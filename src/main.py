"""NetGent client.

Two entry points:

* :meth:`NetGent.run_workflow` — deterministic engine replay of a
  pre-built workflow. ``type="shell"`` runs subprocess actions;
  ``type="browser"`` runs Playwright actions.

* :meth:`NetGent.generate` — drives the LLM subagent matching ``type``
  to turn a natural-language spec into a workflow and execute it.

Routing is inlined (no LangGraph wrapper).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, Literal

from engine.controller import ProgramController
from engine.executor import StateExecutor
from engine.runner import WorkflowRunner
from registry.actions.network import NETWORK_ACTIONS
from registry.triggers.base import always_true

WorkflowType = Literal["shell", "browser"]


def _with_session_timeout(ws_url: str) -> str:
    """Add browserless' per-session ``timeout`` (ms) to a WS endpoint.

    Browserless closes the browser when the session timeout expires; its
    default of 30 s silently truncates any longer experiment. Override with
    ``NETGENT_BROWSER_TIMEOUT_MS``. An explicit ``timeout`` already present in
    the URL is left alone.
    """
    import urllib.parse

    try:
        timeout_ms = int(os.getenv("NETGENT_BROWSER_TIMEOUT_MS", "900000"))
    except (TypeError, ValueError):
        timeout_ms = 900_000

    parsed = urllib.parse.urlparse(ws_url)
    query = urllib.parse.parse_qs(parsed.query)
    if "timeout" in query:
        return ws_url
    query["timeout"] = [str(timeout_ms)]
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))


class NetGent:
    def __init__(
        self,
        *,
        cdp_url: str | None = None,
        headless: bool = True,
    ) -> None:
        self._cdp_url = cdp_url
        self._headless = headless

    # ── deterministic replay ─────────────────────────────────────────
    def run_workflow(
        self,
        workflow: dict[str, Any],
        *,
        parameters: dict[str, str] | None = None,
        type: WorkflowType = "shell",
        action_period: float | None = None,
    ) -> dict[str, Any]:
        return asyncio.run(
            self.arun_workflow(
                workflow,
                parameters=parameters,
                type=type,
                action_period=action_period,
            )
        )

    async def arun_workflow(
        self,
        workflow: dict[str, Any],
        *,
        parameters: dict[str, str] | None = None,
        type: WorkflowType = "shell",
        action_period: float | None = None,
    ) -> dict[str, Any]:
        if type == "shell":
            runner = self._shell_runner(parameters=parameters, action_period=action_period)
            try:
                output = await runner.run(workflow)
            except Exception as exc:
                return {"result": {"success": False, "error": str(exc)}}
            return {"result": {"success": True, "output": output}}

        if type == "browser":
            async with self._playwright_page() as page:
                runner = self._browser_runner(
                    page=page,
                    parameters=parameters,
                    action_period=action_period,
                )
                try:
                    output = await runner.run(workflow)
                except Exception as exc:
                    return {"result": {"success": False, "error": str(exc)}}
                return {"result": {"success": True, "output": output}}

        raise ValueError(f"unsupported workflow type: {type!r}")

    # ── LLM generate ─────────────────────────────────────────────────
    async def generate(
        self,
        spec: str,
        *,
        type: WorkflowType = "browser",
        parameters: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Drive the appropriate LLM subagent to produce + run a workflow."""
        params = dict(parameters or {})

        if type == "browser":
            from agents.subagents.browser.agent import (
                create_agent as create_browser_agent,
            )

            agent = create_browser_agent()
            return await agent.ainvoke(
                {
                    "task": spec,
                    "messages": [],
                    "workflow": None,
                    "parameters": params,
                },
            )

        if type == "shell":
            from agents.subagents.shell.agent import (
                create_agent as create_shell_agent,
            )

            agent = create_shell_agent()
            runner = self._shell_runner(parameters=params)
            return await agent.ainvoke(
                {
                    "task": spec,
                    "messages": [],
                    "workflow": None,
                    "parameters": params,
                },
                context={"runner": runner},
            )

        raise ValueError(f"unsupported workflow type: {type!r}")

    # ── runner builders (shell + browser) ────────────────────────────
    @staticmethod
    def _shell_runner(
        *,
        parameters: dict[str, str] | None = None,
        action_period: float | None = None,
    ) -> WorkflowRunner:
        executor_config: dict[str, Any] | None = (
            None if action_period is None else {"action_period": action_period}
        )
        return WorkflowRunner(
            controller=ProgramController(triggers=(always_true,)),
            executor=StateExecutor(
                actions=NETWORK_ACTIONS,
                parameters=parameters,
                config=executor_config,
            ),
            config={},
        )

    @staticmethod
    def _browser_runner(
        *,
        page: Any,
        parameters: dict[str, str] | None = None,
        action_period: float | None = None,
    ) -> WorkflowRunner:
        # Imported lazily so the shell path doesn't pull in Playwright
        # transitively.
        from registry.actions.playwright import PLAYWRIGHT_ACTIONS

        executor_config: dict[str, Any] | None = (
            None if action_period is None else {"action_period": action_period}
        )
        return WorkflowRunner(
            controller=ProgramController(
                triggers=(always_true,),
                context={"page": page},
            ),
            executor=StateExecutor(
                actions=PLAYWRIGHT_ACTIONS,
                context={"page": page},
                parameters=parameters,
                config=executor_config,
            ),
            config={},
        )

    # ── playwright lifecycle (browser engine path only) ──────────────
    @asynccontextmanager
    async def _playwright_page(self):
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        try:
            if self._cdp_url:
                # Remote mode uses the Playwright WS protocol (e.g. browserless
                # at /chromium/playwright). The legacy field name `cdp_url` is
                # historical — `connect_over_cdp` is the wrong call here.
                #
                # Browserless enforces a per-session TIMEOUT (30 s by default)
                # and tears down the page/context/browser when it expires, so
                # any experiment longer than that silently loses its page
                # mid-run ("Target page, context or browser has been closed").
                # A 60 s VoD run, let alone Prudentia's 600 s, needs this
                # raised; browserless reads it from the WS query string.
                browser = await playwright.chromium.connect(_with_session_timeout(self._cdp_url))
                context = browser.contexts[0] if browser.contexts else (await browser.new_context())
            else:
                browser = await playwright.chromium.launch(
                    headless=self._headless,
                    args=[
                        "--use-fake-ui-for-media-stream",
                        "--use-fake-device-for-media-stream",
                        # Docker gives /dev/shm 64 MB by default, which a
                        # sustained video workload can exhaust. Only relevant
                        # for this local-launch branch -- the browserless path
                        # below runs Chrome in its own container.
                        "--disable-dev-shm-usage",
                    ],
                )
                context = await browser.new_context()

            await context.grant_permissions(["camera", "microphone"])

            page = await context.new_page()
            # Adaptive-bitrate video players size their quality ladder off the
            # viewport. Browserless' default context is 1280x720, which pins
            # YouTube/Vimeo to ~720p (~2.4 Mbps) no matter how much bandwidth
            # is available -- silently making any bottleneck experiment
            # application-limited. Prudentia (SIGCOMM '24) hit this and drove
            # real 4K monitors for exactly this reason. Set per-page so we
            # don't disturb browserless' shared default context.
            vw = int(os.getenv("NETGENT_VIEWPORT_WIDTH", "1280"))
            vh = int(os.getenv("NETGENT_VIEWPORT_HEIGHT", "720"))
            if (vw, vh) != (1280, 720):
                await page.set_viewport_size({"width": vw, "height": vh})
            try:
                yield page
            finally:
                # Pages/contexts can be closed mid-workflow by the remote
                # site (Zoom tears down the join tab once the meeting client
                # mounts). Swallow teardown errors so a successful workflow
                # run isn't masked by a TargetClosedError.
                try:
                    await context.close()
                except Exception:
                    pass
                try:
                    await browser.close()
                except Exception:
                    pass
        finally:
            await playwright.stop()


__all__ = ["NetGent", "WorkflowType"]
