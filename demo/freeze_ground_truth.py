"""Re-freeze demo/ground-truth.json (fixture fingerprint) after an intentional, documented fixture change.

Usage: uv run python demo/freeze_ground_truth.py
Record every re-freeze and its reason in docs/compatibility.md. Never edit labels to improve measured scores.
"""

import json
import sys
from pathlib import Path

from secureyourcode.demo_eval import freeze_ground_truth
from secureyourcode.schemas import SCORING_VERSION


def main() -> int:
    here = Path(__file__).resolve().parent
    truth_path = here / "ground-truth.json"
    entries = json.loads(truth_path.read_text(encoding="utf-8"))["entries"]
    truth = freeze_ground_truth(entries, here / "DemoShop", truth_path, SCORING_VERSION)
    print(truth.fixture_fingerprint)
    return 0


if __name__ == "__main__":
    sys.exit(main())
