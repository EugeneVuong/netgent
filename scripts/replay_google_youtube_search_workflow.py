"""Replay the Google -> YouTube search-and-play workflow via the engine only — no LLM.

Flow: open Google, search for "youtube", click the YouTube result, search on
YouTube, click the first video, keep it playing for ``--watch-seconds``.

Every action's progress screenshot is written to disk alongside a run log so
each replay can be inspected after the fact:

    debug_artifacts/google_youtube_search/<run-id>/
        00_go_to_url.png
        01_input_text.png
        ...
        run.log
        result.json

Pass ``--runs N`` to replay the workflow N times in fresh browsers and print a
per-run consistency summary.

Usage:
    uv run python scripts/replay_google_youtube_search_workflow.py
    uv run python scripts/replay_google_youtube_search_workflow.py \
        --youtube-query "big buck bunny" --watch-seconds 20 --runs 3 --headless
"""

import argparse
import base64
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from main import NetGent  # noqa: E402

DEFAULT_WORKFLOW = os.path.join(
    os.path.dirname(__file__), "workflow", "run_google_youtube_search_workflow.json"
)
DEFAULT_ARTIFACT_ROOT = os.path.join(
    os.path.dirname(__file__), "..", "debug_artifacts", "google_youtube_search"
)


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


def _save_screenshots(result: dict, workflow: dict, run_dir: str) -> list[str]:
    """Write each action's base64 screenshot to ``run_dir``. Returns saved paths."""
    saved: list[str] = []
    outputs = (result.get("result") or {}).get("output") or []
    action_types = [a["type"] for a in workflow["states"][0]["actions"]]
    for state_outputs in outputs:
        for index, action_result in enumerate(state_outputs):
            if not isinstance(action_result, dict):
                continue
            shot = (action_result.get("screenshot") or {}).get("b64")
            if not shot:
                continue
            label = action_types[index] if index < len(action_types) else "action"
            path = os.path.join(run_dir, f"{index:02d}_{label}.png")
            with open(path, "wb") as f:
                f.write(base64.b64decode(shot))
            saved.append(path)
    return saved


def _attach_file_logger(run_dir: str) -> logging.Handler:
    handler = logging.FileHandler(os.path.join(run_dir, "run.log"), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    return handler


def _summarize(result: dict, workflow: dict) -> dict:
    inner = result.get("result") or {}
    outputs = inner.get("output") or []
    total_actions = len(workflow["states"][0]["actions"])
    completed = sum(len(s) for s in outputs) if outputs else 0
    final_url = None
    if outputs and outputs[-1]:
        last = outputs[-1][-1]
        if isinstance(last, dict):
            final_url = last.get("url")
    # ``wait`` doesn't report a URL; fall back to the last action that did.
    if final_url is None and outputs:
        for action_result in reversed(outputs[-1]):
            if isinstance(action_result, dict) and action_result.get("url"):
                final_url = action_result["url"]
                break
    summary = {
        "success": bool(inner.get("success")),
        "error": inner.get("error"),
        "actions_completed": f"{completed}/{total_actions}",
        "final_url": final_url,
    }
    if "failed_action_index" in inner:
        summary["failed_action"] = (
            f"#{inner['failed_action_index']} {inner.get('failed_action_type')}"
        )
    return summary


def run_once(
    *, workflow: dict, parameters: dict, headless: bool, run_dir: str, action_period: float
) -> dict:
    os.makedirs(run_dir, exist_ok=True)
    handler = _attach_file_logger(run_dir)
    started = time.perf_counter()
    try:
        result = NetGent(cdp_url=None, headless=headless).run_workflow(
            workflow,
            parameters=parameters,
            type="browser",
            action_period=action_period,
        )
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()

    screenshots = _save_screenshots(result, workflow, run_dir)
    stripped = _strip_artifacts(result)
    with open(os.path.join(run_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(stripped, f, indent=2, default=str)

    summary = _summarize(result, workflow)
    summary["elapsed_s"] = round(time.perf_counter() - started, 1)
    summary["screenshots"] = len(screenshots)
    summary["run_dir"] = os.path.relpath(run_dir)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--google-query", default="youtube")
    parser.add_argument("--youtube-query", default="big buck bunny")
    parser.add_argument("--watch-seconds", default="20")
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--artifact-root", default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--runs", type=int, default=1, help="Replay N times for consistency.")
    parser.add_argument(
        "--action-period",
        type=float,
        default=3.0,
        help="Seconds the engine sleeps between actions (default 3).",
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=float,
        default=300.0,
        help="Pause between runs; Google's bot check trips on rapid repeated searches.",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    with open(args.workflow, encoding="utf-8") as f:
        workflow = json.load(f)

    parameters = {
        "google_query": args.google_query,
        "youtube_query": args.youtube_query,
        "watch_seconds": args.watch_seconds,
    }

    batch_id = time.strftime("%Y%m%d-%H%M%S")
    summaries = []
    for run_index in range(1, args.runs + 1):
        run_dir = os.path.join(args.artifact_root, f"{batch_id}_run{run_index:02d}")
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
            logging.getLogger(__name__).info(
                "cooldown %.0fs before next run", args.cooldown_seconds
            )
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
