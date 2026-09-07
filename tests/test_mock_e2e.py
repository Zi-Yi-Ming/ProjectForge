from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from app.agents.mock_executor import MockExecutor
from app.agents.orchestrator import ExecutionOrchestrator
from app.agents.persistence import JsonExecutionPersistence
from app.cli.app import app
from app.product.event_store import EventStore
from app.product.project_artifact_store import ProjectArtifactStore
from app.product.project_persistence import ProjectPersistence
from app.product.replan_control import ReplanControl
from app.product.run_control import RunControl
from app.product.service import ProjectService
from app.schemas.execution import ExecutionStatus
from app.schemas.project import ProjectStatus
from app.schemas.replan import ReplanProposalStatus
from app.schemas.task import Task, TaskGraph, TaskStatus

runner = CliRunner()


def _graph() -> TaskGraph:
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g1", why="w1", dependencies=[], status=TaskStatus.PENDING, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
        Task(id="T2", phase_id="P1", title="T2", goal="g2", why="w2", dependencies=["T1"], status=TaskStatus.PENDING, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
    ]
    return TaskGraph(project="demo", tasks=tasks, total_tasks=2, required_tasks=2, optional_tasks=0)


def _mock_orchestrator(run_dir: Path, outcomes: dict[str, list[ExecutionStatus]] | None = None) -> ExecutionOrchestrator:
    run_dir.mkdir(parents=True, exist_ok=True)
    return ExecutionOrchestrator(adapter=MockExecutor(workspace=run_dir, outcomes=outcomes))


def _service(tmp_path: Path) -> ProjectService:
    persistence = ProjectPersistence(base_dir=tmp_path)
    execution_persistence = JsonExecutionPersistence(base_dir=tmp_path)
    run_control = RunControl(persistence=persistence, execution_persistence=execution_persistence)
    replan_control = ReplanControl(persistence=persistence, run_control=run_control, execution_persistence=execution_persistence)
    return ProjectService(persistence=persistence, run_control=run_control, replan_control=replan_control)


def _ready_project(service: ProjectService) -> str:
    project = service.create("mock-e2e")
    for status in (ProjectStatus.ANALYZING, ProjectStatus.PLANNING, ProjectStatus.READY):
        service.transition_to(project.project_id, status)
    return project.project_id


def test_mock_executor_completes_run(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project_id = _ready_project(service)
    run_dir = tmp_path / "ws"
    run = service.start_run(project_id, _graph(), run_dir, _mock_orchestrator(run_dir))
    assert run.status == ExecutionStatus.COMPLETED
    assert (run_dir / "t1_impl.txt").exists()
    assert (run_dir / "t2_impl.txt").exists()


def test_mock_failure_replan_cycle(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project_id = _ready_project(service)
    run_dir = tmp_path / "ws"

    first = _mock_orchestrator(run_dir, outcomes={"T2": [ExecutionStatus.FAILED]})
    run = service.start_run(project_id, _graph(), run_dir, first)
    assert run.status in {ExecutionStatus.FAILED, ExecutionStatus.BLOCKED}
    run = service.run_control.complete_run(project_id, run.run_id, run.status)
    assert run.status in {ExecutionStatus.FAILED, ExecutionStatus.BLOCKED}

    proposal = service.replan_control.create_proposal(project_id, run.run_id, _graph())
    assert proposal.status == ReplanProposalStatus.PROPOSED
    approved = service.replan_control.approve_proposal(project_id, run.run_id, proposal.proposal_id)
    assert approved.status == ReplanProposalStatus.APPROVED
    graph = _graph()
    applied = service.replan_control.apply_proposal(project_id, proposal.proposal_id, graph, run_id=run.run_id)
    assert applied.status == ReplanProposalStatus.APPLIED
    assert next(t for t in graph.tasks if t.id == "T2").status == TaskStatus.PENDING

    project = service.persistence.load_project(project_id)
    project.status = ProjectStatus.BLOCKED
    service.persistence.save_project(project)

    resumed = service.replan_control.resume_project(project_id, graph, run_dir, _mock_orchestrator(run_dir))
    assert resumed.run_id != run.run_id


def test_cli_run_start_with_mock_executor(tmp_path: Path) -> None:
    result = runner.invoke(app, ["create", "Mock CLI"] + ["--base-dir", str(tmp_path)])
    assert result.exit_code == 0
    project_id = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("ID: ")][0]
    for status in (ProjectStatus.ANALYZING, ProjectStatus.PLANNING, ProjectStatus.READY):
        result = runner.invoke(app, ["transition", project_id, status.value, "--base-dir", str(tmp_path)])
        assert result.exit_code == 0

    graph = TaskGraph(
        project=project_id,
        tasks=[Task(id="T1", phase_id="P1", title="hello", goal="Create hello.txt", status=TaskStatus.PENDING)],
        total_tasks=1,
        required_tasks=1,
        optional_tasks=0,
    )
    workflow_store = ProjectArtifactStore(base_dir=Path.cwd() / ".runtime" / "projects")
    workflow_store.save(project_id, "task_graph", graph)
    persistence = ProjectPersistence(base_dir=tmp_path)
    project = persistence.load_project(project_id)
    project.task_graph_ref = workflow_store.save(project_id, "task_graph", graph)
    persistence.save_project(project)

    result = runner.invoke(app, ["run", "start", project_id, "--base-dir", str(tmp_path), "--executor", "mock"])
    assert result.exit_code == 0, result.output + result.stderr
    assert "Run completed" in result.output
    assert "Status: COMPLETED" in result.output


def test_cli_rejects_unknown_executor(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "start", "proj-x", "--base-dir", str(tmp_path), "--executor", "bogus"])
    assert result.exit_code != 0
