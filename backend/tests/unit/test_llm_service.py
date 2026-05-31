from unittest.mock import AsyncMock, MagicMock, patch
from app.services.llm_service import _clean_script, generate_manim_script

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


# ── generate_manim_script (mocked litellm) ───────────────────────────────────

async def test_generate_returns_cleaned_script():
    code = "from manim import *\n\nclass S(Scene):\n    def construct(self): pass"
    mock_response = MagicMock()
    mock_response.choices[0].message.content = f"```python\n{code}\n```"

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        result = await generate_manim_script("animate something")

    assert "`" not in result
    assert result == code


async def test_generate_plain_response_returned_as_is():
    code = "from manim import *\n\nclass S(Scene):\n    def construct(self): pass"
    mock_response = MagicMock()
    mock_response.choices[0].message.content = code

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        result = await generate_manim_script("animate something")

    assert result == code


async def test_generate_passes_model_from_settings():
    """LiteLLM acompletion must be called with the configured model name."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "from manim import *\nclass S(Scene):\n    def construct(self): pass"

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response) as mock_call:
        await generate_manim_script("test")

    call_kwargs = mock_call.call_args.kwargs
    assert "model" in call_kwargs
    assert "api_key" in call_kwargs
