import pytest
from app.utils.script_validator import validate_manim_script, MAX_SCRIPT_LENGTH, MAX_NESTING_DEPTH

VALID_SCRIPT = """
from manim import *

class BubbleSortScene(Scene):
    def construct(self):
        text = Text("Bubble Sort")
        self.play(Write(text))
        self.wait(1)
"""


def test_valid_script_passes():
    result = validate_manim_script(VALID_SCRIPT)
    assert result.is_valid
    assert result.error == ""


def test_banned_import_os_fails():
    script = """
from manim import *
import os

class MyScene(Scene):
    def construct(self):
        self.wait(1)
"""
    result = validate_manim_script(script)
    assert not result.is_valid
    assert "os" in result.error


def test_banned_import_subprocess_fails():
    script = """
from manim import *
import subprocess

class MyScene(Scene):
    def construct(self):
        self.wait(1)
"""
    result = validate_manim_script(script)
    assert not result.is_valid
    assert "subprocess" in result.error


def test_unauthorized_import_fails():
    script = """
from manim import *
import numpy

class MyScene(Scene):
    def construct(self):
        self.wait(1)
"""
    result = validate_manim_script(script)
    assert not result.is_valid
    assert "numpy" in result.error


def test_no_scene_class_fails():
    script = """
from manim import *

class NotAScene:
    def construct(self):
        self.wait(1)
"""
    result = validate_manim_script(script)
    assert not result.is_valid
    assert "Scene" in result.error


def test_multiple_scene_classes_fails():
    script = """
from manim import *

class SceneOne(Scene):
    def construct(self):
        self.wait(1)

class SceneTwo(Scene):
    def construct(self):
        self.wait(1)
"""
    result = validate_manim_script(script)
    assert not result.is_valid
    assert "one" in result.error.lower() or "multiple" in result.error.lower()


def test_missing_construct_method_fails():
    script = """
from manim import *

class MyScene(Scene):
    def setup(self):
        self.wait(1)
"""
    result = validate_manim_script(script)
    assert not result.is_valid
    assert "construct" in result.error


def test_eval_call_fails():
    script = """
from manim import *

class MyScene(Scene):
    def construct(self):
        eval("malicious code")
        self.wait(1)
"""
    result = validate_manim_script(script)
    assert not result.is_valid
    assert "eval" in result.error


def test_exec_call_fails():
    script = """
from manim import *

class MyScene(Scene):
    def construct(self):
        exec("import os; os.system('rm -rf /')")
        self.wait(1)
"""
    result = validate_manim_script(script)
    assert not result.is_valid
    assert "exec" in result.error


def test_open_call_fails():
    script = """
from manim import *

class MyScene(Scene):
    def construct(self):
        f = open("/etc/passwd")
        self.wait(1)
"""
    result = validate_manim_script(script)
    assert not result.is_valid
    assert "open" in result.error


def test_malformed_python_fails():
    script = "this is not valid python !!!"
    result = validate_manim_script(script)
    assert not result.is_valid
    assert "Syntax error" in result.error


def test_from_banned_module_fails():
    script = """
from manim import *
from pathlib import Path

class MyScene(Scene):
    def construct(self):
        self.wait(1)
"""
    result = validate_manim_script(script)
    assert not result.is_valid
    assert "pathlib" in result.error


# — Phase 7 hardening —

def test_script_too_long_fails():
    padding = "# " + "x" * MAX_SCRIPT_LENGTH
    script = f"""
from manim import *

{padding}

class MyScene(Scene):
    def construct(self):
        self.wait(1)
"""
    result = validate_manim_script(script)
    assert not result.is_valid
    assert "length" in result.error.lower()


def test_script_at_max_length_passes():
    # A valid script well within the limit should still pass
    result = validate_manim_script("""
from manim import *

class MyScene(Scene):
    def construct(self):
        self.wait(1)
""")
    assert result.is_valid


def test_nesting_depth_exceeded_fails():
    # 4 levels of nesting inside construct — exceeds MAX_NESTING_DEPTH (3)
    script = """
from manim import *

class MyScene(Scene):
    def construct(self):
        def level2():
            def level3():
                def level4():
                    pass
"""
    result = validate_manim_script(script)
    assert not result.is_valid
    assert "nesting" in result.error.lower() or "depth" in result.error.lower()


def test_nesting_depth_at_limit_passes():
    # exactly MAX_NESTING_DEPTH (3) levels — should pass
    script = """
from manim import *

class MyScene(Scene):
    def construct(self):
        def level2():
            def level3():
                pass
        self.wait(1)
"""
    result = validate_manim_script(script)
    assert result.is_valid
