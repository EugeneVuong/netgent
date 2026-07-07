"""Replay the Prudentia-style bulk download workflow — engine only, no LLM.

Stand-in for the file-transfer category from "Prudentia: Findings of an
Internet Fairness Watchdog" (SIGCOMM '24, Table 1): Dropbox/Drive/OneDrive/
Mega each download a 10 GB file. This uses a public speed-test file instead,
so no account or upload is needed. The payload is discarded to /dev/null.
Transfer duration is governed by the file size (Hetzner offers 100MB.bin,
1GB.bin, 10GB.bin). Requires wget (`brew install wget`).

Usage:
    uv run python scripts/replay_prudentia_bulk_download.py            # 1 GB file
    uv run python scripts/replay_prudentia_bulk_download.py \
        --url https://ash-speed.hetzner.com/10GB.bin
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Shell actions read USE_LOCAL at import time; force local mode for macOS
# (namespace mode is Linux-only). See run_netgent.py.
os.environ["USE_LOCAL"] = "true"

from main import NetGent  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="https://ash-speed.hetzner.com/1GB.bin",
        help="Public file to download (Hetzner speed-test file by default).",
    )
    parser.add_argument(
        "--timeout-seconds",
        default="30",
        help="wget network stall/connect timeout (not a duration cap).",
    )
    parser.add_argument(
        "--workflow",
        default=os.path.join(
            os.path.dirname(__file__), "workflow", "prudentia_bulk_download_workflow.json"
        ),
        help="Path to the saved workflow JSON.",
    )
    args = parser.parse_args()

    with open(args.workflow, encoding="utf-8") as f:
        workflow = json.load(f)

    result = NetGent().run_workflow(
        workflow,
        parameters={
            "url": args.url,
            "timeout_seconds": args.timeout_seconds,
        },
        type="shell",
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
