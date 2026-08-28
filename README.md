# Content Agent

Production-style automation workflow for researching GitHub repositories and producing short-form faceless video assets.

## Verified Connectivity (Phase 1)

- StepFun API endpoint reachable from this VM.
- GitHub API endpoint reachable from this VM.
- Default Step Plan base URL: https://api.stepfun.com/step_plan/v1

## Verified Model Mapping (Phase 2 Design)

| Role | Default Model | Notes |
| --- | --- | --- |
| Fast | step-3.7-flash | lightweight tasks |
| Agent | step-explore | long-form research and scripting |
| Reasoning | step-explore | complex planning tasks |
| Vision | step-1o-turbo-vision | visual QA |
| Image | step-image-edit-2 | AI image generation fallback |
| TTS | stepaudio-2.5-tts | speech synthesis |
| Router | step-router-v1 | optional router mode |

All model IDs are configurable via environment variables and should be treated as replaceable provider inputs.

## Current MVP Scope

- Input: GitHub URL or topic string
- Output: research.json, script.json, assets, audio, subtitles, render state
- Runtime: Python 3.12 venv, StepFun API, GitHub API, FFmpeg
- No Node.js, Chromium, or Docker required for Phase 2

## Setup

```bash
cd /home/azureuser/content-agent
cp .env.example .env
```

Edit `.env` and set at least:

- STEPFUN_API_KEY
- GITHUB_TOKEN (optional but recommended)

## CLI

```bash
source .venv/bin/activate
python main.py --check-only
python main.py --dry-run --input "<github_url_or_topic>"
python main.py --input "<github_url_or_topic>"
python main.py --stage script --input "<github_url_or_topic>"
python main.py --resume --input "<github_url_or_topic>"
python main.py --reset --input "<github_url_or_topic>"
```

## Task Data

- tasks/<task_id>/
- cache/
- logs/
- outputs/

Do not commit these directories. They are gitignored by default.
