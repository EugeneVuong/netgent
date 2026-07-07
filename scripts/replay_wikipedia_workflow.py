"""Replay the saved Wikipedia scroll workflow JSON via the engine only — no LLM.

Usage:
    uv run python scripts/replay_wikipedia_workflow.py \
        --url https://en.wikipedia.org/wiki/Internet \
        --pause-seconds 2
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from main import NetGent  # noqa: E402


def _strip_artifacts(value):
    if isinstance(value, dict):
        return {
            key: _strip_artifacts(nested)
            for key, nested in value.items()
            if key not in ("screenshot", "har")
        }
    if isinstance(value, list):
        return [_strip_artifacts(nested) for nested in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://en.wikipedia.org/wiki/Internet")
    parser.add_argument("--pause-seconds", default="2")
    parser.add_argument(
        "--workflow",
        default=os.path.join(os.path.dirname(__file__), "workflow", "run_wikipedia_workflow.json"),
        help="Path to the saved workflow JSON.",
    )
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    with open(args.workflow, encoding="utf-8") as f:
        workflow = json.load(f)

    result = NetGent(cdp_url=None, headless=args.headless).run_workflow(
        workflow,
        parameters={
            "url": args.url,
            "pause_seconds": args.pause_seconds,
        },
        type="browser",
    )
    print(json.dumps(_strip_artifacts(result), indent=2, default=str))


if __name__ == "__main__":
    main()
