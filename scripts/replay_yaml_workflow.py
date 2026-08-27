#!/usr/bin/env -S uv run python
"""Replay any workflow file (YAML or JSON) via the engine only — no LLM.

Generic runner: point it at a workflow file and pass its declared parameters
as ``--param name=value``. Every action's progress screenshot, a run log, and
the stripped result are written to::

    debug_artifacts/<workflow-stem>/<run-id>/
        00_go_to_url.png ... run.log  result.json

Usage:
    uv run python scripts/replay_yaml_workflow.py \\
        scripts/workflow/youtube_search_play_workflow.yaml \\
        --param query="big buck bunny" --param watch_seconds=20 --runs 2
"""

import argparse
import base64
import json
import logging
import os
import sys
import time

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from main import NetGent  # noqa: E402

ARTIFACT_ROOT = os.path.join(os.path.dirname(__file__), "..", "debug_artifacts")


def load_workflow(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        if path.endswith((".yaml", ".yml")):
            return yaml.safe_load(f)
        return json.load(f)


def parse_params(pairs: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--param expects name=value, got {pair!r}")
        name, value = pair.split("=", 1)
        params[name.strip()] = value
    return params


def _strip_artifacts(value):
    if isinstance(value, dict):
        return {k: _strip_artifacts(v) for k, v in value.items() if k not in ("screenshot", "har")}
    if isinstance(value, list):
        return [_strip_artifacts(v) for v in value]
    return value


def _save_screenshots(result: dict, workflow: dict, run_dir: str) -> int:
    saved = 0
    outputs = (result.get("result") or {}).get("output") or []
    action_types = [a["type"] for a in workflow["states"][0]["actions"]]
    for state_outputs in outputs:
        for index, action_result in enumerate(state_outputs):
            shot = (
                (action_result.get("screenshot") or {}).get("b64")
                if isinstance(action_result, dict)
                else None
            )
            if not shot:
                continue
            label = action_types[index] if index < len(action_types) else "action"
            with open(os.path.join(run_dir, f"{index:02d}_{label}.png"), "wb") as f:
                f.write(base64.b64decode(shot))
            saved += 1
    return saved


def _summarize(result: dict, workflow: dict) -> dict:
    inner = result.get("result") or {}
    outputs = inner.get("output") or []
    total = len(workflow["states"][0]["actions"])
    completed = sum(len(s) for s in outputs)
    final_url = None
    for action_result in reversed(outputs[-1] if outputs else []):
        if isinstance(action_result, dict) and action_result.get("url"):
            final_url = action_result["url"]
            break
    summary = {
        "success": bool(inner.get("success")),
        "error": inner.get("error"),
        "actions_completed": f"{completed}/{total}",
        "final_url": final_url,
    }
    if "failed_action_index" in inner:
        summary["failed_action"] = (
            f"#{inner['failed_action_index']} {inner.get('failed_action_type')}"
        )
    return summary


def run_once(*, workflow, parameters, headless, run_dir, action_period) -> dict:
    os.makedirs(run_dir, exist_ok=True)
    handler = logging.FileHandler(os.path.join(run_dir, "run.log"), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    started = time.perf_counter()
    try:
        result = NetGent(cdp_url=None, headless=headless).run_workflow(
            workflow, parameters=parameters, type="browser", action_period=action_period
        )
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()

    screenshots = _save_screenshots(result, workflow, run_dir)
    with open(os.path.join(run_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(_strip_artifacts(result), f, indent=2, default=str)

    summary = _summarize(result, workflow)
    summary["elapsed_s"] = round(time.perf_counter() - started, 1)
    summary["screenshots"] = screenshots
    summary["run_dir"] = os.path.relpath(run_dir)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", help="Path to a .yaml/.yml/.json workflow file.")
    parser.add_argument(
        "--param", action="append", default=[], metavar="NAME=VALUE", help="Workflow parameter."
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--cooldown-seconds", type=float, default=30.0)
    parser.add_argument("--action-period", type=float, default=3.0)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    workflow = load_workflow(args.workflow)
    parameters = parse_params(args.param)
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
