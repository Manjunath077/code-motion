import litellm  # type: ignore[import]
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Suppress LiteLLM's verbose internal logging
litellm.suppress_debug_info = True

_SYSTEM_PROMPT = """
You are an expert Manim animation engineer specializing in educational computer science visualizations.
Your job is to produce visually rich, clear, and engaging Manim Community Edition (v0.18+) Python scripts
that teach algorithms and data structures through animation.

━━━ ANIMATION QUALITY STANDARDS ━━━
Every script you write MUST:
1. Start with a bold title (Text, font_size=42, color=WHITE) centered at the top.
2. Show a "step label" (Text, font_size=28, color=YELLOW) that updates to describe each operation.
3. Use colored shapes — NOT just text — to represent data elements.
4. Color-code operations: GREEN for insertions/push, RED for deletions/pop, YELLOW for current/active, BLUE for neutral.
5. Apply visual feedback on key moments: Flash, Indicate, or Circumscribe around modified elements.
6. Call self.wait(0.6) between major steps so viewers can follow along.
7. Keep total animation length between 20–35 seconds.
8. End with a brief "Done!" or summary text fading in.

━━━ ALLOWED MANIM CONSTRUCTS ━━━
You may freely use ANY Manim Community Edition construct, including:

Shapes:        Rectangle, RoundedRectangle, Square, Circle, Triangle,
               Line, Arrow, DoubleArrow, DashedLine, Polygon, Brace, BraceBetweenPoints
Text:          Text, Tex, MathTex, MarkupText  (use font_size= to control size)
Create anims:  Create, Write, FadeIn, FadeOut, GrowFromCenter, GrowFromEdge,
               DrawBorderThenFill, AddTextLetterByLetter
Motion anims:  MoveToTarget, Transform, ReplacementTransform, ApplyMethod,
               Rotate, ScaleInPlace, Wiggle
Sequencing:    AnimationGroup, LaggedStart, LaggedStartMap, Succession
Effect anims:  Indicate, Flash, Circumscribe, ShowPassingFlash, FocusOn,
               SurroundingRectangle, Underline
Grouping:      VGroup, HGroup, Group — use .arrange(), .next_to(), .move_to(), .shift()
Positioning:   UP, DOWN, LEFT, RIGHT, ORIGIN, UL, UR, DL, DR, and numpy vectors
Colors:        BLUE, GREEN, RED, YELLOW, ORANGE, PURPLE, WHITE, GRAY, TEAL,
               GOLD, MAROON, PINK, LIGHT_GRAY, DARK_BLUE, DARK_GREEN
Properties:    .set_color(), .set_fill(color, opacity), .set_stroke(color, width)
               .set_opacity(), .scale(), .rotate()

━━━ STRUCTURE REQUIREMENTS ━━━
- Exactly ONE class inheriting from Scene.
- Class MUST have a `construct(self)` method.
- Helper methods defined ON THE CLASS are allowed and encouraged (e.g., def _push_block(self, ...)).
- Use `from manim import *` as the only import.
- DO NOT import os, sys, subprocess, requests, or any non-manim module.

━━━ VISUAL DESIGN PATTERNS ━━━

Stack visualization:
  - Draw each element as a Rectangle (width=2, height=0.7) with Text centered inside.
  - Stack grows UPWARD from a fixed base line drawn with Line.
  - Maintain a "TOP →" Arrow or label that repositions after each push/pop.
  - PUSH: GrowFromEdge(block, DOWN) + Flash(block, color=GREEN).
  - POP: Flash(block, color=RED) then FadeOut(block, shift=RIGHT).

Queue visualization:
  - Elements are Rectangles arranged horizontally.
  - ENQUEUE on the right: GrowFromEdge(block, LEFT).
  - DEQUEUE from the left: Flash + FadeOut(shift=LEFT).
  - Show FRONT and REAR labels with Arrows.

Sorting (bars):
  - Elements are vertical Rectangles of height proportional to their value.
  - Comparing pair: set color YELLOW + Indicate.
  - Swap: use MoveToTarget with saved target positions.
  - Sorted portion: set color GREEN progressively.

Linked list:
  - Nodes: RoundedRectangle with Text value + small Rectangle for "next" pointer.
  - Arrows between nodes.
  - Insertion: new node GrowFromCenter, then arrow redrawn.

Tree / Graph:
  - Nodes: Circle with Text label inside.
  - Edges: Line or Arrow between node centers.
  - BFS/DFS: visited=GREEN, current=YELLOW, unvisited=BLUE.

━━━ OUTPUT FORMAT ━━━
Return ONLY valid Python code. No markdown fences, no explanations. Start directly with `from manim import *`.
"""


def _enrich_prompt(user_prompt: str) -> str:
    return (
        f"Create a detailed, visually engaging Manim educational animation for:\n\n"
        f"{user_prompt}\n\n"
        "Follow all quality standards from your instructions:\n"
        "- Title + step labels\n"
        "- Colored shapes for every data element\n"
        "- GREEN for additions, RED for removals, YELLOW for active element\n"
        "- Flash or Indicate effect on every state change\n"
        "- self.wait(0.6) between steps\n"
        "- 20–35 second total duration\n"
        "- Finish with a 'Done!' message"
    )


async def generate_manim_script(user_prompt: str) -> str:
    kwargs = dict(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _enrich_prompt(user_prompt)},
        ],
        api_key=settings.LLM_API_KEY,
        temperature=settings.LLM_TEMPERATURE,
        timeout=settings.LLM_TIMEOUT,
    )
    if settings.LLM_BASE_URL:
        kwargs["base_url"] = settings.LLM_BASE_URL

    logger.info("Calling LLM model: %s", settings.LLM_MODEL)
    response = await litellm.acompletion(**kwargs)
    content = response.choices[0].message.content
    return _clean_script(content)


async def fix_manim_script(broken_script: str, error: str) -> str:
    """Send the broken script + validation error back to the LLM and ask it to fix it."""
    fix_prompt = (
        f"The Manim script below failed validation with this error:\n\n"
        f"ERROR: {error}\n\n"
        f"BROKEN SCRIPT:\n{broken_script}\n\n"
        "Fix ONLY the error above. Do not change the animation structure or logic. "
        "Return ONLY the corrected Python code with no markdown fences or explanations."
    )
    kwargs = dict(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": fix_prompt},
        ],
        api_key=settings.LLM_API_KEY,
        temperature=0.1,
        timeout=settings.LLM_TIMEOUT,
    )
    if settings.LLM_BASE_URL:
        kwargs["base_url"] = settings.LLM_BASE_URL

    logger.info("Attempting script repair — error: %s", error[:120])
    response = await litellm.acompletion(**kwargs)
    content = response.choices[0].message.content
    return _clean_script(content)


def _clean_script(content: str) -> str:
    """Strip markdown code fences that the LLM sometimes wraps around output."""
    content = content.strip()

    if "```" in content:
        lines = content.split("\n")
        # Drop opening fence line (e.g. ```python or ```)
        if lines[0].startswith("```"):
            lines = lines[1:]
        # Drop closing fence line
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines)
    elif content.startswith("`") and content.endswith("`"):
        content = content[1:-1]

    # Drop stray "python" prefix left by some fence variants
    if content.startswith("python"):
        content = content[len("python"):]

    return content.strip()
