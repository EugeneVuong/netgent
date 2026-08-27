import logging
import os
import re
from typing import Any, NotRequired

from browser_use import Agent, AgentHistoryList, Browser
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.runtime import Runtime
from playwright.async_api import Playwright
from pydantic import BaseModel, ConfigDict

from agents.model_factory import get_browser_use_model
from agents.subagents.browser.generate.evolution import (
    BrowserEvolution,
    build_evolutionary_prompt,
    coerce_evolution,
    update_evolution,
)
from agents.subagents.browser.generate.generate import gen_workflow
from agents.subagents.browser.util import (
    build_controller,
    open_browser_session,
    parse_agent_history,
    prune_agenthistorylist,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_STEPS = int(os.getenv("BROWSER_USE_MAX_STEPS", "30"))
EXCLUDED_BROWSER_USE_ACTIONS = [
    "close_tab",
    "search_google",
    "extract_structured_data",
    "read_sheet_contents",
    "read_cell_contents",
    "update_cell_contents",
    "clear_cell_contents",
    "select_cell_or_range",
    "fallback_input_into_single_selected_cell",
    "switch_tab",
    "upload_file",
]

BROWSER_USE_HEADLESS = True


class BrowserGenerateState(MessagesState):
    task: str
    history: NotRequired[list[AgentHistoryList]]
    steps: NotRequired[int]
    workflow: NotRequired[dict[str, Any] | None]
    result: NotRequired[dict[str, Any] | None]
    evolution: NotRequired[BrowserEvolution]
    parameters: NotRequired[dict[str, str]]
    # alias -> parameter name, for parameters routed through browser-use's
    # sensitive_data masking (see _prepare_parameters).
    secret_aliases: NotRequired[dict[str, str]]


class BrowserGenerateContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    playwright: Playwright


# Parameter names that hold credentials. Only these are routed through
# browser-use's ``sensitive_data`` (which masks the value everywhere in the
# LLM's messages); everything else is inlined literally into the task and
# mapped back to a ``{{placeholder}}`` after generation.
SECRET_NAME_RE = re.compile(
    r"(password|passwd|secret|token|api_?key|passcode|pin|otp|credential|auth)",
    re.IGNORECASE,
)
_SECRET_TAG_RE = re.compile(r"<secret>\s*(\w+)\s*</secret>")
_PARAM_NAME_RE = re.compile(r"^\w+$")


def _is_secret_parameter(name: str) -> bool:
    return SECRET_NAME_RE.search(name) is not None


def _alias_for(index: int) -> str:
    """Opaque, letters-only alias (``NGSECRETA``, ``NGSECRETB``, ...).

    browser-use masks every sensitive *value* wherever it appears in a
    message, including inside other placeholders' names — with
    ``{"google_query": "youtube", "youtube_query": ...}`` the tag
    ``<secret>youtube_query</secret>`` was rewritten to
    ``<secret><secret>google_query</secret>_query</secret>`` and the LLM typed
    that literally. Upper-case letter-only aliases cannot contain a
    lower-case word or a number, so values can never collide with them.
    """
    letters = ""
    index += 1
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return f"NGSECRET{letters}"


def validate_parameters(parameters: dict[str, str]) -> None:
    """Reject parameter sets the placeholder machinery can't represent."""
    for name, value in parameters.items():
        if not _PARAM_NAME_RE.match(name):
            raise ValueError(
                f"parameter name {name!r} must match [A-Za-z0-9_]+ (used as {{{{{name}}}}})"
            )
        if not isinstance(value, str):
            raise ValueError(f"parameter {name!r} must be a string, got {type(value).__name__}")
        if not value.strip():
            raise ValueError(f"parameter {name!r} is empty")
    for name, value in parameters.items():
        if _is_secret_parameter(name) and len(value) < 4:
            logger.warning(
                "secret parameter %r is only %d chars; browser-use masks every "
                "occurrence of the value in page text, which can corrupt the "
                "agent's view of the page",
                name,
                len(value),
            )


def _prepare_parameters(
    task: str, parameters: dict[str, str]
) -> tuple[str, dict[str, str] | None, dict[str, str]]:
    """Return (task_for_agent, sensitive_data, secret_aliases).

    * Plain parameters: ``<secret>name</secret>`` in the task is replaced by
      the literal value and the value is listed for the agent. After
      generation the literal is mapped back to ``{{name}}`` by value.
    * Secret parameters: passed as browser-use ``sensitive_data`` under an
      opaque alias; the task refers to ``<secret>ALIAS</secret>``.
    """
    validate_parameters(parameters)
    if not parameters:
        return task, None, {}

    secret_aliases: dict[str, str] = {}
    sensitive_data: dict[str, str] = {}
    plain: dict[str, str] = {}
    for name, value in parameters.items():
        if _is_secret_parameter(name):
            alias = _alias_for(len(secret_aliases))
            secret_aliases[alias] = name
            sensitive_data[alias] = value
        else:
            plain[name] = value

    def _rewrite_tag(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in plain:
            return plain[name]
        for alias, param_name in secret_aliases.items():
            if param_name == name:
                return f"<secret>{alias}</secret>"
        return match.group(0)

    task_for_agent = _SECRET_TAG_RE.sub(_rewrite_tag, task)

    lines = [task_for_agent, ""]
    if plain:
        lines.append("Runtime parameter values (type them exactly as written):")
        for name, value in plain.items():
            lines.append(f"  - {name} = {value}")
    if secret_aliases:
        lines.append("Secret placeholders (write the tag verbatim; it is substituted for you):")
        for alias, name in secret_aliases.items():
            lines.append(
                f"  - {name}: write <secret>{alias}</secret> wherever this value is needed"
            )
    return "\n".join(lines), (sensitive_data or None), secret_aliases


def _restore_secret_aliases(workflow: dict[str, Any], secret_aliases: dict[str, str]) -> None:
    """Rewrite ``<secret>ALIAS</secret>`` back to ``<secret>name</secret>`` in place."""
    if not secret_aliases:
        return

    def _restore(match: re.Match[str]) -> str:
        name = secret_aliases.get(match.group(1))
        return f"<secret>{name}</secret>" if name else match.group(0)

    for state in workflow.get("states") or []:
        for action in state.get("actions") or []:
            params = action.get("params")
            if not isinstance(params, dict):
                continue
            for key, value in list(params.items()):
                if isinstance(value, str) and "<secret>" in value:
                    params[key] = _SECRET_TAG_RE.sub(_restore, value)


async def execute_task(
    state: BrowserGenerateState, runtime: Runtime[BrowserGenerateContext]
) -> dict[str, Any]:
    playwright = runtime.context.playwright
    parameters = state.get("parameters") or {}
    task, sensitive_data, secret_aliases = _prepare_parameters(state["task"], parameters)
    evolution = coerce_evolution(task, state.get("evolution"))
    history_list: list[AgentHistoryList] = []
    steps = max(1, state.get("steps", 1) or 1)
    for _ in range(steps):
        evolutionary_prompt = build_evolutionary_prompt(task, evolution)
        print("evolutionary_prompt", evolutionary_prompt)
        browser, browser_context, _ = await open_browser_session(playwright)

        try:
            # We don't give it the ability to Change Pages.
            # It can only stay only on one page at a time.
            browser_agent = Agent(
                browser=Browser(
                    browser=browser,
                    browser_context=browser_context,
                    playwright=playwright,
                ),
                controller=build_controller(EXCLUDED_BROWSER_USE_ACTIONS),
                llm=get_browser_use_model(),
                task=evolutionary_prompt,
                sensitive_data=sensitive_data,
                headless=BROWSER_USE_HEADLESS,
            )
            history = await browser_agent.run(max_steps=DEFAULT_MAX_STEPS)
            evolution = update_evolution(task, history, evolution)
            history_list.append(history)
        finally:
            await browser.close()
    return {"history": history_list, "evolution": evolution, "secret_aliases": secret_aliases}


async def generate_workflow(state: BrowserGenerateState):
    # top_k = min(max(1, state.get("steps", 3) or 3), 3)
    pruned_history = prune_agenthistorylist(state.get("history", []), top_k=1)
    if not pruned_history or len(pruned_history) == 0:
        return {
            "result": {
                "success": False,
                "message": "Agent could not execute prompted task",
            }
        }
    parsed_history = parse_agent_history(pruned_history[0].model_dump())
    parameter_names = list((state.get("parameters") or {}).keys())
    workflow = gen_workflow(
        parsed_history,
        specification=state["task"],
        parameters=parameter_names,
    )
    _restore_secret_aliases(workflow, state.get("secret_aliases") or {})
    print(workflow)
    return {
        "workflow": workflow,
        "result": {
            "success": True,
            "message": "Workflow Generated!",
        },
    }


def create_agent():
    graph = StateGraph(
        state_schema=BrowserGenerateState,
        context_schema=BrowserGenerateContext,
    )
    graph.add_node("execute_task", execute_task)
    graph.add_node("generate_workflow", generate_workflow)
    graph.add_edge(START, "execute_task")
    graph.add_edge("execute_task", "generate_workflow")
    graph.add_edge("generate_workflow", END)
    return graph.compile()
