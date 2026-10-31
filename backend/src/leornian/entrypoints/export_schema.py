import json
from pathlib import Path

from leornian.delivery.contracts import PublicEvent
from leornian.entrypoints.api import create_app


def main() -> None:
    schema = create_app().openapi()
    event_schema = PublicEvent.model_json_schema(ref_template="#/components/schemas/{model}")
    definitions = event_schema.pop("$defs", {})
    schema["components"]["schemas"].update(definitions)
    schema["components"]["schemas"]["PublicEvent"] = event_schema
    target = Path(__file__).parents[4] / "packages" / "api-contracts" / "openapi.json"
    target.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
