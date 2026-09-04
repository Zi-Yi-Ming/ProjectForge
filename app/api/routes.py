from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.schemas import (
    CreateProjectRequest,
    ErrorDetail,
    ErrorResponse,
    EventResponse,
    EventsResponse,
    ProjectResponse,
    TransitionProjectRequest,
)
from app.product.errors import (
    ActiveRunExistsError,
    CommandNotAllowedError,
    InvalidProjectStateError,
    InvalidStateTransitionError,
    PersistenceError,
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
)
from app.product.workflow import ProjectWorkflow
from app.product.service import ProjectService
from app.schemas.execution import ExecutionRun, ExecutionStatus
from app.schemas.project import ProjectStatus


def _to_response(project: Any) -> ProjectResponse:
    return ProjectResponse(
        project_id=project.project_id,
        name=project.name,
        status=project.status.value if hasattr(project.status, "value") else str(project.status),
        current_stage=project.current_stage,
        created_at=project.created_at,
        updated_at=project.updated_at,
        jd_profile_ref=project.jd_profile_ref,
        blueprint_ref=project.blueprint_ref,
        task_graph_ref=project.task_graph_ref,
        last_run_id=project.last_run_id,
    )


def create_api(service: ProjectService | None = None) -> FastAPI:
    api = FastAPI(title="ProjectForge Product API", version="0.1.0")
    service = service or ProjectService()

    @api.post("/projects", response_model=ProjectResponse, status_code=201)
    def create_project(request: CreateProjectRequest) -> JSONResponse:
        try:
            project = service.create(request.name)
        except ProjectAlreadyExistsError as exc:
            return JSONResponse(
                status_code=409,
                content=ErrorResponse(error=ErrorDetail(code="PROJECT_ALREADY_EXISTS", message=str(exc))).model_dump(),
            )
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(error=ErrorDetail(code="PERSISTENCE_ERROR", message=f"Failed to create project: {exc}")).model_dump(),
            )
        return JSONResponse(status_code=201, content=_to_response(project).model_dump())

    @api.get("/projects/{project_id}", response_model=ProjectResponse)
    def get_project(project_id: str) -> JSONResponse:
        try:
            project = service.load(project_id)
        except ProjectNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(error=ErrorDetail(code="PROJECT_NOT_FOUND", message=str(exc))).model_dump(),
            )
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(error=ErrorDetail(code="PERSISTENCE_ERROR", message=f"Failed to load project: {exc}")).model_dump(),
            )
        return JSONResponse(status_code=200, content=_to_response(project).model_dump())

    @api.post("/projects/{project_id}/transition", response_model=ProjectResponse)
    def transition_project(project_id: str, request: TransitionProjectRequest) -> JSONResponse:
        try:
            target = ProjectStatus(request.target_status)
        except ValueError as exc:
            return JSONResponse(
                status_code=409,
                content=ErrorResponse(error=ErrorDetail(code="INVALID_STATE_TRANSITION", message=f"Invalid target status: {request.target_status}")).model_dump(),
            )
        try:
            project = service.transition_to(project_id, target)
        except ProjectNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(error=ErrorDetail(code="PROJECT_NOT_FOUND", message=str(exc))).model_dump(),
            )
        except InvalidStateTransitionError as exc:
            return JSONResponse(
                status_code=409,
                content=ErrorResponse(error=ErrorDetail(code="INVALID_STATE_TRANSITION", message=str(exc))).model_dump(),
            )
        except InvalidProjectStateError as exc:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(error=ErrorDetail(code="INVALID_PROJECT_STATE", message=str(exc))).model_dump(),
            )
        except ActiveRunExistsError as exc:
            return JSONResponse(
                status_code=409,
                content=ErrorResponse(error=ErrorDetail(code="ACTIVE_RUN_EXISTS", message=str(exc))).model_dump(),
            )
        except CommandNotAllowedError as exc:
            return JSONResponse(
                status_code=409,
                content=ErrorResponse(error=ErrorDetail(code="COMMAND_NOT_ALLOWED", message=str(exc))).model_dump(),
            )
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(error=ErrorDetail(code="PERSISTENCE_ERROR", message=f"Failed to transition project: {exc}")).model_dump(),
            )
        return JSONResponse(status_code=200, content=_to_response(project).model_dump())

    @api.get("/projects/{project_id}/events", response_model=EventsResponse)
    def get_project_events(project_id: str) -> JSONResponse:
        try:
            events = service.event_store.get_events(project_id)
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(error=ErrorDetail(code="PERSISTENCE_ERROR", message=f"Failed to load events: {exc}")).model_dump(),
            )
        return JSONResponse(
            status_code=200,
            content=EventsResponse(
                project_id=project_id,
                events=[
                    EventResponse(
                        event_id=event.event_id,
                        event_type=event.event_type,
                        project_id=event.project_id,
                        timestamp=event.timestamp,
                        actor=event.actor.value if hasattr(event.actor, "value") else str(event.actor),
                        payload=event.payload,
                    )
                    for event in events
                ],
            ).model_dump(),
        )

    @api.post("/projects/{project_id}/runs")
    def start_run(project_id: str) -> JSONResponse:
        try:
            project = service.load(project_id)
        except ProjectNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(error=ErrorDetail(code="PROJECT_NOT_FOUND", message=str(exc))).model_dump(),
            )
        try:
            result = service.execute_run(project_id, run_dir=None)
        except InvalidProjectStateError as exc:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(error=ErrorDetail(code="INVALID_PROJECT_STATE", message=str(exc))).model_dump(),
            )
        except PersistenceError as exc:
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(error=ErrorDetail(code="PERSISTENCE_ERROR", message=f"Failed to start run: {exc}")).model_dump(),
            )
        return JSONResponse(status_code=201, content={
            "run": {
                "run_id": result.last_run_id or "",
                "project_id": project_id,
                "status": result.status.value,
            }
        })

    @api.get("/projects/{project_id}/runs/{run_id}")
    def get_run(project_id: str, run_id: str) -> JSONResponse:
        try:
            run = service.run_control.get_run(run_id)
        except ProjectNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(error=ErrorDetail(code="RUN_NOT_FOUND", message=str(exc))).model_dump(),
            )
        except PersistenceError as exc:
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(error=ErrorDetail(code="PERSISTENCE_ERROR", message=str(exc))).model_dump(),
            )
        return JSONResponse(status_code=200, content={"run": {"run_id": run.run_id, "project_id": run.project, "status": run.status.value}})

    @api.post("/projects/{project_id}/runs/{run_id}/cancel")
    def cancel_run(project_id: str, run_id: str) -> JSONResponse:
        try:
            run = service.run_control.cancel_run(project_id, run_id)
        except Exception as exc:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(error=ErrorDetail(code="RUN_NOT_FOUND", message=str(exc))).model_dump(),
            )
        return JSONResponse(status_code=200, content={"run": {"run_id": run.run_id, "project_id": run.project, "status": run.status.value, "blocking_reason": run.blocking_reason}})

    @api.post("/projects/{project_id}/runs/{run_id}/replan")
    def create_replan(project_id: str, run_id: str) -> JSONResponse:
        try:
            task_graph = ProjectWorkflow().load_task_graph(project_id)
            if task_graph is None:
                raise InvalidProjectStateError("Task graph could not be loaded.")
            proposal = service.replan_control.create_proposal(project_id, run_id, task_graph)
        except ProjectNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(error=ErrorDetail(code="PROJECT_NOT_FOUND", message=str(exc))).model_dump(),
            )
        except InvalidProjectStateError as exc:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(error=ErrorDetail(code="INVALID_PROJECT_STATE", message=str(exc))).model_dump(),
            )
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(error=ErrorDetail(code="PERSISTENCE_ERROR", message=f"Failed to create replan proposal: {exc}")).model_dump(),
            )
        return JSONResponse(status_code=200, content={"proposal": {"proposal_id": proposal.proposal_id, "run_id": proposal.run_id, "status": proposal.status.value, "action": proposal.action.value, "task_id": proposal.task_id}})

    @api.get("/projects/{project_id}/replans/{run_id}/{proposal_id}")
    def get_replan(project_id: str, run_id: str, proposal_id: str) -> JSONResponse:
        try:
            proposal = service.replan_control.get_proposal(run_id, proposal_id)
        except Exception as exc:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(error=ErrorDetail(code="PROPOSAL_NOT_FOUND", message=str(exc))).model_dump(),
            )
        return JSONResponse(status_code=200, content={"proposal": {"proposal_id": proposal.proposal_id, "run_id": proposal.run_id, "status": proposal.status.value}})

    @api.post("/projects/{project_id}/replans/{run_id}/{proposal_id}/approve")
    def approve_replan(project_id: str, run_id: str, proposal_id: str) -> JSONResponse:
        try:
            proposal = service.replan_control.approve_proposal(project_id, run_id, proposal_id)
        except InvalidProjectStateError as exc:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(error=ErrorDetail(code="INVALID_PROJECT_STATE", message=str(exc))).model_dump(),
            )
        except Exception as exc:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(error=ErrorDetail(code="PROPOSAL_NOT_FOUND", message=str(exc))).model_dump(),
            )
        return JSONResponse(status_code=200, content={"proposal": {"proposal_id": proposal.proposal_id, "run_id": proposal.run_id, "status": proposal.status.value}})

    @api.post("/projects/{project_id}/replans/{run_id}/{proposal_id}/reject")
    def reject_replan(project_id: str, run_id: str, proposal_id: str) -> JSONResponse:
        try:
            proposal = service.replan_control.reject_proposal(project_id, run_id, proposal_id)
        except InvalidProjectStateError as exc:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(error=ErrorDetail(code="INVALID_PROJECT_STATE", message=str(exc))).model_dump(),
            )
        except Exception as exc:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(error=ErrorDetail(code="PROPOSAL_NOT_FOUND", message=str(exc))).model_dump(),
            )
        return JSONResponse(status_code=200, content={"proposal": {"proposal_id": proposal.proposal_id, "run_id": proposal.run_id, "status": proposal.status.value}})

    @api.post("/projects/{project_id}/replans/{run_id}/{proposal_id}/apply")
    def apply_replan(project_id: str, run_id: str, proposal_id: str) -> JSONResponse:
        try:
            proposal = service.apply_replan(project_id, proposal_id, run_id=run_id)
        except ProjectNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(error=ErrorDetail(code="PROJECT_NOT_FOUND", message=str(exc))).model_dump(),
            )
        except InvalidProjectStateError as exc:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(error=ErrorDetail(code="INVALID_PROJECT_STATE", message=str(exc))).model_dump(),
            )
        except Exception as exc:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(error=ErrorDetail(code="PROPOSAL_NOT_FOUND", message=str(exc))).model_dump(),
            )
        return JSONResponse(status_code=200, content={"proposal": {"proposal_id": proposal.proposal_id, "run_id": proposal.run_id, "status": proposal.status.value}})

    @api.post("/projects/{project_id}/runs/resume")
    def resume_run(project_id: str, run_id: str, proposal_id: str) -> JSONResponse:
        try:
            result = service.resume_project(project_id, proposal_id, run_id)
        except ProjectNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(error=ErrorDetail(code="PROJECT_NOT_FOUND", message=str(exc))).model_dump(),
            )
        except InvalidProjectStateError as exc:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(error=ErrorDetail(code="INVALID_PROJECT_STATE", message=str(exc))).model_dump(),
            )
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(error=ErrorDetail(code="PERSISTENCE_ERROR", message=f"Failed to resume project: {exc}")).model_dump(),
            )
        return JSONResponse(status_code=201, content={"project": {"project_id": project_id, "status": result.status.value, "last_run_id": result.last_run_id or ""}})

    return api


def _dummy_task_graph() -> Any:
    from app.schemas.task import Task, TaskGraph, TaskStatus
    tasks = [
        Task(id="T1", phase_id="P1", title="T1", goal="g1", why="w1", dependencies=[], status=TaskStatus.DONE, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
        Task(id="T2", phase_id="P1", title="T2", goal="g2", why="w2", dependencies=["T1"], status=TaskStatus.FAILED, scope="Core", acceptance_criteria=[], out_of_scope=[], interview_points=[]),
    ]
    return TaskGraph(project="demo", tasks=tasks, total_tasks=2, required_tasks=2, optional_tasks=0)


def _dummy_run_dir() -> Any:
    from pathlib import Path
    return Path("/tmp/dummy-run-dir")
