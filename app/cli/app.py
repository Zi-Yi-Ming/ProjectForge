from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer

from app.agents.persistence import JsonExecutionPersistence
from app.agents.replan_persistence import ReplanPersistence
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
from app.product.service import ProjectService, executor_factory_from_name, planner_factory_from_name
from app.product.workflow import ProjectWorkflow
from app.schemas.project import ProjectStatus


def _default_base_dir() -> Path:
    return Path(".runtime")


def _build_service(base_dir: Path | None = None, executor: str = "hermes", task_timeout: int | None = None) -> ProjectService:
    base = base_dir or _default_base_dir()
    projects_root = base / "projects"
    persistence = ProjectPersistence(base_dir=projects_root)
    event_store = EventStore(base_dir=projects_root)
    execution_persistence = JsonExecutionPersistence(base_dir=base)
    run_control = RunControl(persistence=persistence, execution_persistence=execution_persistence, event_store=event_store)
    replan_control = ReplanControl(persistence=persistence, run_control=run_control, event_store=event_store, execution_persistence=execution_persistence, replan_persistence=ReplanPersistence(base_dir=base))
    return ProjectService(persistence=persistence, event_store=event_store, run_control=run_control, replan_control=replan_control, executor_factory=_executor_factory(executor), base_dir=base, task_timeout=task_timeout)


def _executor_factory(executor: str):
    try:
        return executor_factory_from_name(executor)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _planner_factory(planner: str):
    try:
        return planner_factory_from_name(planner)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


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


plan_app = typer.Typer(add_completion=False, no_args_is_help=True, help="从 JD 规划项目并审批")
app.add_typer(plan_app, name="plan", help="从 JD 规划项目并审批")


@plan_app.command("new")
def plan_new(
    jd_file: Path,
    planner_name: str = typer.Option("rule", "--planner", help="Planner backend: rule (offline) or llm (OpenAI-compatible API)."),
    base_dir: Path | None = typer.Option(None, "--base-dir"),
    json_out: Path | None = typer.Option(None, "--json-out", help="Write the task graph JSON to this file."),
) -> None:
    """Plan a project from a JD text file: JD -> PLANNING (awaiting approval)."""
    try:
        planner = _planner_factory(planner_name)
    except typer.BadParameter as exc:
        if planner_name != "llm":
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=2) from exc
        # The LLM planner degrades to the rule-based one instead of failing.
        typer.echo(f"Warning: {exc} Falling back to --planner rule.", err=True)
        planner = _planner_factory("rule")

    try:
        jd_text = Path(jd_file).read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"Error: cannot read JD file: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    service = _build_service(base_dir)
    project = service.create(Path(jd_file).stem)
    try:
        result_project = service.plan_to_planning(project.project_id, jd_text, planner=planner)
    except (InvalidProjectStateError, PersistenceError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    task_graph = ProjectWorkflow(base_dir=base_dir or _default_base_dir()).load_task_graph(project.project_id)
    typer.echo(f"Plan generated (awaiting approval)")
    typer.echo(f"Project ID: {result_project.project_id}")
    typer.echo(f"Status: {result_project.status.value}")
    typer.echo(f"Tasks: {task_graph.total_tasks} (required {task_graph.required_tasks}, optional {task_graph.optional_tasks})")
    for task in task_graph.tasks:
        typer.echo(f"  {task.id} | {task.scope} | {task.title} | {task.goal} | criteria x{len(task.acceptance_criteria)}")

    if json_out is not None:
        Path(json_out).write_text(task_graph.model_dump_json(indent=2), encoding="utf-8")
        typer.echo(f"Task graph written to {json_out}")

    typer.echo("下一步: projectforge plan approve <project_id> --base-dir <同 plan new>")


@plan_app.command("approve")
def plan_approve(
    project_id: str,
    base_dir: Path | None = typer.Option(None, "--base-dir"),
) -> None:
    """Approve a PLANNING project: unlock execution (PLANNING -> READY)."""
    service = _build_service(base_dir)
    try:
        result = service.approve_plan(project_id)
    except (ProjectNotFoundError, InvalidProjectStateError, PersistenceError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Plan approved")
    typer.echo(f"Project ID: {result.project_id}")
    typer.echo(f"Status: {result.status.value}")


@app.command()
def interview(
    project_id: str,
    base_dir: Path | None = typer.Option(None, "--base-dir"),
    out: Path | None = typer.Option(None, "--out", help="输出文件路径（默认 <base-dir>/projects/<pid>/interview_prep.md）"),
    no_llm: bool = typer.Option(False, "--no-llm", help="跳过 LLM 润色，直接模板渲染"),
) -> None:
    """Generate the pre-interview cram document for a project."""
    service = _build_service(base_dir)
    try:
        path = service.interview_prep(project_id, use_llm=not no_llm, out_path=out)
    except (ProjectNotFoundError, InvalidProjectStateError, PersistenceError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(path)
    typer.echo(Path(path).read_text(encoding="utf-8"))


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


@replan_app.command("create")
def replan_create(project_id: str, run_id: str, base_dir: Path | None = typer.Option(None, "--base-dir")) -> None:
    service = _build_service(base_dir)
    try:
        workflow = ProjectWorkflow(base_dir=base_dir or _default_base_dir())
        task_graph = workflow.load_task_graph(project_id)
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except PersistenceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    try:
        proposal = service.replan_control.create_proposal(project_id, run_id, task_graph)
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
        proposal = service.apply_replan(project_id, proposal_id, run_id=project.last_run_id or "")
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
    typer.echo(f"Run ID: {proposal.run_id}")
    typer.echo(f"Status: {proposal.status.value}")


run_app = typer.Typer(add_completion=False, no_args_is_help=True, help="管理项目执行运行")
app.add_typer(run_app, name="run", help="管理项目执行运行")


@run_app.command("start")
def run_start(project_id: str, base_dir: Path | None = typer.Option(None, "--base-dir"), run_dir: Path | None = typer.Option(None, "--run-dir", help="Executor workspace directory (defaults to <base-dir>/workspaces/<project>)."), executor: str = typer.Option("hermes", "--executor", help="Executor backend: hermes (sandboxed CLI agent) or mock (offline)."), task_timeout: int | None = typer.Option(None, "--timeout", help="Per-task executor timeout in seconds (default 300; env PROJECTFORGE_TASK_TIMEOUT_SECONDS).")) -> None:
    service = _build_service(base_dir, executor=executor, task_timeout=task_timeout)
    try:
        result = service.execute_run(project_id, run_dir=run_dir)
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
def run_resume(project_id: str, run_id: str, proposal_id: str, base_dir: Path | None = typer.Option(None, "--base-dir"), run_dir: Path | None = typer.Option(None, "--run-dir", help="Executor workspace directory (defaults to <base-dir>/workspaces/<project>)."), executor: str = typer.Option("hermes", "--executor", help="Executor backend: hermes (sandboxed CLI agent) or mock (offline)."), task_timeout: int | None = typer.Option(None, "--timeout", help="Per-task executor timeout in seconds (default 300; env PROJECTFORGE_TASK_TIMEOUT_SECONDS).")) -> None:
    service = _build_service(base_dir, executor=executor, task_timeout=task_timeout)
    try:
        result = service.resume_project(project_id, proposal_id, run_id, run_dir=run_dir)
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
    typer.echo(f"Project ID: {project_id}")
    typer.echo(f"Status: {result.status.value}")
    if result.last_run_id:
        typer.echo(f"Last Run ID: {result.last_run_id}")


if __name__ == "__main__":
    app()
