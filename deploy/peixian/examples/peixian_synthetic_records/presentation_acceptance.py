"""Publish traced presentation plugin; total budget 40 includes ten prior requests.
Use --prepare ACCOUNT before --run ACCOUNT; a failed case is never retried.
"""
import argparse
import fcntl
import hashlib
import io
import json
from pathlib import Path
import subprocess
import time
import zipfile
from provision_platform import acceptance_class
from accept_registered_tools import agent_messages, container_json, PROBE_AGENT
from agent_acceptance_evidence import current_turn

ROOT = Path(__file__).resolve().parent
DEPLOY = Path("/srv/peixian-alignment-20260917")
REPORT = DEPLOY / "presentation-acceptance-20260918.json"
SCENARIOS = [("DEMO-CASE-GAMBLING", "gambling-materials", "涉赌案件资料整理（代码核对演示）"), ("DEMO-CASE-THEFT", "theft-timeline", "盗窃案件时空资料核对（代码核对演示）")]
PID = "peixian-synthetic-records"


def package():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("manifest.json", "entry.mjs", "engine.mjs", "legacy.mjs", "fixtures.json"):
            info = zipfile.ZipInfo(name, (2026, 9, 18, 0, 0, 0))
            z.writestr(info, (ROOT / "presentation-plugin" / name).read_bytes())
    return buffer.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run"])
    parser.add_argument("account", choices=["alignment-a", "alignment-b"])
    parser.add_argument("--batch", choices=["ui13"], default="ui13")
    parser.add_argument("--scenario", choices=["DEMO-CASE-GAMBLING","DEMO-CASE-THEFT"])
    args = parser.parse_args()
    report = json.loads(REPORT.read_text()) if REPORT.exists() else {"model_limit": 40, "prior_requests": 10, "cases": [], "prepared": {}, "scope": "code_prepared_scenarios"}
    api = acceptance_class(DEPLOY)(DEPLOY)
    def save():
        temporary = REPORT.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        temporary.replace(REPORT)
    try:
        su = api.login("admin")
        client = api.login(args.account)
        if args.account == "alignment-b":
            first = [c for c in report["cases"] if c["account"] == "alignment-a" and c.get("batch") == args.batch]
            assert len(first) == 2 and all(c["status"] == "passed" or c.get("reevaluation",{}).get("status")=="passed" for c in first), "first_account_must_pass"
        if args.action == "prepare":
            blob = package()
            published = api.request(su, "GET", "/admin/plugins")["items"]
            if not any(x["id"] == PID and x["version"] == "1.3.0" for x in published):
                api.request(su, "POST", "/admin/plugins", files={"file": ("scenario-1.3.0.zip", blob, "application/zip")})
            conns = api.request(su, "GET", "/admin/connections")["items"]
            connection = next(x for x in conns if x["name"] == "沛县七项合成资料服务")
            api.request(su, "PUT", "/admin/plugins/"+PID+"/1.3.0/connections", json={"bindings": {"peixian_records": connection["id"]}})
            templates = api.request(su, "GET", "/admin/templates")["items"]
            template_ids = {}
            for sid, slug, name in SCENARIOS:
                content = (ROOT / "facts-skills" / slug / "SKILL.md").read_text()
                found = [t for t in templates if t["name"] == name]
                if found:
                    assert len(found) == 1 and found[0]["content"] == content
                    template_ids[sid] = found[0]["id"]
                else:
                    template_ids[sid] = api.request(su, "POST", "/admin/templates", json={"name": name, "description": "固定合成场景的资料整理与证据引用，不作犯罪判断。", "content": content})["id"]
            existing = api.request(client, "GET", "/plugins")["items"]
            old = next(x for x in existing if x["id"] == PID)
            report["prepared"].setdefault(args.account, {"previous_install": {k: old.get(k) for k in ("version", "enabled", "installed_version")}, "skills": {}})
            report["package_sha256"] = hashlib.sha256(blob).hexdigest(); save()
            api.request(client, "PUT", "/plugins/"+PID, json={"version": "1.3.0", "enabled": True, "config": {}})
            api.ready(client, seconds=300)
            previous=json.loads((DEPLOY / "facts-acceptance-20260918.json").read_text())
            report["prepared"][args.account]["skills"]=previous["prepared"][args.account]["skills"]
            save()
            for sid, slug, name in SCENARIOS:
                if sid not in report["prepared"][args.account]["skills"]:
                    copied = api.request(client, "POST", "/templates/"+template_ids[sid]+"/copy", json={})
                    report["prepared"][args.account]["skills"][sid] = {"id": copied["id"], "name": name}; save()
            api.ready(client, seconds=300)
            assert api.request(client, "POST", "/plugins/"+PID+"/test", json={})["ok"]
            uid = api.request(client, "GET", "/me")["user"]["id"]
            ids = subprocess.check_output(["docker", "ps", "-q", "--filter", "label=peixian.uid="+uid], text=True).split()
            containers = json.loads(subprocess.check_output(["docker", "inspect", *ids], text=True))
            agent = next(x for x in containers if x["Config"]["Labels"].get("com.docker.compose.service") == "agent" and x["Config"]["Labels"].get("peixian.deployment") == DEPLOY.name)
            report["prepared"][args.account]["container"] = agent["Name"].lstrip("/")
            registry = container_json(agent["Name"], PROBE_AGENT.replace("peixian_get_", "peixian_"))
            assert "peixian_prepare_scenario_facts" in registry["registered"]
            model = next(x for x in registry["models"] if x["model"] == api.state["model"])
            context = next(x for x in model["tools"] if x["id"] == "peixian_prepare_scenario_facts")
            assert set(context["parameters"]["properties"]["scenario_id"]["enum"]) == {x[0] for x in SCENARIOS}
            report["prepared"][args.account]["registry_verified"] = True; save()
            print("prepared_and_registered:"+args.account, flush=True); return
        prepared = report["prepared"][args.account]
        assert prepared["registry_verified"]
        for scenario, slug, name in SCENARIOS:
            if args.scenario and args.scenario!=scenario: continue
            assert len(report["cases"]) + report["prior_requests"] < 40
            assert not any(c["account"] == args.account and c["scenario"] == scenario and c.get("batch") == args.batch for c in report["cases"]), "request_already_attempted"
            session = api.request(client, "POST", "/sessions", json={"title": name})["id"]
            case = {"account": args.account, "scenario": scenario, "session_id": session, "status": "submitting", "batch": args.batch}
            report["cases"].append(case); save()
            started = time.monotonic()
            try:
                skill = prepared["skills"][scenario]
                text = "这是合成资料验收。先调用 skill 加载《"+name+"》，然后严格执行该 Skill 的固定场景工具流程（场景编号 "+scenario+"），每个所需工具只调用一次。事实内容由页面展示，最终只输出 Skill 规定的完成提示，不重写事实。不得给出人员犯罪判断或风险等级。"
                api.request(client, "POST", "/sessions/"+session+"/messages", json={"text": text, "model_id": api.state["model"], "skill_ids": [skill["id"]]})
                while time.monotonic()-started < 180:
                    messages = api.request(client, "GET", "/sessions/"+session+"/messages")["items"]
                    turn = current_turn(messages)
                    if any(m["info"].get("error") for m in turn): raise RuntimeError("model_error")
                    if turn and turn[-1]["info"].get("finish") in ("stop", "end_turn") and turn[-1]["info"].get("time", {}).get("completed"): break
                    time.sleep(2)
                else: raise RuntimeError("result_unknown_timeout")
                evidence = api.request(client, "GET", "/sessions/"+session+"/evidence")
                assert evidence["status"] == "complete" and evidence["scenario"]["scenario_id"] == scenario, "evidence_incomplete"
                assert evidence.get("summary_check") == "checked" and evidence.get("verified_summary"), "summary_not_checked"
                assert len(evidence["presentation"]["process"]) == 5
                assert all(s["status"] == "completed" and s["time"] != "—" for s in evidence["presentation"]["process"]), "trace_incomplete"
                assert len(evidence["presentation"]["evidence"]) == 4
                raw = current_turn(agent_messages(prepared["container"], session))
                parts = [p for m in raw for p in m.get("parts", []) if p.get("type") == "tool"]
                modules = ["night", "portrait", "funds", "lookup"] if slug == "gambling-materials" else ["night", "portrait", "vehicle"]
                expected = ["skill", "peixian_prepare_scenario_facts", "peixian_check_scenario_summary"]
                names = [p.get("tool") for p in parts]
                assert names[:2] == expected[:2] and sorted(names) == sorted(expected), "tool_chain_mismatch"
                assert all(p["state"]["status"] == "completed" for p in parts)
                assert parts[0]["state"]["input"]["name"] == name
                text = "".join(p.get("text", "") for p in turn[-1].get("parts", []) if p.get("type") == "text")
                assert text.strip() == "已完成资料核对，请查看页面“已核对摘要”和“资料缺口”。本次为完全合成演示资料，不作犯罪判断。", "unverified_final_rewrite"
                other = api.login("alignment-b" if args.account == "alignment-a" else "alignment-a")
                assert other.get("/sessions/"+session+"/evidence").status_code == 404
                case.update(status="passed", seconds=round(time.monotonic()-started, 2), tool_chain=names, card_count=len(evidence["cards"]), checked_count=len(evidence["verified_summary"]), cross_account_denied=True, answer=text)
            except Exception as exc:
                case.update(status="failed", reason=type(exc).__name__+":"+str(exc)[:180])
                try: api.request(client, "POST", "/sessions/"+session+"/abort", json={})
                except Exception: case["abort_unconfirmed"] = True
            save(); print(json.dumps({k:v for k,v in case.items() if k!="answer"}, ensure_ascii=False), flush=True)
            if case["status"] != "passed": raise SystemExit(1)
    finally: api.clients.close()

if __name__ == "__main__":
    with REPORT.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        main()
