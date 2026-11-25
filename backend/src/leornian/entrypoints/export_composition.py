"""Export the opt-in composition contract, without advertising a nonexistent API."""

import argparse
import json

from leornian.modules.tutor.composition_catalog import component_directory
from leornian.modules.tutor.composition_contracts import LearningComposition
from leornian.modules.tutor.composition_v2_contracts import LearningCompositionV2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=("1", "2"), default="1")
    parser.add_argument("--directory", action="store_true")
    args = parser.parse_args()
    contract = LearningCompositionV2 if args.version == "2" else LearningComposition
    value = component_directory() if args.directory else contract.model_json_schema()
    print(json.dumps(value, ensure_ascii=True))


if __name__ == "__main__":
    main()
