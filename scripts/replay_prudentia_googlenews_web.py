"""Replay the Prudentia youtube.com web-browsing workflow — engine only, no LLM.

Reproduces the news.google.com web workload from "Prudentia: Findings of an Internet
Fairness Watchdog" (SIGCOMM '24, section 5.2; Table 1: BBRv3.0, >20 flows, text with thumbnails):
load the page 10 times with 45 s between loads. Prudentia uses a fresh
Chrome instance with wiped cache/cookies per
load; NetGent approximates this with repeated navigations inside one fresh
browser context per run. See docs/prudentia_application_workflows.md.

Usage:
    uv run python scripts/replay_prudentia_googlenews_web.py                 # 10 loads, 45 s apart
    uv run python scripts/replay_prudentia_googlenews_web.py --gap-seconds 5
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
    parser.add_argument(
        "--page-url",
        default="https://news.google.com/",
        help="Webpage to load repeatedly.",
    )
    parser.add_argument(
        "--gap-seconds",
        default="45",
        help="Wait between page loads; Prudentia uses 45 s.",
    )
    parser.add_argument(
        "--workflow",
        default=os.path.join(
            os.path.dirname(__file__), "workflow", "prudentia_googlenews_web_workflow.json"
        ),
        help="Path to the saved workflow JSON.",
    )
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    with open(args.workflow, encoding="utf-8") as f:
        workflow = json.load(f)

    result = NetGent(cdp_url=None, headless=args.headless).run_workflow(
        workflow,
        parameters={
            "page_url": args.page_url,
            "gap_seconds": args.gap_seconds,
        },
        type="browser",
    )
    print(json.dumps(_strip_artifacts(result), indent=2, default=str))


if __name__ == "__main__":
    main()
