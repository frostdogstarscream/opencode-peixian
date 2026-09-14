"""Export the console contract offline; no lifespan, database or network access."""
import argparse
import json
from pathlib import Path

from control.app import create_app
from control.openapi import build_openapi


def export_openapi(destination=None):
    target = Path(destination) if destination is not None else Path(__file__).parent / "docs" / "openapi.json"
    schema = build_openapi(create_app())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Output JSON path; defaults to docs/openapi.json")
    args = parser.parse_args()
    target = export_openapi(args.output)
    print("OpenAPI contract exported: " + str(target))


if __name__ == "__main__":
    main()
