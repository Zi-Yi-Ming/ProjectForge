"""End-to-end ProjectForge demo, fully offline.

Runs the whole product chain without Hermes, bubblewrap or network access
by selecting the mock executor: project lifecycle -> task graph ->
constrained run (with an injected task failure) -> human-approved replan ->
resume to completion.

    python scripts/demo.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.mock_executor import MockExecutor  # noqa: E402
from app.agents.orchestrator import ExecutionOrchestrator
from app.agents.persistence import JsonExecutionPersistence
from app.product.project_artifact_store import ProjectArtifactStore
from app.product.project_persistence import ProjectPersistence
from app.product.replan_control import ReplanControl
from app.product.run_control import RunControl
from app.product.service import ProjectService
from app.product.workflow import ProjectWorkflow
from app.schemas.execution import ExecutionStatus
from app.schemas.project import ProjectStatus
from app.schemas.replan import ReplanProposalStatus
from app.schemas.task import Task, TaskGraph, TaskStatus


def _orchestrator(run_dir: Path, fail_t2: bool) -> ExecutionOrchestrator:
    outcomes = {"T2": [ExecutionStatus.FAILED]} if fail_t2 else None
    return ExecutionOrchestrator(adapter=MockExecutor(workspace=run_dir, outcomes=outcomes))


def main() -> None:
    base = Path(tempfile.mkdtemp(prefix="projectforge-demo-"))
    print(f"runtime root: {base}")

    persistence = ProjectPersistence(base_dir=base / "projects")
    execution_persistence = JsonExecutionPersistence(base_dir=base)
    run_control = RunControl(persistence=persistence, execution_persistence=execution_persistence)
    replan_control = ReplanControl(
        persistence=persistence,
        run_control=run_control,
        execution_persistence=execution_persistence,
    )
    service = ProjectService(
        persistence=persistence,
        run_control=run_control,
        replan_control=replan_control,
        base_dir=base,
    )

    print("\n[1/5] project lifecycle: CREATED -> ANALYZING -> PLANNING -> READY")
    project = service.create("demo-spring-petclinic")
    for status in (ProjectStatus.ANALYZING, ProjectStatus.PLANNING, ProjectStatus.READY):
        service.transition_to(project.project_id, status)
        print(f"  -> {status.value}")

    print("\n[2/5] persist task graph (2 tasks, T2 depends on T1)")
    graph = TaskGraph(
        project=project.project_id,
        tasks=[
            Task(id="T1", phase_id="P1", title="Scaffold project", goal="Create project skeleton",
                 why="foundation", dependencies=[], status=TaskStatus.PENDING, scope="Core",
                 acceptance_criteria=["skeleton compiles"], out_of_scope=[], interview_points=[],
                 test_paths=["tests"]),
            Task(id="T2", phase_id="P1", title="Add REST endpoint", goal="Add GET /pets",
                 why="core feature", dependencies=["T1"], status=TaskStatus.PENDING, scope="Core",
                 acceptance_criteria=["endpoint returns 200"], out_of_scope=[], interview_points=[],
                 test_paths=["tests"]),
        ],
        total_tasks=2,
        required_tasks=2,
        optional_tasks=0,
    )
    workflow = ProjectWorkflow(base_dir=base)
    project = persistence.load_project(project.project_id)
    project.task_graph_ref = workflow.persist_task_graph(project.project_id, graph)
    persistence.save_project(project)

    print("\n[3/5] constrained run #1: T1 succeeds, T2 injected to FAIL")
    run_dir = base / "workspaces" / project.project_id
    run = service.start_run(project.project_id, graph, run_dir, _orchestrator(run_dir, fail_t2=True))
    run = run_control.complete_run(project.project_id, run.run_id, run.status)
    print(f"  run {run.run_id} -> {run.status.value}")

    print("\n[4/5] replan: create -> approve -> apply (human approval gate)")
    proposal = service.replan_control.create_proposal(project.project_id, run.run_id, graph)
    print(f"  proposal {proposal.proposal_id} -> {proposal.status.value} ({proposal.action.value})")
    proposal = service.replan_control.approve_proposal(project.project_id, run.run_id, proposal.proposal_id)
    print(f"  approved -> {proposal.status.value}")
    proposal = service.replan_control.apply_proposal(project.project_id, proposal.proposal_id, graph, run_id=run.run_id)
    print(f"  applied -> {proposal.status.value} (T2 reset to PENDING)")

    project = persistence.load_project(project.project_id)
    project.status = ProjectStatus.BLOCKED
    persistence.save_project(project)

    print("\n[5/5] resume: T1 stays DONE, T2 retried and validated -> COMPLETED")
    resumed = service.replan_control.resume_project(
        project.project_id, graph, run_dir, _orchestrator(run_dir, fail_t2=False)
    )
    resumed_run = run_control.get_run(resumed.run_id)
    print(f"  run {resumed.run_id} -> {resumed_run.status.value}")
    assert resumed_run.status == ExecutionStatus.COMPLETED

    print("\nDEMO COMPLETE: every artifact under", base)


if __name__ == "__main__":
    main()
