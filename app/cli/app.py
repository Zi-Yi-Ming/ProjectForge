from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer

from app.agents.persistence import JsonExecutionPersistence
from app.product.errors import (
    ActiveRunExistsError,
    CommandNotAllowedError,
    InvalidProjectStateError,
    InvalidStateTransitionError,
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
    PersistenceError,
)
from app.product.event_store import EventStore
from app.product.lifecycle import ProjectLifecycle
from app.product.project_persistence import ProjectPersistence
from app.product.replan_control import ReplanControl
from app.product.run_control import RunControl
from app.product.service import ProjectService
from app.schemas.project import ProjectStatus
from app.schemas.task import Task, TaskGraph, TaskStatus


def _default_base_dir() -> Path:
    return Path(".runtime/projects")


def _build_service(base_dir: Path | None = None) -> ProjectService:
    persistence = ProjectPersistence(base_dir=base_dir or _default_base_dir())
    event_store = EventStore(base_dir=base_dir or _default_base_dir())
    execution_persistence = JsonExecutionPersistence(base_dir=base_dir or _default_base_dir())
    run_control = RunControl(persistence=persistence, execution_persistence=execution_persistence, event_store=event_store)
    replan_control = ReplanControl(persistence=persistence, run_control=run_control, event_store=event_store, execution_persistence=execution_persistence)
    return ProjectService(persistence=persistence, event_store=event_store, run_control=run_control, replan_control=replan_control)


app = typer.Typer(add_completion=False, no_args_is_help=True, help="ProjectForge 项目管理 CLI")


@app.command()
def create(name: str, base_dir: Path | None = typer.Option(None, "--base-dir")) -> None:
    service = _build_service(base_dir)
    try:
        project = service.create(name)
    except ProjectAlreadyExistsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Project created")
    typer.echo(f"ID: {project.project_id}")
    typer.echo(f"Name: {project.name}")
    typer.echo(f"Status: {project.status.value}")
    typer.echo(f"Stage: {project.current_stage}")


@app.command()
def show(project_id: str, base_dir: Path | None = typer.Option(None, "--base-dir")) -> None:
    service = _build_service(base_dir)
    try:
        project = service.load(project_id)
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Project ID: {project.project_id}")
    typer.echo(f"Name: {project.name}")
    typer.echo(f"Status: {project.status.value}")
    typer.echo(f"Current Stage: {project.current_stage}")
    typer.echo(f"Created At: {project.created_at}")
    typer.echo(f"Updated At: {project.updated_at}")
    typer.echo(f"JD Profile Ref: {project.jd_profile_ref}")
    typer.echo(f"Blueprint Ref: {project.blueprint_ref}")
    typer.echo(f"Task Graph Ref: {project.task_graph_ref}")
    typer.echo(f"Last Run ID: {project.last_run_id}")


@app.command()
def transition(
    project_id: str,
    target_status: str,
    base_dir: Path | None = typer.Option(None, "--base-dir"),
) -> None:
    service = _build_service(base_dir)
    try:
        target = ProjectStatus(target_status.upper())
    except ValueError as exc:
        typer.echo(f"Error: invalid target status: {target_status}", err=True)
        raise typer.Exit(code=1) from exc
    try:
        project = service.transition_to(project_id, target)
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except InvalidStateTransitionError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except InvalidProjectStateError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ActiveRunExistsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except CommandNotAllowedError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Project transitioned")
    typer.echo(f"ID: {project.project_id}")
    typer.echo(f"Status: {project.status.value}")
    typer.echo(f"Stage: {project.current_stage}")


@app.command()
def events(project_id: str, base_dir: Path | None = typer.Option(None, "--base-dir")) -> None:
    service = _build_service(base_dir)
    try:
        all_events = service.event_store.get_events(project_id)
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for event in all_events:
        actor = event.actor.value if hasattr(event.actor, "value") else str(event.actor)
        typer.echo(f"- {event.timestamp} | {event.event_type} | {actor} | {event.event_id}")
        if event.payload:
            typer.echo(f"  payload: {event.payload}")


replan_app = typer.Typer(add_completion=False, no_args_is_help=True, help="管理项目重新规划")
app.add_typer(replan_app, name="replan", help="管理项目重新规划")


def _dummy_task_graph() -> TaskGraph:
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g1", why="w1", dependencies=[], status=TaskStatus.DONE, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
        Task(id="T2", phase_id="P1", title="T2", goal="g2", why="w2", dependencies=["T1"], status=TaskStatus.FAILED, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
    ]
    return TaskGraph(project="demo", tasks=tasks, total_tasks=2, required_tasks=2, optional_tasks=0)


@replan_app.command("create")
def replan_create(project_id: str, run_id: str, base_dir: Path | None = typer.Option(None, "--base-dir")) -> None:
    service = _build_service(base_dir)
    try:
        proposal = service.replan_control.create_proposal(project_id, run_id, _dummy_task_graph())
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except InvalidProjectStateError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Proposal created")
    typer.echo(f"Proposal ID: {proposal.proposal_id}")
    typer.echo(f"Run ID: {proposal.run_id}")
    typer.echo(f"Status: {proposal.status.value}")


@replan_app.command("show")
def replan_show(project_id: str, proposal_id: str, base_dir: Path | None = typer.Option(None, "--base-dir")) -> None:
    service = _build_service(base_dir)
    try:
        project = service.load(project_id)
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    try:
        proposals = service.replan_control.list_proposals(project.last_run_id or "")
        proposal = next(p for p in proposals if p.proposal_id == proposal_id)
    except StopIteration:
        typer.echo(f"Error: Proposal {proposal_id} not found", err=True)
        raise typer.Exit(code=1) from None
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Proposal ID: {proposal.proposal_id}")
    typer.echo(f"Run ID: {proposal.run_id}")
    typer.echo(f"Status: {proposal.status.value}")


@replan_app.command("approve")
def replan_approve(project_id: str, proposal_id: str, base_dir: Path | None = typer.Option(None, "--base-dir")) -> None:
    service = _build_service(base_dir)
    try:
        project = service.load(project_id)
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    try:
        proposal = service.replan_control.approve_proposal(project_id, project.last_run_id or "", proposal_id)
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except InvalidProjectStateError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Proposal approved")
    typer.echo(f"Proposal ID: {proposal.proposal_id}")
    typer.echo(f"Status: {proposal.status.value}")


@replan_app.command("reject")
def replan_reject(project_id: str, proposal_id: str, base_dir: Path | None = typer.Option(None, "--base-dir")) -> None:
    service = _build_service(base_dir)
    try:
        project = service.load(project_id)
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    try:
        proposal = service.replan_control.reject_proposal(project_id, project.last_run_id or "", proposal_id)
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except InvalidProjectStateError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Proposal rejected")
    typer.echo(f"Proposal ID: {proposal.proposal_id}")
    typer.echo(f"Status: {proposal.status.value}")


@replan_app.command("apply")
def replan_apply(project_id: str, proposal_id: str, base_dir: Path | None = typer.Option(None, "--base-dir")) -> None:
    service = _build_service(base_dir)
    try:
        project = service.load(project_id)
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    try:
        proposal = service.replan_control.apply_proposal(project_id, proposal_id, _dummy_task_graph(), run_id=project.last_run_id or "")
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except InvalidProjectStateError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Proposal applied")
    typer.echo(f"Proposal ID: {proposal.proposal_id}")
    typer.echo(f"Status: {proposal.status.value}")


run_app = typer.Typer(add_completion=False, no_args_is_help=True, help="管理项目执行运行")
app.add_typer(run_app, name="run", help="管理项目执行运行")


@run_app.command("start")
def run_start(project_id: str, base_dir: Path | None = typer.Option(None, "--base-dir")) -> None:
    service = _build_service(base_dir)
    try:
        result = service.execute_run(project_id, run_dir=base_dir or _default_base_dir())
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ActiveRunExistsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except InvalidProjectStateError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Run completed")
    typer.echo(f"Project ID: {result.project_id}")
    typer.echo(f"Status: {result.status.value}")
    if result.last_run_id:
        typer.echo(f"Last Run ID: {result.last_run_id}")


@run_app.command("show")
def run_show(project_id: str, run_id: str, base_dir: Path | None = typer.Option(None, "--base-dir")) -> None:
    service = _build_service(base_dir)
    try:
        run = service.run_control.get_run(run_id)
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Run ID: {run.run_id}")
    typer.echo(f"Project ID: {run.project}")
    typer.echo(f"Status: {run.status.value}")


@run_app.command("cancel")
def run_cancel(project_id: str, run_id: str, base_dir: Path | None = typer.Option(None, "--base-dir")) -> None:
    service = _build_service(base_dir)
    try:
        run = service.run_control.cancel_run(project_id, run_id)
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Cancellation requested for run {run_id}")
    typer.echo(f"Project ID: {run.project}")
    typer.echo(f"Status: {run.status.value}")
    if run.blocking_reason:
        typer.echo(f"Blocking Reason: {run.blocking_reason}")


@run_app.command("resume")
def run_resume(project_id: str, base_dir: Path | None = typer.Option(None, "--base-dir")) -> None:
    service = _build_service(base_dir)
    try:
        run = service.replan_control.resume_project(project_id, _dummy_task_graph(), base_dir or _default_base_dir())
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except InvalidProjectStateError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Run resumed")
    typer.echo(f"Run ID: {run.run_id}")
    typer.echo(f"Project ID: {project_id}")
    typer.echo(f"Status: {run.status.value}")


if __name__ == "__main__":
    app()
