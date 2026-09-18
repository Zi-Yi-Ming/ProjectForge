from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_cli_entrypoint_does_not_require_fastapi() -> None:
    # fastapi moved to the optional [api] extra; importing the CLI entry (the
    # projectforge command) must not pull it in, in a clean interpreter.
    code = (
        "import sys; import app.cli.app;"
        " assert not any(m == 'fastapi' or m.startswith('app.api')"
        " for m in sys.modules), 'core/CLI unexpectedly imports fastapi/app.api'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_api_subpackage_imports_fastapi_only_via_extra() -> None:
    # Sanity: the API surface is where fastapi is used, and importing it works
    # (fastapi is installed in the dev env); proves the split is the reason the
    # core test above passes, not that app.api is simply broken.
    code = "import app.api.app; import fastapi; print('ok')"
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
