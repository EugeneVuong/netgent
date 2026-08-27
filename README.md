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

### How parameters reach the LLM agent

`generate()` splits `parameters` in two (see
`agents/subagents/browser/generate/agent.py::_prepare_parameters`):

- **Secret-named parameters** (`password`, `token`, `api_key`, `passcode`,
  `pin`, `otp`, …) go through browser-use's `sensitive_data`, which masks the
  value in every LLM message. They are passed under opaque aliases
  (`NGSECRETA`, …) because browser-use masks the value *everywhere* — with
  `{"google_query": "youtube", "youtube_query": …}` the tag
  `<secret>youtube_query</secret>` was rewritten to
  `<secret><secret>google_query</secret>_query</secret>` and typed literally.
- **Everything else** is inlined into the task as its literal value and
  mapped back to `{{name}}` after generation, by exact value, by numeric
  value, or embedded inside a longer string (values shorter than 4 chars are
  never matched inside other text, so `"20"` can't corrupt `"2024"`).

Parameter names must match `[A-Za-z0-9_]+` and values must be non-empty
strings; `validate_parameters` rejects anything else up front.

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

## Example: Google → YouTube search-and-play

`scripts/workflow/run_google_youtube_search_workflow.json` opens Google,
searches for `youtube`, clicks the YouTube result, searches YouTube for a
query, clicks the first video, and keeps it playing. It exercises the full
action set: `go_to_url` → `input_text` → `send_keys` → `click_element` → `wait`.

Google Search serves its "unusual traffic" reCAPTCHA page to Playwright's
bundled Chromium and to **every** headless mode, so this workflow needs the
system Google Chrome in headful mode — set `BROWSER_CHANNEL=chrome` in `.env`
(or pass `browser_channel="chrome"` to `NetGent`). Two more things trip it:

- a spoofed User-Agent whose version disagrees with Chrome's Client Hints
  (`open_browser_session` therefore leaves the UA alone when a real channel
  is used), and
- **rate**: roughly three automated searches from one IP inside ~5 minutes.
  The replay and generator scripts default to a 300 s cooldown between runs;
  a failed run whose error URL contains `google.com/sorry/` is this check, not
  a broken selector.

```bash
# Replay 3× in fresh browsers and print a consistency summary. Each run writes
# per-action screenshots, run.log, and result.json under
# debug_artifacts/google_youtube_search/<run-id>/.
uv run python scripts/replay_google_youtube_search_workflow.py \
    --youtube-query "big buck bunny" --watch-seconds 20 --runs 3

# Regenerate from the natural-language spec (needs an API key). --attempts N
# generates N times and reports how many distinct action sequences came out.
uv run python scripts/netgent/run_google_youtube_search.py --attempts 3
```

## Authoring workflows in YAML

Workflows can be written in YAML instead of JSON — same schema, friendlier to
hand-edit and comment. `scripts/workflow/youtube_search_play_workflow.yaml` is
a complete example (YouTube search → click first video → play). Run any
`.yaml`/`.json` workflow with the generic runner, passing its declared
parameters as `--param name=value`:

```bash
uv run python scripts/replay_yaml_workflow.py \
    scripts/workflow/youtube_search_play_workflow.yaml \
    --param query="big buck bunny" --param watch_seconds=20 --runs 2
```

Per-action screenshots, `run.log`, and `result.json` land under
`debug_artifacts/<workflow-name>/<run-id>/`.

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
- **Real Chrome** — set `BROWSER_CHANNEL=chrome` (or pass `browser_channel=`)
  to launch the installed Google Chrome instead of the bundled Chromium. The
  engine replay path and the LLM generation path share the same stealth launch
  configuration (`open_browser_session`), so generated workflows replay in an
  identically-fingerprinted browser.
- **Tests** — `uv run pytest`.
