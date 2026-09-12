"""LangGraph pipeline for turning a prompt into a validated Manim script.

Phase 0 has exactly one node, wrapping the generate -> AST-validate -> repair
loop that used to live directly in scene_service.py. The point of putting it
in a graph now, even with a single node, is so later phases (scriptwriter,
storyboard, per-scene codegen, critic) only ever add nodes/edges here instead
of reshaping the calling code in scene_service.py.
"""
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from app.core.logging import get_logger
from app.repository.scene_repository import update_scene_status
from app.schemas.scene_schema import SceneStatus
from app.services.llm_service import fix_manim_script, generate_manim_script
from app.utils.script_validator import validate_manim_script

logger = get_logger(__name__)

_MAX_REPAIR_ATTEMPTS = 2


class GraphState(TypedDict):
    scene_id: str
    prompt: str
    script: Optional[str]
    validation_error: Optional[str]
    attempt: int
    is_valid: bool


async def _generate_scene_code(state: GraphState) -> GraphState:
    await update_scene_status(state["scene_id"], SceneStatus.VALIDATING)

    script = state["script"]
    if script is None:
        script = await generate_manim_script(state["prompt"])
    else:
        script = await fix_manim_script(script, state["validation_error"] or "")

    result = validate_manim_script(script)
    return {
        **state,
        "script": script,
        "is_valid": result.is_valid,
        "validation_error": None if result.is_valid else result.error,
        "attempt": state["attempt"] + 1,
    }


def _route_after_generate(state: GraphState) -> str:
    if state["is_valid"]:
        return "done"
    if state["attempt"] > _MAX_REPAIR_ATTEMPTS:
        return "failed"
    return "retry"


_builder = StateGraph(GraphState)
_builder.add_node("generate_scene_code", _generate_scene_code)
_builder.set_entry_point("generate_scene_code")
_builder.add_conditional_edges(
    "generate_scene_code",
    _route_after_generate,
    {"retry": "generate_scene_code", "done": END, "failed": END},
)

video_graph = _builder.compile()


async def run_scene_codegen(scene_id: str, prompt: str) -> GraphState:
    initial: GraphState = {
        "scene_id": scene_id,
        "prompt": prompt,
        "script": None,
        "validation_error": None,
        "attempt": 0,
        "is_valid": False,
    }
    return await video_graph.ainvoke(initial)
