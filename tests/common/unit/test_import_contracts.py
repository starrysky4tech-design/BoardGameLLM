"""import-linter の契約(pyproject.toml)が、違反を実際に検出することを確かめる。

本物のソースではなく、同じパッケージ構成の合成ツリーに違反を書いて、契約を当てる。
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"

PACKAGES = [
    "core",
    "application",
    "infrastructure",
    "toolkit",
    "cli",
    "plugins",
    "plugins/kahuna",
    "plugins/kahuna/logic",
    "plugins/kahuna/vision",
]

RUN = (
    "import sys; from importlinter.cli import lint_imports_command; "
    f"sys.argv = ['lint-imports', '--config', r'{PYPROJECT}']; lint_imports_command()"
)


def build_tree(root: Path, extra: dict[str, str]) -> None:
    (root / "bglm").mkdir()
    (root / "bglm" / "__init__.py").write_text("", encoding="utf-8")
    for package in PACKAGES:
        directory = root / "bglm" / package
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_text("", encoding="utf-8")
    for relative, text in extra.items():
        (root / "bglm" / relative).write_text(text, encoding="utf-8")


def lint(root: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(root), "PYTHONUTF8": "1"}
    return subprocess.run(
        [sys.executable, "-c", RUN],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


ALLOWED = {
    "application/ok.py": "import bglm.core\n",
    "infrastructure/ok.py": "import bglm.core\n",
    "toolkit/ok.py": "import bglm.core\n",
    "plugins/kahuna/logic/ok.py": "import bglm.core\n",
    "plugins/kahuna/vision/ok.py": (
        "import cv2\nimport bglm.core\nimport bglm.toolkit\nimport bglm.plugins.kahuna.logic\n"
    ),
    "cli/ok.py": (
        "import bglm.application\nimport bglm.infrastructure\nimport bglm.plugins.kahuna\n"
    ),
}

VIOLATIONS = [
    ("core/bad.py", "import bglm.application\n"),
    ("core/bad.py", "import bglm.plugins.kahuna\n"),
    ("application/bad.py", "import bglm.plugins.kahuna\n"),
    ("application/bad.py", "import bglm.infrastructure\n"),
    ("infrastructure/bad.py", "import bglm.application\n"),
    ("toolkit/bad.py", "import bglm.infrastructure\n"),
    ("plugins/kahuna/vision/bad.py", "import bglm.application\n"),
    ("plugins/kahuna/logic/bad.py", "import bglm.plugins.kahuna.vision\n"),
    ("plugins/kahuna/logic/bad.py", "import bglm.toolkit\n"),
    ("plugins/kahuna/logic/bad.py", "import cv2\n"),
    ("plugins/kahuna/logic/bad.py", "import bglm.infrastructure\n"),
]


def test_allowed_imports_are_kept(tmp_path: Path) -> None:
    build_tree(tmp_path, ALLOWED)

    result = lint(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("path", "statement"), VIOLATIONS)
def test_violation_is_detected(tmp_path: Path, path: str, statement: str) -> None:
    build_tree(tmp_path, {**ALLOWED, path: statement})

    result = lint(tmp_path)

    assert result.returncode != 0, f"{path}: {statement.strip()} が検出されなかった"
    assert "BROKEN" in result.stdout
