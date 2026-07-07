"""Replay the Prudentia YouTube video-on-demand workflow — engine only, no LLM.

Plays a DASH stream in the public dash.js reference player — a no-account
stand-in for Prudentia's video-on-demand category (SIGCOMM '24, Table 1).
See docs/prudentia_application_workflows.md.

Usage:
    uv run python scripts/replay_prudentia_dash_vod.py                # full 600 s run
    uv run python scripts/replay_prudentia_dash_vod.py --watch-seconds 30
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
        "--mpd-url",
        default="https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd",
        help="DASH manifest URL (default: Big Buck Bunny public test stream on Akamai).",
    )
    parser.add_argument(
        "--watch-seconds",
        default="600",
        help="Playback duration; Prudentia uses 600 s per experiment.",
    )
    parser.add_argument(
        "--workflow",
        default=os.path.join(
            os.path.dirname(__file__), "workflow", "prudentia_dash_vod_workflow.json"
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
            "mpd_url": args.mpd_url,
            "watch_seconds": args.watch_seconds,
        },
        type="browser",
    )
    print(json.dumps(_strip_artifacts(result), indent=2, default=str))


if __name__ == "__main__":
    main()
