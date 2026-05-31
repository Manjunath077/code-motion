import ast
from dataclasses import dataclass, field

BANNED_MODULES = {
    "os", "sys", "subprocess", "socket", "requests",
    "urllib", "shutil", "pathlib", "importlib", "builtins",
}
BANNED_BUILTINS = {"eval", "exec", "open", "__import__", "compile"}

MAX_SCRIPT_LENGTH = 25_000
MAX_NESTING_DEPTH = 5


@dataclass
class ValidationResult:
    is_valid: bool
    error: str = field(default="")


def validate_manim_script(script: str) -> ValidationResult:
    # 1. Script length guard
    if len(script) > MAX_SCRIPT_LENGTH:
        return ValidationResult(
            is_valid=False,
            error=f"Script exceeds maximum length of {MAX_SCRIPT_LENGTH} characters",
        )

    # 2. Must be valid Python
    try:
        tree = ast.parse(script)
    except SyntaxError as e:
        return ValidationResult(is_valid=False, error=f"Syntax error: {e}")

    # 3. Walk all nodes — check imports and banned calls
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in BANNED_MODULES:
                    return ValidationResult(is_valid=False, error=f"Banned import '{alias.name}'")
                if top != "manim":
                    return ValidationResult(
                        is_valid=False,
                        error=f"Unauthorized import '{alias.name}' — only 'from manim import *' is allowed",
                    )

        if isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in BANNED_MODULES:
                return ValidationResult(is_valid=False, error=f"Banned import from '{node.module}'")
            if top != "manim":
                return ValidationResult(
                    is_valid=False,
                    error=f"Unauthorized import from '{node.module}' — only 'from manim import *' is allowed",
                )

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BANNED_BUILTINS:
                return ValidationResult(is_valid=False, error=f"Banned call '{func.id}()'")

    # 4. Exactly one class inheriting from Scene
    scene_classes = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and _inherits_from_scene(node)
    ]

    if len(scene_classes) == 0:
        return ValidationResult(is_valid=False, error="Script must contain exactly one class inheriting from Scene")
    if len(scene_classes) > 1:
        return ValidationResult(
            is_valid=False,
            error=f"Script must contain exactly one Scene class, found {len(scene_classes)}",
        )

    # 5. construct() method must exist directly on the Scene class
    scene_cls = scene_classes[0]
    has_construct = any(
        isinstance(node, ast.FunctionDef) and node.name == "construct"
        for node in scene_cls.body
    )
    if not has_construct:
        return ValidationResult(is_valid=False, error="Scene class must define a 'construct' method")

    # 6. Function nesting depth must not exceed MAX_NESTING_DEPTH
    depth = _max_fn_nesting_depth(tree)
    if depth > MAX_NESTING_DEPTH:
        return ValidationResult(
            is_valid=False,
            error=f"Function nesting depth {depth} exceeds maximum of {MAX_NESTING_DEPTH}",
        )

    return ValidationResult(is_valid=True)


def _inherits_from_scene(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "Scene":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "Scene":
            return True
    return False


def _max_fn_nesting_depth(node: ast.AST, current: int = 0) -> int:
    if isinstance(node, ast.FunctionDef):
        current += 1
    max_depth = current
    for child in ast.iter_child_nodes(node):
        max_depth = max(max_depth, _max_fn_nesting_depth(child, current))
    return max_depth
