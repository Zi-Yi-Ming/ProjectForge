from __future__ import annotations
import json
import logging
import sys
from pathlib import Path
from typing import Optional
import typer
import httpx
from app.config import get_settings
from app.pipeline.state import Stage
from app.pipeline.workflow import WorkflowRunner
from app.providers.base import ChatProvider, ImageProvider, TTSProvider, ResearchExtractor
from app.providers.github import GitHubProvider
from app.providers.step import StepProvider
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()
app = typer.Typer()
def _providers(enable_image: bool, enable_tts: bool) -> tuple[ResearchExtractor, ChatProvider, Optional[ImageProvider], Optional[TTSProvider]]:
    github = GitHubProvider(token=settings.github.token or None)
    step = StepProvider()
    image = step if enable_image else None
    tts = step if enable_tts else None
    return github, step, image, tts
@app.command()
def main(
    input: str = typer.Option(None, help="GitHub URL or topic string"),
    task_id: str = typer.Option(None, help="Task ID, auto-generated if omitted"),
    check_only: bool = typer.Option(False, help="Run connectivity checks only"),
    dry_run: bool = typer.Option(False, help="Print execution plan without running"),
    stage: Optional[str] = typer.Option(None, help="Run a specific stage only"),
    resume: bool = typer.Option(False, help="Resume from last saved state"),
    reset: bool = typer.Option(False, help="Reset task state before running"),
    no_image: bool = typer.Option(False, help="Disable AI image generation"),
    no_tts: bool = typer.Option(False, help="Disable TTS"),
) -> None:
    if check_only:
        ok = True
        try:
            with httpx.Client(base_url=settings.step.base_url, timeout=settings.step.timeout) as client:
                resp = client.get("/models", headers={"Authorization": f"Bearer {settings.step.api_key}"})
                logger.info("step_models_status=%s", resp.status_code)
                ok = ok and resp.status_code == 200
        except Exception as exc:
            logger.error("step_connect_error=%s", exc)
            ok = False
        try:
            with httpx.Client(base_url="https://api.github.com", timeout=30) as client:
                resp = client.get("/rate_limit")
                logger.info("github_rate_limit_status=%s", resp.status_code)
                ok = ok and resp.status_code == 200
        except Exception as exc:
            logger.error("github_connect_error=%s", exc)
            ok = False
        typer.echo(json.dumps({"check_only": True, "ok": ok}, ensure_ascii=False))
        raise typer.Exit(code=0 if ok else 1)
    if dry_run:
        plan = {
            "task_id": task_id or "default",
            "input": input,
            "models": {
                "agent": settings.step.model_agent,
                "fast": settings.step.model_fast,
                "vision": settings.step.model_vision,
                "image": settings.step.model_image,
                "tts": settings.step.model_tts,
                "router": settings.step.router_model,
            },
            "stages": [s.value for s in Stage],
        }
        typer.echo(json.dumps(plan, ensure_ascii=False, indent=2))
        raise typer.Exit(code=0)
    if not input:
        typer.echo("Missing --input for non-check/dry-run modes.")
        raise typer.Exit(code=2)
    effective_task = task_id or str(abs(hash(input)))
    github, llm, image, tts = _providers(enable_image=not no_image, enable_tts=not no_tts)
    runner = WorkflowRunner(github=github, llm=llm, image=image, tts=tts)
    state = runner.run(effective_task, input, stage=stage)
    typer.echo(json.dumps({"task_id": state.task_id, "stage": state.current_stage.value}, ensure_ascii=False))
if __name__ == "__main__":
    app()
