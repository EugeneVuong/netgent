"""Replay the Prudentia iPerf baseline workflow — engine only, no LLM.

Reproduces the iPerf baseline from "Prudentia: Findings of an Internet
Fairness Watchdog" (SIGCOMM '24, Table 1): a single bulk-transfer flow used
as the CCA-only comparison point. The CCA variant (BBR/Cubic/NewReno in the
paper) is whatever this machine's kernel uses. Requires iperf3
(`brew install iperf3`) and a reachable iperf3 server.

Usage:
    uv run python scripts/replay_prudentia_iperf_baseline.py          # 600 s run
    uv run python scripts/replay_prudentia_iperf_baseline.py --duration-seconds 10
    uv run python scripts/replay_prudentia_iperf_baseline.py --host <your-server>
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
        "--host",
        default="speedtest.wtnet.de",
        help="iperf3 server (default: wilhelm.tel's public server; public servers "
        "are shared and may report 'busy' — retry or pick another, e.g. "
        "iperf.he.net:5201).",
    )
    parser.add_argument("--port", default="5200")
    parser.add_argument(
        "--duration-seconds",
        default="600",
        help="Transfer duration; Prudentia uses 600 s per experiment.",
    )
    parser.add_argument(
        "--workflow",
        default=os.path.join(
            os.path.dirname(__file__), "workflow", "prudentia_iperf_baseline_workflow.json"
        ),
        help="Path to the saved workflow JSON.",
    )
    args = parser.parse_args()

    with open(args.workflow, encoding="utf-8") as f:
        workflow = json.load(f)

    result = NetGent().run_workflow(
        workflow,
        parameters={
            "host": args.host,
            "port": args.port,
            "duration_seconds": args.duration_seconds,
        },
        type="shell",
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
