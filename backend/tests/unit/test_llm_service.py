from unittest.mock import AsyncMock, patch
from app.services.llm_service import _clean_script, fix_manim_script, generate_manim_script

# ── _clean_script unit tests (no network) ────────────────────────────────────

def test_plain_code_unchanged():
    code = "from manim import *\n\nclass S(Scene):\n    def construct(self): pass"
    assert _clean_script(code) == code


def test_triple_backtick_with_python_tag_stripped():
    code = "from manim import *\n\nclass S(Scene):\n    def construct(self): pass"
    fenced = f"```python\n{code}\n```"
    result = _clean_script(fenced)
    assert "`" not in result
    assert result == code


def test_triple_backtick_without_tag_stripped():
    code = "from manim import *\n\nclass S(Scene):\n    def construct(self): pass"
    fenced = f"```\n{code}\n```"
    result = _clean_script(fenced)
    assert "`" not in result
    assert result == code


def test_single_backtick_span_stripped():
    code = "from manim import *"
    result = _clean_script(f"`{code}`")
    assert result == code


def test_stray_python_prefix_stripped():
    result = _clean_script("python\nfrom manim import *")
    assert not result.startswith("python")
    assert result.startswith("from manim")


def test_whitespace_stripped():
    result = _clean_script("  \nfrom manim import *\n  ")
    assert result == "from manim import *"


# ── generate_manim_script (mocked model router) ──────────────────────────────

async def test_generate_returns_cleaned_script():
    code = "from manim import *\n\nclass S(Scene):\n    def construct(self): pass"

    with patch(
        "app.services.llm_service.call_text", new_callable=AsyncMock, return_value=f"```python\n{code}\n```"
    ):
        result = await generate_manim_script("animate something")

    assert "`" not in result
    assert result == code


async def test_generate_plain_response_returned_as_is():
    code = "from manim import *\n\nclass S(Scene):\n    def construct(self): pass"

    with patch("app.services.llm_service.call_text", new_callable=AsyncMock, return_value=code):
        result = await generate_manim_script("animate something")

    assert result == code


async def test_generate_routes_through_codegen_stage():
    """generate_manim_script must route through the 'codegen' model-router stage
    so it picks up the model assigned to that stage (see app/core/model_router.py)."""
    code = "from manim import *\nclass S(Scene):\n    def construct(self): pass"

    with patch("app.services.llm_service.call_text", new_callable=AsyncMock, return_value=code) as mock_call:
        await generate_manim_script("test")

    assert mock_call.call_args.args[0] == "codegen"


async def test_fix_routes_through_code_fix_stage():
    code = "from manim import *\nclass S(Scene):\n    def construct(self): pass"

    with patch("app.services.llm_service.call_text", new_callable=AsyncMock, return_value=code) as mock_call:
        await fix_manim_script("broken", "SyntaxError", scene_id="abc")

    assert mock_call.call_args.args[0] == "code_fix"
    assert mock_call.call_args.kwargs["scene_id"] == "abc"
