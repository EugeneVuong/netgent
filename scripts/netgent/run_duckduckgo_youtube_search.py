"""Generate and run a DuckDuckGo -> YouTube search-and-play workflow from a natural-language spec (LLM).

The browser subagent searches DuckDuckGo for "youtube", clicks through to
YouTube, searches for a video, plays it, and records the interaction as a
workflow. DuckDuckGo is used (rather than Google) because it has no reCAPTCHA
bot check, so generation and replay are repeatable back-to-back.

Requires an LLM API key in the repo-root `.env` (GOOGLE_API_KEY or
ANTHROPIC_API_KEY, matching NETGENT_LLM_PROVIDER). The generated workflow is
saved to scripts/workflow/duckduckgo_youtube_search_workflow.json so it can
later be replayed without the LLM:

    uv run python scripts/replay_yaml_workflow.py \\
        scripts/workflow/duckduckgo_youtube_search_workflow.json \\
        --param search_query=youtube --param youtube_query="big buck bunny" \\
        --param watch_seconds=20

Pass ``--attempts N`` to generate N times and report how consistent the
generated action sequences are; each attempt is also saved as
``duckduckgo_youtube_search_workflow.attemptNN.json``. The canonical artifact
is overwritten with the last successful attempt.

Usage:
    uv run python scripts/netgent/run_duckduckgo_youtube_search.py \\
        --youtube-query "big buck bunny" --watch-seconds 20 --attempts 2
"""

import argparse
import asyncio
import json
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from main import NetGent  # noqa: E402

WORKFLOW_DIR = os.path.join(os.path.dirname(__file__), "..", "workflow")
WORKFLOW_NAME = "duckduckgo_youtube_search_workflow"


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


def _write_workflow(workflow: dict, filename: str) -> str:
    os.makedirs(WORKFLOW_DIR, exist_ok=True)
    path = os.path.join(WORKFLOW_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(workflow, f, indent=2)
        f.write("\n")
    return path


def _append_playing_assertion(workflow: dict) -> dict:
    """Append ``assert_media_playing`` so a replay fails if the player is
    paused — the LLM never emits it, and "all actions ran" alone does not
    prove the video played."""
    states = workflow.get("states") or []
    if not states:
        return workflow
    actions = states[-1].setdefault("actions", [])
    if not any(a.get("type") == "assert_media_playing" for a in actions):
        actions.append(
            {
                "type": "assert_media_playing",
                "params": {"selector": "video", "min_seconds": 5},
            }
        )
    return workflow


def _action_signature(workflow: dict) -> list[str]:
    """Compact per-action fingerprint used to compare generated attempts."""
    signature: list[str] = []
    for state in workflow.get("states") or []:
        for action in state.get("actions") or []:
            params = action.get("params") or {}
            key = params.get("text") or params.get("url") or params.get("keys") or ""
            signature.append(f"{action.get('type')}({key})")
    return signature


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and run a DuckDuckGo -> YouTube search-and-play workflow."
    )
    parser.add_argument("--search-query", default="youtube")
    parser.add_argument("--youtube-query", default="big buck bunny")
    parser.add_argument("--watch-seconds", default="20")
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

    specification = """1. Go to 'https://duckduckgo.com'.
    2. Type <secret>search_query</secret> into the DuckDuckGo search box and press Enter to search.
    3. On the results page, click the first result, which links to youtube.com (do not open it in a new tab).
    4. Once on YouTube, wait a few seconds for the page to finish loading.
    5. Type <secret>youtube_query</secret> into the YouTube search box and press Enter.
    6. In the search results, click the first regular video (not an ad, Short, channel, or playlist).
    7. The video starts playing automatically once the watch page loads. Do not click the player or the play button, since that would pause it.
    8. Keep the video playing for <secret>watch_seconds</secret> seconds, then stop."""
    parameters = {
        "search_query": args.search_query,
        "youtube_query": args.youtube_query,
        "watch_seconds": args.watch_seconds,
    }

    client = NetGent(cdp_url=None, headless=args.headless)
    signatures: list[list[str] | None] = []
    for attempt in range(1, args.attempts + 1):
        print(f"\n=== generation attempt {attempt}/{args.attempts} ===")
        generated = await client.generate(
            specification,
            type="browser",
            parameters=parameters,
        )
        workflow = generated.get("workflow")
        result = generated.get("result") or {}
        if isinstance(workflow, dict):
            workflow = _append_playing_assertion(workflow)
            attempt_path = _write_workflow(workflow, f"{WORKFLOW_NAME}.attempt{attempt:02d}.json")
            print(f"Wrote attempt workflow to {attempt_path}")
            signatures.append(_action_signature(workflow))
            if result.get("success"):
                canonical = _write_workflow(workflow, f"{WORKFLOW_NAME}.json")
                print(f"Wrote canonical workflow to {canonical}")
        else:
            signatures.append(None)
        print(json.dumps(_strip_artifacts(generated), indent=2, default=str))

    if args.attempts > 1:
        print("\n=== generation consistency ===")
        for index, sig in enumerate(signatures, 1):
            print(f"  attempt {index}: {' -> '.join(sig) if sig else 'NO WORKFLOW'}")
        distinct = {json.dumps(sig) for sig in signatures if sig}
        print(f"  {len(distinct)} distinct action sequence(s) across {len(signatures)} attempts")


if __name__ == "__main__":
    asyncio.run(main())
