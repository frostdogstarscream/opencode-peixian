"""Validate a stage-one release before emitting a manifest. No credentials required.

Offline checks validate recorded evidence, not the health of a running deployment.
--runtime-evidence additionally requires a freshly collected, sanitized runtime
snapshot; --check-images asks the local Docker daemon to resolve every image ID.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile


def require(condition, code):
    if not condition:
        raise ValueError(code)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_counts(release):
    history = release["historical_runs"]
    budget = release["model_budget"]
    requests = release["model_requests"]
    for value in [history[k] for k in ("old_runs", "new_runs", "current_total_runs", "unchanged", "changed")] + [budget[k] for k in ("prior", "this_release", "round_total", "round_limit")]:
        require(type(value) is int and value >= 0, "invalid_count")
    require(history["old_runs"] + history["new_runs"] == history["current_total_runs"], "run_total_mismatch")
    require(history["unchanged"] + history["changed"] == history["old_runs"], "history_count_mismatch")
    require(budget["prior"] + budget["this_release"] == budget["round_total"] <= budget["round_limit"], "model_budget_mismatch")
    require(len(requests) == budget["this_release"], "request_count_mismatch")
    ids = [r["client_request_id"] for r in requests]
    require(all(isinstance(i, str) and i for i in ids) and len(set(ids)) == len(ids), "duplicate_request_id")
    admitted = [r["run_id"] for r in requests if r.get("run_id")]
    require(len(admitted) == len(set(admitted)) == history["new_runs"], "admitted_run_mismatch")
    require(all(r.get("run_id") or r.get("no_run_reason") for r in requests), "missing_run_explanation")
    disabled = release["disabled_check"]
    require(disabled["runs_before"] == disabled["runs_after"] == history["current_total_runs"], "disabled_check_count_mismatch")
    require(disabled["model_dispatched"] is False, "disabled_check_dispatched")


def check_runtime(release):
    rows = release["runtime_states"]
    require(len(rows) == 2 and {r["account"] for r in rows} == {"alignment-a", "alignment-b"}, "runtime_accounts_mismatch")
    for row in rows:
        require(row["status"] == "ready" and row["applied"] == row["desired"]
                and row["recovery_required"] == 0 and row["gate_policy"] == "open", "runtime_not_ready")
    require(all(release["legacy"][k] == 0 for k in ("installations", "grants", "enabled_versions")), "legacy_still_enabled")


def validate(root, manifest, *, check_images=False, runtime_evidence=None):
    root, manifest = Path(root).resolve(), Path(manifest).resolve()
    release = load(manifest)
    check_counts(release)
    check_runtime(release)
    revisions = [release["source_revision"]] + [v["source_revision"] for v in release["images"].values()]
    for revision in revisions:
        require(bool(re.fullmatch(r"[0-9a-f]{40}", revision)), "invalid_revision")
        require(subprocess.run(["git", "merge-base", "--is-ancestor", revision, "HEAD"], cwd=root, capture_output=True).returncode == 0, "source_not_ancestor")
    require(set(release["images"]) == {"control", "gateway", "agent"}, "image_set_mismatch")
    for image in release["images"].values():
        require(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", image["id"])), "invalid_image_digest")
        if check_images:
            result = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image["id"]], capture_output=True, text=True)
            require(result.returncode == 0 and result.stdout.strip() == image["id"], "image_missing")
    catalog = load(root / "services/peixian-control/control/official_methods.json")["skills"]
    recorded = {v["id"]: v for v in release["methods"]}
    require(len(recorded) == len(release["methods"]) == len(catalog), "method_set_mismatch")
    for method in catalog:
        content = (root / "deploy/peixian/examples/seven_data_plugins/skills" / method["method"] / "SKILL.md").read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        require(digest == method["sha256"] == recorded[method["id"]]["content_sha256"], "skill_hash_mismatch")
        require(content.decode() == method["content"] and recorded[method["id"]]["state"] == method["state"]
                and recorded[method["id"]]["version"] == method["version"], "method_identity_mismatch")
    path = root / "deploy/peixian/examples/seven_data_plugins/package.py"
    spec = importlib.util.spec_from_file_location("stage1_plugin_package", path)
    packager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packager)
    with tempfile.TemporaryDirectory() as temporary:
        built = packager.build(temporary)
        expected = {v["id"] + "-" + v["version"] + ".zip": v["sha256"] for v in built}
        require(len(release["plugins"]) == len(expected) == 7, "plugin_count_mismatch")
        require({v["file"]: v["sha256"] for v in release["plugins"]} == expected, "plugin_hash_mismatch")
    checksum = manifest.parent / "seven-plugins-pr1-4-SHA256SUMS.txt"
    seen = set()
    for line in checksum.read_text().splitlines():
        digest, name = line.split("  ", 1)
        require(name == Path(name).name and name not in seen, "invalid_checksum_path")
        seen.add(name)
        require(hashlib.sha256((checksum.parent / name).read_bytes()).hexdigest() == digest, "checksum_mismatch")
    require(seen == {"seven-plugins-pr1-4-" + name for name in ("acceptance.md", "operations.md", "user-guide.md", "release.json", "openapi.json")}, "checksum_set_mismatch")
    if runtime_evidence:
        live = load(runtime_evidence)
        from datetime import datetime, timezone
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(live["observed_at"])).total_seconds()
        require(0 <= age <= 60, "stale_runtime_evidence")
        check_runtime(live)
        require(live["runtime_states"] == release["runtime_states"] and live["legacy"] == release["legacy"], "live_evidence_mismatch")
    return release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--check-images", action="store_true")
    parser.add_argument("--runtime-evidence", type=Path)
    parser.add_argument("--output", type=Path, help="Write a validated copy; refuse existing output")
    args = parser.parse_args()
    manifest = args.manifest or args.root / "specs/seven-plugins-pr1-4-release.json"
    release = validate(args.root, manifest, check_images=args.check_images, runtime_evidence=args.runtime_evidence)
    if args.output:
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(release, output, ensure_ascii=False, indent=2)
            output.write("\n")
    print(json.dumps({"validated": True, "mode": "runtime-evidence" if args.runtime_evidence else "recorded-evidence", "image_existence_checked": args.check_images}))


if __name__ == "__main__":
    main()
