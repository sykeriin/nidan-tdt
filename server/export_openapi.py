"""Write the OpenAPI schema: python -m server.export_openapi  -> docs/openapi.json"""
import json
from pathlib import Path

from server.app import app

OUT = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"

if __name__ == "__main__":
    OUT.write_text(json.dumps(app.openapi(), indent=1), encoding="utf-8")
    print(OUT)
