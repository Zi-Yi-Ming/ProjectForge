from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from app.cli.app import app

runner = CliRunner()

SAMPLE_JD = """岗位：Java 后端开发工程师

任职要求：
1. 熟练掌握 Java、Spring Boot、MyBatis
2. 熟悉 MySQL、Redis
3. 了解 Docker
"""


def _jd_file(tmp_path: Path) -> Path:
    path = tmp_path / "java-backend.md"
    path.write_text(SAMPLE_JD, encoding="utf-8")
    return path


def test_cli_plan_rule_end_to_end(tmp_path: Path) -> None:
    jd_path = _jd_file(tmp_path)
    base = tmp_path / "base"
    result = runner.invoke(app, ["plan", "new", str(jd_path), "--planner", "rule", "--base-dir", str(base)])
    assert result.exit_code == 0, result.output + result.stderr
    assert "Status: PLANNING" in result.output
    pid = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("Project ID: ")][0]
    result = runner.invoke(app, ["plan", "approve", pid, "--base-dir", str(base)])
    assert result.exit_code == 0, result.output + result.stderr
    assert "Status: READY" in result.output


def test_cli_plan_writes_task_graph_json(tmp_path: Path) -> None:
    jd_path = _jd_file(tmp_path)
    base = tmp_path / "base"
    json_out = tmp_path / "graph.json"
    result = runner.invoke(
        app,
        ["plan", "new", str(jd_path), "--planner", "rule", "--base-dir", str(base), "--json-out", str(json_out)],
    )
    assert result.exit_code == 0, result.output + result.stderr
    assert "Status: PLANNING" in result.output
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert data["total_tasks"] > 0
    assert data["graph_validation"]["valid"] is True
    pid = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("Project ID: ")][0]
    result = runner.invoke(app, ["plan", "approve", pid, "--base-dir", str(base)])
    assert result.exit_code == 0, result.output + result.stderr
    assert "Status: READY" in result.output


def test_cli_plan_llm_without_key_degrades_to_rule(tmp_path: Path) -> None:
    jd_path = _jd_file(tmp_path)
    base = tmp_path / "base"
    result = runner.invoke(
        app,
        ["plan", "new", str(jd_path), "--planner", "llm", "--base-dir", str(base)],
        env={k: "" for k in ("PROJECTFORGE_LLM_BASE_URL", "PROJECTFORGE_LLM_API_KEY", "PROJECTFORGE_LLM_MODEL")},
    )
    assert result.exit_code == 0, result.output + result.stderr
    assert "Status: PLANNING" in result.output
    pid = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("Project ID: ")][0]
    result = runner.invoke(app, ["plan", "approve", pid, "--base-dir", str(base)])
    assert result.exit_code == 0, result.output + result.stderr
    assert "Status: READY" in result.output


def test_cli_plan_rejects_unknown_planner(tmp_path: Path) -> None:
    jd_path = _jd_file(tmp_path)
    result = runner.invoke(app, ["plan", "new", str(jd_path), "--planner", "magic"])
    assert result.exit_code != 0


def test_cli_plan_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["plan", "new", str(tmp_path / "nope.md"), "--planner", "rule"])
    assert result.exit_code == 1
    assert "Error" in result.output + result.stderr
