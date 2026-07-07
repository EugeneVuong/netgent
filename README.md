# NetGent

NetGent turns application behaviors (browser sessions, network measurements) into
reproducible **workflows**. A workflow is a JSON program of states and actions that
the engine replays deterministically — no LLM needed at replay time. Workflows can
be written by hand or **generated once** from a natural-language specification by an
LLM agent, then saved and replayed forever.

Two entry points on the `NetGent` client (`src/main.py`):

| Method | What it does | Needs an API key? |
|---|---|---|
| `run_workflow(workflow, parameters, type)` | Deterministic replay of a pre-built workflow JSON | No |
| `generate(spec, type, parameters)` | LLM agent turns a natural-language spec into a workflow, runs it, and returns the workflow JSON | Yes (Gemini or Anthropic) |

`type` is `"browser"` (Playwright actions) or `"shell"` (network actions:
`ping`, `iperf`, `ndt`, `wget`).

## Setup

Requires Python 3.11–3.12 and [uv](https://docs.astral.sh/uv/).

```bash
# 1. Install dependencies
uv sync

# 2. Install the Chromium browser used by Playwright
uv run playwright install chromium

# 3. Create your env file
cp .env.example .env
```

### API keys

API keys are only needed for **workflow generation** (the `generate()` path).
Replaying a saved workflow JSON works without any key.

Edit `.env` and set one of:

```bash
# Default provider is Gemini — get a key at https://aistudio.google.com/apikey
GOOGLE_API_KEY=your-key-here

# Or use Anthropic — get a key at https://console.anthropic.com/
# NETGENT_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key-here
```

`NETGENT_LLM_PROVIDER` selects the provider (`gemini` by default, model
`gemini-3.1-flash-lite`). The env file is discovered automatically by
`src/core/config.py` (priority: `.env.{environment}.local` → `.env.{environment}`
→ `.env.local` → `.env`). See `.env.example` for all available settings
(headless mode, log level, Browserless endpoint, etc.).

## Workflow anatomy

A workflow JSON has a `specification` (human-readable description), a list of
`states`, and a list of `parameters`:

```json
{
  "specification": "Go to a website and wait",
  "states": [
    {
      "checks": [{ "type": "always_true", "params": {} }],
      "actions": [
        { "type": "go_to_url", "params": { "url": "{{url}}", "new_tab": false } },
        { "type": "wait", "params": { "seconds": "{{wait_seconds}}" } }
      ],
      "end_state": "Workflow Completed"
    }
  ],
  "parameters": ["url", "wait_seconds"]
}
```

- **checks** — triggers that gate when a state runs (`always_true` runs unconditionally).
- **actions** — executed in order by the `StateExecutor`.
- **`{{name}}` placeholders** — substituted at run time from the `parameters`
  dict you pass to `run_workflow()`. Both full-value (`"{{url}}"`) and embedded
  (`"https://en.wikipedia.org/wiki/{{article}}"`) placeholders work.

### Available browser actions

Registered in `src/registry/actions/playwright.py`:

| Action | Key params |
|---|---|
| `go_to_url` | `url`, `new_tab` |
| `go_back` | — |
| `wait` | `seconds` |
| `click_element` | `selector` |
| `input_text` | `selector`, `text` |
| `scroll` | `down` (bool), `num_pages` (float), optional `selector` |
| `scroll_to_text` | `text` |
| `send_keys` | `keys` |
| `select_dropdown_option` | `selector`, `option` |

## Example: scrolling Wikipedia

The repo ships a complete example. There are two ways to build any new
application workflow — the Wikipedia one demonstrates both.

### Option A — write the workflow JSON by hand (no API key)

`scripts/workflow/run_wikipedia_workflow.json` opens an article, scrolls down
one viewport at a time (pausing between scrolls), then scrolls back to the top.
The core of it is just:

```json
{ "type": "go_to_url", "params": { "url": "{{url}}", "new_tab": false } },
{ "type": "scroll",    "params": { "down": true, "num_pages": 1 } },
{ "type": "wait",      "params": { "seconds": "{{pause_seconds}}" } }
```

Replay it (headful by default; add `--headless` to hide the browser):

```bash
uv run python scripts/replay_wikipedia_workflow.py \
    --url https://en.wikipedia.org/wiki/Internet \
    --pause-seconds 2
```

### Option B — generate it from natural language (needs an API key)

`scripts/netgent/run_wikipedia.py` sends a plain-English spec to the browser
subagent, which drives a real browser, produces the workflow JSON, runs it, and
saves the artifact to `scripts/workflow/run_wikipedia_workflow.json`:

```bash
uv run python scripts/netgent/run_wikipedia.py \
    --url https://en.wikipedia.org/wiki/Internet \
    --pause-seconds 2
```

The spec inside the script is just numbered prose; runtime values are marked
with `<secret>name</secret>` so the agent parameterizes them instead of
hardcoding them:

```
1. Go to <secret>url</secret>.
2. Wait for the article to finish loading.
3. Scroll down one page at a time, pausing <secret>pause_seconds</secret> seconds between scrolls, five times.
4. Scroll back to the top of the article.
```

Once generated, replay it forever with Option A — no more LLM calls.

## Building your own application workflow

1. **Pick the target flow** and write it as numbered steps. Mark every runtime
   value (URLs, credentials, durations) as `<secret>name</secret>`.
2. **Generate**: copy `scripts/netgent/run_wikipedia.py`, swap in your spec and
   CLI args, and run it. The generated workflow JSON is saved under
   `scripts/workflow/`. (Or skip the LLM and hand-write the JSON using the
   action table above — see `scripts/workflow/*.json` for real examples like
   Google Meet, Zoom, Twitch, and Puffer.)
3. **Replay**: copy `scripts/replay_wikipedia_workflow.py`, point it at your
   workflow JSON, and pass the parameters. Iterate on the JSON directly (fix
   selectors, add waits) until the replay is stable.
4. **Commit both** the generator script and the workflow JSON so others can
   replay without an API key.

### Programmatic use

```python
import json
from main import NetGent  # with src/ on sys.path

client = NetGent(cdp_url=None, headless=True)
workflow = json.load(open("scripts/workflow/run_wikipedia_workflow.json"))
result = client.run_workflow(
    workflow,
    parameters={"url": "https://en.wikipedia.org/wiki/Internet", "pause_seconds": "2"},
    type="browser",
)
```

## Notes

- **Headless vs headful** — `NetGent(headless=False)` shows the browser window;
  replay scripts default to headful and accept `--headless`.
- **macOS** — set `USE_LOCAL=true` (the default) so shell actions run in the
  local process; Linux network-namespace mode (`ip netns exec`) is Linux-only.
- **Remote browser** — set `BROWSERLESS_WS_ENDPOINT` in `.env` (or pass
  `cdp_url=` to `NetGent`) to drive a remote Browserless Chromium instead of a
  local one.
- **Tests** — `uv run pytest`.
