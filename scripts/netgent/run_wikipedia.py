"""Generate and run a Wikipedia scroll workflow from a natural-language spec (LLM).

Requires an LLM API key in the repo-root `.env` (GOOGLE_API_KEY or
ANTHROPIC_API_KEY, matching NETGENT_LLM_PROVIDER). The generated workflow is
saved to scripts/workflow/run_wikipedia_workflow.json so it can later be
replayed without the LLM via scripts/replay_wikipedia_workflow.py.

Usage:
    uv run python scripts/netgent/run_wikipedia.py \
        --url https://en.wikipedia.org/wiki/Internet \
        --pause-seconds 2
"""

import argparse
import asyncio
import json
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

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


def _write_workflow_artifact(generated: dict) -> None:
    workflow = generated.get("workflow")
    if not isinstance(workflow, dict):
        return

    workflow_dir = os.path.join(os.path.dirname(__file__), "..", "workflow")
    os.makedirs(workflow_dir, exist_ok=True)
    workflow_path = os.path.join(workflow_dir, "run_wikipedia_workflow.json")

    with open(workflow_path, "w", encoding="utf-8") as workflow_file:
        json.dump(workflow, workflow_file, indent=2)
        workflow_file.write("\n")

    print(f"Wrote workflow JSON to {workflow_path}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and run a Wikipedia scroll workflow locally."
    )
    parser.add_argument(
        "--url",
        default="https://en.wikipedia.org/wiki/Internet",
        help="Wikipedia article URL to scroll through.",
    )
    parser.add_argument(
        "--pause-seconds",
        default="2",
        help="Pause between scrolls, in seconds.",
    )
    args = parser.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

    specification = """1. Go to <secret>url</secret>.
    2. Wait for the article to finish loading.
    3. Scroll down one page at a time, pausing <secret>pause_seconds</secret> seconds \
between scrolls, five times.
    4. Scroll back to the top of the article."""
    parameters = {
        "url": args.url,
        "pause_seconds": args.pause_seconds,
    }
    client = NetGent(cdp_url=None, headless=False)
    generated = await client.generate(
        specification,
        type="browser",
        parameters=parameters,
    )
    _write_workflow_artifact(generated)
    print(json.dumps(_strip_artifacts(generated), indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
