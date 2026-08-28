from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional
from app.config import get_settings
from app.pipeline.state import Stage, State
from app.agents.researcher import ResearcherAgent
from app.agents.writer import WriterAgent
from app.agents.visual import VisualAgent
from app.agents.voice import VoiceAgent
from app.agents.subtitle import SubtitleAgent
from app.render.ffmpeg import build_render, copy_to_outputs, verify_mp4
from app.providers.base import ChatProvider, ImageProvider, TTSProvider, ResearchExtractor
logger = logging.getLogger(__name__)
settings = get_settings()
class WorkflowRunner:
    def __init__(
        self,
        github: ResearchExtractor,
        llm: ChatProvider,
        image: ImageProvider | None = None,
        tts: TTSProvider | None = None,
    ) -> None:
        self.github = github
        self.llm = llm
        self.image = image
        self.tts = tts
        self.researcher = ResearcherAgent(github=github, llm=llm)
        self.writer = WriterAgent(llm=llm)
        self.visual = VisualAgent(image_provider=image)
        self.voice = VoiceAgent(tts_provider=tts)
        self.subtitle = SubtitleAgent()

    def run(self, task_id: str, input_url: str, stage: str | None = None, resume: bool = False) -> State:
        state = State(task_id)
        state.input = {"input": input_url}

        if stage:
            target = Stage(stage.upper())
        else:
            target = Stage.COMPLETED

        resume_start = None
        if resume and state.current_stage == Stage.FAILED:
            resume_start = self._resume_target(state)
            target = Stage.COMPLETED

        research: Optional[ResearchOutput] = None
        script: Optional[ScriptOutput] = None

        # Stage 1: Research
        if self._should_run("research", state.current_stage, target, resume_start):
            state.set_stage(Stage.RESEARCHING)
            research = self.researcher.run(task_id, input_url)
            state.set_stage(Stage.RESEARCHED)
            state.metadata["topic"] = research.topic

        # Stage 2: Script
        if self._should_run("script", state.current_stage, target, resume_start):
            if research is None:
                research = self._load_research(state)
            state.set_stage(Stage.SCRIPTING)
            script = self.writer.run(task_id, research)
            state.set_stage(Stage.SCRIPTED)
            state.metadata["title"] = script.title

        # Stage 3: Visual
        if self._should_run("visual", state.current_stage, target, resume_start):
            if script is None:
                script = self._load_script(state)
            state.set_stage(Stage.GENERATING_ASSETS)
            self.visual.run(task_id, script)
            state.set_stage(Stage.ASSETS_READY)

        # Stage 4: Audio/TTS
        if self._should_run("audio", state.current_stage, target, resume_start):
            if script is None:
                script = self._load_script(state)
            state.set_stage(Stage.GENERATING_AUDIO)
            self.voice.run(task_id, script)
            state.set_stage(Stage.AUDIO_READY)

        # Stage 5: Subtitles
        if self._should_run("subtitle", state.current_stage, target, resume_start):
            if script is None:
                script = self._load_script(state)
            state.set_stage(Stage.GENERATING_SUBTITLES)
            self.subtitle.run(task_id, script)
            state.set_stage(Stage.SUBTITLES_READY)

        # Stage 6: Render
        if self._should_run("render", state.current_stage, target, resume_start):
            state.set_stage(Stage.RENDERING)
            try:
                render_path = build_render(task_id)
                output_path = copy_to_outputs(task_id, render_path)
                verification = verify_mp4(output_path)
                if not verification["exists"] or not verification["video_stream_present"]:
                    raise ValueError(f"MP4 verification failed: {verification}")
                state.set_stage(Stage.COMPLETED)
                state.metadata.pop("error", None)
            except Exception as exc:
                state.current_stage = Stage.FAILED
                state.metadata["error"] = str(exc)
                state.save()
                raise

        state.save()
        return state

    @staticmethod
    def _should_run(stage_name: str, current: Stage, target: Stage, resume_start: Stage | None = None) -> bool:
        """Determine if a stage should execute given current state, target, and optional resume start."""
        completed = {
            "research": Stage.RESEARCHED,
            "script": Stage.SCRIPTED,
            "visual": Stage.ASSETS_READY,
            "audio": Stage.AUDIO_READY,
            "subtitle": Stage.SUBTITLES_READY,
            "render": Stage.COMPLETED,
        }
        done_stage = completed.get(stage_name)

        stage_target_map = {
            "research": Stage.RESEARCHING,
            "script": Stage.SCRIPTING,
            "visual": Stage.GENERATING_ASSETS,
            "audio": Stage.GENERATING_AUDIO,
            "subtitle": Stage.GENERATING_SUBTITLES,
            "render": Stage.RENDERING,
        }

        # Resume mode: only run stages at or after resume_start
        if resume_start is not None:
            resume_order = [
                Stage.RESEARCHING,
                Stage.SCRIPTING,
                Stage.GENERATING_ASSETS,
                Stage.GENERATING_AUDIO,
                Stage.GENERATING_SUBTITLES,
                Stage.RENDERING,
            ]
            try:
                stage_order_idx = next(i for i, s in enumerate(resume_order) if s == stage_target_map.get(stage_name))
                resume_order_idx = next(i for i, s in enumerate(resume_order) if s == resume_start)
            except StopIteration:
                return False
            if stage_order_idx < resume_order_idx:
                return False
            # For resume, skip if already done
            if done_stage and current == done_stage:
                return False
            return True

        # Non-resume mode
        # If target is before this stage, skip
        target_stage = stage_target_map.get(stage_name)
        if target_stage:
            order = [s for s in Stage]
            target_idx = order.index(target)
            stage_idx = order.index(target_stage)
            if target_idx < stage_idx:
                return False

        # If already at done stage, skip
        if current == done_stage:
            return False

        return True

    @staticmethod
    def _load_research(state: State) -> "ResearchOutput":
        import json
        from app.schemas.research import ResearchOutput
        path = state.root / "research.json"
        return ResearchOutput.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def _load_script(state: State) -> "ScriptOutput":
        import json
        from app.schemas.script import ScriptOutput
        path = state.root / "script.json"
        return ScriptOutput.model_validate_json(path.read_text(encoding="utf-8"))

    def _resume_target(self, state: State) -> Stage:
        task_dir = state.root
        if not (task_dir / "script.json").exists():
            return Stage.RESEARCHING
        if not (task_dir / "assets").exists() or not any((task_dir / "assets").glob("*.png")):
            return Stage.GENERATING_ASSETS
        if not (task_dir / "audio").exists() or not any((task_dir / "audio").glob("*.mp3")):
            return Stage.GENERATING_AUDIO
        if not (task_dir / "subtitles" / "subtitle.srt").exists():
            return Stage.GENERATING_SUBTITLES
        return Stage.RENDERING
