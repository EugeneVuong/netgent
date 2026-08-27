#!/usr/bin/env -S uv run python
"""Replay the DuckDuckGo -> YouTube search-and-play workflow — engine only, no LLM.

Flow: open DuckDuckGo, search for "youtube", click the YouTube result, search
on YouTube, click the first real video, keep it playing for
``--watch-seconds``, and assert the player is actually playing.

Defaults to the hand-authored YAML; pass ``--workflow`` to replay the
LLM-generated JSON instead. Per-action screenshots, run.log and result.json
are written under debug_artifacts/<workflow-name>/<run-id>/ and ``--runs N``
prints an N-run consistency summary.

Usage:
    uv run python scripts/replay_duckduckgo_youtube_search_workflow.py
    uv run python scripts/replay_duckduckgo_youtube_search_workflow.py \\
        --youtube-query "big buck bunny" --watch-seconds 20 --runs 3
    uv run python scripts/replay_duckduckgo_youtube_search_workflow.py \\
        --workflow scripts/workflow/duckduckgo_youtube_search_workflow.json
"""

import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from replay_yaml_workflow import ARTIFACT_ROOT, load_workflow, run_once  # noqa: E402

DEFAULT_WORKFLOW = os.path.join(
    os.path.dirname(__file__), "workflow", "duckduckgo_youtube_search_workflow.yaml"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search-query", default="youtube", help="Query typed into DuckDuckGo.")
    parser.add_argument(
        "--youtube-query", default="big buck bunny", help="Query typed into YouTube."
    )
    parser.add_argument("--watch-seconds", default="20", help="How long to keep the video playing.")
    parser.add_argument(
        "--workflow", default=DEFAULT_WORKFLOW, help="Path to the workflow file (.yaml or .json)."
    )
    parser.add_argument("--runs", type=int, default=1, help="Replay N times for consistency.")
    parser.add_argument("--cooldown-seconds", type=float, default=15.0)
    parser.add_argument("--action-period", type=float, default=3.0)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    workflow = load_workflow(args.workflow)
    parameters = {
        "search_query": args.search_query,
        "youtube_query": args.youtube_query,
        "watch_seconds": args.watch_seconds,
    }
    stem = os.path.splitext(os.path.basename(args.workflow))[0]
    batch_id = time.strftime("%Y%m%d-%H%M%S")

    summaries = []
    for run_index in range(1, args.runs + 1):
        run_dir = os.path.join(ARTIFACT_ROOT, stem, f"{batch_id}_run{run_index:02d}")
        logging.getLogger(__name__).info("=== run %s/%s -> %s", run_index, args.runs, run_dir)
        summary = run_once(
            workflow=workflow,
            parameters=parameters,
            headless=args.headless,
            run_dir=run_dir,
            action_period=args.action_period,
        )
        summaries.append(summary)
        print(json.dumps(summary, indent=2, default=str))
        if run_index < args.runs and args.cooldown_seconds > 0:
            time.sleep(args.cooldown_seconds)

    passed = sum(1 for s in summaries if s["success"])
    print(f"\n=== consistency: {passed}/{len(summaries)} runs succeeded ===")
    for index, s in enumerate(summaries, 1):
        status = "PASS" if s["success"] else f"FAIL ({s['error']})"
        print(f"  run {index}: {status}  actions={s['actions_completed']}  url={s['final_url']}")
    if passed != len(summaries):
        sys.exit(1)


if __name__ == "__main__":
    main()
