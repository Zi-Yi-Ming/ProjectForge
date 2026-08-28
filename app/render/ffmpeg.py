from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _probe_duration(path: Path) -> float:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        value = proc.stdout.strip()
        if not value:
            return 0.0
        duration = float(value)
        return duration if duration > 0 else 0.0
    except Exception as exc:
        logger.debug("ffprobe duration failed path=%s error=%s", path, exc)
        return 0.0


def _run_ffmpeg(cmd: list[str], step_name: str) -> None:
    logger.info("ffmpeg %s cmd=%s", step_name, " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        error_msg = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(
            f"FFmpeg {step_name} failed with exit code {proc.returncode}: {error_msg}"
        )
    if proc.stderr:
        logger.debug("ffmpeg %s stderr=%s", step_name, proc.stderr[:1000])


def _scale_asset_to_1080p(asset_path: Path, temp_dir: Path, index: int) -> Path:
    """Pre-scale static image to 1080x1920 exactly using Pillow-like approach via FFmpeg."""
    # Since assets are already 1080x1920 from placeholder generation,
    # and real images may be different sizes, we create a standardized video segment
    # with a single fast scale operation
    output = temp_dir / f"scene_{index:03d}_scaled.mp4"
    
    # Use a fast preset and minimal filtering for static images
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(asset_path),
        "-f", "lavfi", "-i", "aevalsrc=0:s=44100:c=mono:d=0.1",  # placeholder audio, duration will be overridden
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "1",
        "-shortest",
        str(output),
    ]
    _run_ffmpeg(cmd, f"scale_asset_{index}")
    return output


def _create_scene_video(
    asset_path: Path,
    audio_path: Path,
    duration: float,
    temp_dir: Path,
    index: int,
) -> tuple[Path, Path]:
    """Create a single scene video and audio with proper duration."""
    video_output = temp_dir / f"scene_{index:03d}.mp4"
    audio_output = temp_dir / f"scene_{index:03d}_audio.m4a" if audio_path else None
    
    # Build video from image with exact duration
    if audio_path and audio_path.exists() and audio_path.stat().st_size > 0:
        # Use actual audio duration
        audio_duration = _probe_duration(audio_path)
        if audio_duration <= 0:
            audio_duration = duration
        duration = max(audio_duration, duration)
        
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(asset_path),
            "-i", str(audio_path),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "1",
            "-shortest",
            str(video_output),
        ]
    else:
        # No audio, create silent video
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(asset_path),
            "-f", "lavfi", "-i", f"aevalsrc=0:s=44100:c=mono:d={duration:.3f}",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "1",
            "-t", str(duration),
            str(video_output),
        ]
    
    _run_ffmpeg(cmd, f"scene_video_{index}")
    return video_output, audio_output


def _concat_scenes(scene_videos: list[Path], scene_audios: list[Path], output: Path) -> None:
    """Concat scene videos and audios into final output."""
    if len(scene_videos) == 1:
        # Single scene, just copy
        shutil.copy2(scene_videos[0], output)
        return
    
    # Create concat list for video
    concat_list = output.parent / "concat.txt"
    video_concat = output.parent / "concat_videos.txt"
    audio_concat = output.parent / "concat_audios.txt"
    
    with open(video_concat, "w") as f:
        for v in scene_videos:
            f.write(f"file '{v.resolve()}'\n")
    
    # Concat videos
    temp_video = output.parent / "temp_concat.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(video_concat),
        "-c", "copy",
        str(temp_video),
    ]
    _run_ffmpeg(cmd, "concat_videos")
    
    if any(a and a.exists() for a in scene_audios):
        # Create concat list for audio
        with open(audio_concat, "w") as f:
            for a in scene_audios:
                if a and a.exists():
                    f.write(f"file '{a.resolve()}'\n")
        
        temp_audio = output.parent / "temp_concat.m4a"
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(audio_concat),
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "1",
            str(temp_audio),
        ]
        _run_ffmpeg(cmd, "concat_audios")
        
        # Mux video + audio
        cmd = [
            "ffmpeg", "-y",
            "-i", str(temp_video),
            "-i", str(temp_audio),
            "-c:v", "copy", "-c:a", "copy",
            str(output),
        ]
        _run_ffmpeg(cmd, "mux")
        
        # Cleanup temp files
        temp_video.unlink(missing_ok=True)
        temp_audio.unlink(missing_ok=True)
    else:
        # No audio, just copy video
        shutil.move(str(temp_video), str(output))
    
    # Cleanup
    video_concat.unlink(missing_ok=True)
    audio_concat.unlink(missing_ok=True)


def _burn_subtitles(input_video: Path, srt_path: Path, output: Path) -> None:
    """Burn subtitles onto video."""
    if not srt_path.exists():
        shutil.copy2(input_video, output)
        return
    
    # Escape paths for FFmpeg subtitles filter
    escaped_srt = str(srt_path.resolve()).replace(":", "\\\\:").replace("\\'", "\\\\'")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-vf", f"subtitles='{escaped_srt}':force_style='FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Alignment=2,MarginV=30'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(output),
    ]
    _run_ffmpeg(cmd, "burn_subtitles")


def build_render(task_id: str) -> Path:
    task_dir = settings.tasks_dir / task_id
    video_dir = task_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)

    script = task_dir / "script.json"
    if not script.exists():
        raise FileNotFoundError("script.json missing")

    data = json.loads(script.read_text(encoding="utf-8"))
    scenes = data.get("scenes", [])
    if not scenes:
        raise ValueError("script has no scenes")

    output = video_dir / "final.mp4"
    temp_dir = video_dir / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Stage 1: Create individual scene videos
        scene_videos: list[Path] = []
        scene_audios: list[Path] = []
        
        for idx, scene in enumerate(scenes):
            asset = task_dir / "assets" / f"scene_{idx+1:03d}.png"
            audio = task_dir / "audio" / f"scene_{idx+1:03d}.mp3"
            
            asset_path = asset if asset.exists() else None
            audio_path = audio if audio.exists() and audio.stat().st_size > 0 else None
            
            if not asset_path:
                raise FileNotFoundError(f"asset missing for scene {idx+1}")
            
            script_duration = max(float(scene.get("duration", 5)), 0.1)
            
            video_file, audio_file = _create_scene_video(
                asset_path, audio_path, script_duration, temp_dir, idx
            )
            scene_videos.append(video_file)
            scene_audios.append(audio_file)
        
        # Stage 2: Concat scenes
        concat_output = temp_dir / "concat.mp4"
        _concat_scenes(scene_videos, scene_audios, concat_output)
        
        # Stage 3: Burn subtitles
        srt = task_dir / "subtitles" / "subtitle.srt"
        if srt.exists():
            _burn_subtitles(concat_output, srt, output)
            concat_output.unlink(missing_ok=True)
        else:
            shutil.move(str(concat_output), str(output))
        
        logger.info("ffmpeg render complete task_id=%s output=%s", task_id, output)
        return output
    
    finally:
        # Cleanup temp files
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def copy_to_outputs(task_id: str, source: Path) -> Path:
    out_dir = settings.outputs_dir / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "final.mp4"
    dest.write_bytes(source.read_bytes())
    return dest


def verify_mp4(path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        str(path),
    ]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    return {
        "exists": path.exists(),
        "video_stream_present": bool(video),
        "audio_stream_present": bool(audio),
        "width": video.get("width"),
        "height": video.get("height"),
        "codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "duration": data.get("format", {}).get("duration"),
        "path": str(path),
    }
