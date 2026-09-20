import json
from pathlib import Path

from app import app


output = Path(__file__).parents[2] / "specs" / "peixian-data-adapter-openapi.yaml"
output.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
print(output)
