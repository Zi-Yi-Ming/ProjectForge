# Content Agent

Turn any GitHub repository into a short-form developer video.

```
GitHub Repository
       ↓
   Research
       ↓
Fact Extraction & Validation
       ↓
  Script Generation
       ↓
Visual / Voice / Subtitle
       ↓
  FFmpeg Rendering
       ↓
1080×1920 Short Video
```

## Demo

Real outputs from the pipeline, not placeholders.

- [Django demo](examples/django/final.mp4) — `examples/django/script.json`, `examples/django/research.json`
- [React demo](examples/react/final.mp4) — `examples/react/script.json`, `examples/react/research.json`
- [Spring Boot demo](examples/spring-boot/final.mp4) — `examples/spring-boot/script.json`, `examples/spring-boot/research.json`

| Demo | Duration | Resolution | FPS | Audio |
| --- | --- | --- | --- | --- |
| Django | ~27s | 1080×1920 | 30 | AAC |
| React | ~30s | 1080×1920 | 30 | AAC |
| Spring Boot | ~40s | 1080×1920 | 30 | AAC |

Each demo directory contains the generated `final.mp4`, `script.json`, and `research.json` from a fresh end-to-end run.

## Features

- **Repo-specific content**: extracts facts from GitHub README and metadata, not generic templates
- **5-scene script**: hook, community stats, tech fact, project highlight, CTA
- **Voiceover & subtitles**: TTS-generated audio with SRT subtitles
- **Vertical video**: 1080×1920, H.264, 30fps, AAC
- **Quality checks**: README pollution filters, markdown/URL/path removal, cross-scene dedup, proper noun casing

## Architecture

```
app/
  agents/
    researcher.py   # GitHub README / repo metadata → research.json
    writer.py       # research.json → script.json (5 scenes)
    visual.py       # scene prompts → images
    voice.py        # scene voiceover → audio
    subtitle.py     # voiceover + timing → subtitles
  pipeline/
    state.py        # task state machine
    workflow.py     # orchestrates agents and render
  providers/
    github.py       # GitHub API client
    step.py         # StepFun API client
    cache.py        # disk-backed cache
    edge_tts.py     # fallback TTS provider
  render/
    ffmpeg.py       # image + audio + subtitle → final.mp4
  schemas/
    research.py     # ResearchOutput model
    script.py       # ScriptOutput model
  config.py         # settings loaded from .env
```

## Quick Start

```bash
cp .env.example .env
# edit .env and set STEPFUN_API_KEY and optional GITHUB_TOKEN

source .venv/bin/activate
python main.py --input "https://github.com/django/django"
```

Outputs are written under `tasks/<task_id>/` and `outputs/<task_id>/`.

## Configuration

Environment variables are loaded from `.env`.

| Variable | Purpose |
| --- | --- |
| `STEPFUN_API_KEY` | StepFun API key for LLM / image / TTS |
| `GITHUB_TOKEN` | GitHub token for higher API rate limits |
| `STEPFUN_BASE_URL` | StepFun API base URL |
| `STEPFUN_MODEL_FAST` | Fast model ID |
| `STEPFUN_MODEL_AGENT` | Research / script model ID |
| `STEPFUN_MODEL_REASONING` | Reasoning model ID |
| `STEPFUN_MODEL_VISION` | Vision model ID |
| `STEPFUN_MODEL_IMAGE` | Image generation model ID |
| `STEPFUN_MODEL_TTS` | TTS model ID |
| `STEPFUN_TTS_VOICE` | TTS voice |
| `STEPFUN_TTS_RESPONSE_FORMAT` | TTS audio format |
| `STEPFUN_TIMEOUT` | Request timeout |
| `STEPFUN_MAX_RETRIES` | Retry count |
| `LOG_LEVEL` | Logging level |

## Validation

The writer and researcher have been validated against fresh end-to-end runs for:

- `django/django`
- `facebook/react`
- `spring-projects/spring-boot`

Validation includes:

- research cleaning: no README原文污染, markdown, URL, path, heading, polite phrase, fragment, trailing colon
- script quality: exactly 5 scenes, non-mechanical hook, proper noun casing, repo-specific facts
- cross-scene checks: Scene 3/4 dedup, Scene 5 not copying earlier scenes
- voiceover / onscreen consistency
- `ffprobe` verification: h264, 1080×1920, 30fps, AAC, duration > 0

## Roadmap

- [ ] Support more repo languages and frameworks
- [ ] Improve visual prompt quality and consistency
- [ ] Add more TTS voice options
- [ ] Batch processing for multiple repos
- [ ] Web UI for preview and editing

## Notes

- `tasks/`, `cache/`, `logs/`, `outputs/`, and `.venv/` are gitignored.
- This is an actively iterating project; APIs and prompts may change.
- The examples in `examples/` are real pipeline outputs for demonstration.
