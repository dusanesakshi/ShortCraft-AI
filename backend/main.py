
import base64
import binascii
import io
import json
import os
import shutil
import subprocess
import tempfile
import uuid

from pathlib import Path

from PIL import Image
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import OpenAI, APIError, AuthenticationError, RateLimitError
from pydantic import BaseModel, Field
from fastapi import UploadFile, File, Form
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from backend.captions import build_classic_bold_ass
from backend.reddit_card import render_reddit_card

# Load environment variables from the project-root .env file.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

FFMPEG_PATH = os.getenv("FFMPEG_PATH")
FFMPEG_COMPOSE_TIMEOUT_SECONDS = int(
    os.getenv("FFMPEG_COMPOSE_TIMEOUT_SECONDS", "1800")
)

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "generated_videos")
os.makedirs(OUTPUT_DIR, exist_ok=True)


if not FFMPEG_PATH:
    raise RuntimeError("FFMPEG_PATH is missing from the .env file.")

if not os.path.isfile(FFMPEG_PATH):
    raise RuntimeError(
        f"FFmpeg executable was not found at: {FFMPEG_PATH}"
    )

ALLOWED_VIDEO_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/webm",
}
ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/mp3"}
ALLOWED_CARD_IMAGE_TYPES = {"image/png", "application/octet-stream"}

VERTICAL_VIDEO_FILTER = (
    "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
)
CARD_OVERLAY_WIDTH = 900
CARD_OVERLAY_TOP_Y = 260
CARD_INTRO_ZOOM_MAX = 1.025
CARD_INTRO_ZOOM_DELTA = CARD_INTRO_ZOOM_MAX - 1.0


def _ffmpeg_filter_path(path: Path) -> str:
    """Escape a filesystem path for FFmpeg filter arguments (Windows-safe)."""
    return (
        path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
    )


def _ffprobe_path() -> str:
    ffmpeg_path = Path(FFMPEG_PATH)
    probe_name = "ffprobe.exe" if ffmpeg_path.suffix.lower() == ".exe" else "ffprobe"
    probe_path = ffmpeg_path.with_name(probe_name)
    if not probe_path.is_file():
        raise RuntimeError(
            f"ffprobe was not found next to FFmpeg at: {probe_path}"
        )
    return str(probe_path)


def _media_duration_seconds(media_path: Path) -> float:
    command = [
        _ffprobe_path(),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(media_path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        print("ffprobe error:", result.stderr[-2000:])
        raise HTTPException(
            status_code=500,
            detail="Could not read narration duration.",
        )

    try:
        payload = json.loads(result.stdout)
        duration = float(payload["format"]["duration"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not parse narration duration.",
        ) from exc

    if duration <= 0:
        raise HTTPException(
            status_code=400,
            detail="Narration audio duration must be greater than zero.",
        )

    return duration


def _run_ffmpeg(
    command: list[str],
    *,
    timeout: int = 600,
    error_detail: str = "Video composition failed. Check the backend terminal.",
) -> None:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        print("FFmpeg error:", result.stderr[-4000:])
        raise HTTPException(status_code=500, detail=error_detail)


app = FastAPI(
    title="ShortCraft AI",
    description="AI-powered YouTube Shorts generation platform",
    version="0.3.0",
)


class StoryInput(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    target_duration: int = Field(default=45, ge=30, le=60)


class ScriptRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    target_duration: int = Field(default=45, ge=30, le=60)
    style: str = Field(default="engaging", max_length=30)


@app.get("/")
def root():
    return {
        "project": "ShortCraft AI",
        "status": "running",
        "version": "0.3.0",
    }


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/v1/story/prepare")
def prepare_story(story: StoryInput):
    cleaned_text = story.text.strip()

    if not cleaned_text:
        raise HTTPException(
            status_code=400,
            detail="Story text cannot be empty.",
        )

    words = cleaned_text.split()
    word_count = len(words)
    estimated_seconds = round((word_count / 150) * 60)
    target_word_count = round(story.target_duration * 2.2)

    return {
        "success": True,
        "original_text": cleaned_text,
        "character_count": len(cleaned_text),
        "word_count": word_count,
        "target_duration": story.target_duration,
        "estimated_seconds": estimated_seconds,
        "suggested_word_count": target_word_count,
        "message": "Story validated successfully.",
    }


@app.post("/api/v1/story/generate-script")
def generate_script(request: ScriptRequest):
    story_text = request.text.strip()

    if not story_text:
        raise HTTPException(
            status_code=400,
            detail="Story text cannot be empty.",
        )

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is missing from the project .env file.",
        )

    target_words = round(request.target_duration * 2.2)

    style_instructions = {
        "engaging": "Use an engaging, natural storytelling style.",
        "dramatic": "Use suspenseful pacing without inventing details.",
        "casual": "Use a conversational, relatable tone.",
        "mystery": "Emphasize genuine uncertainty and suspense in the source.",
    }

    style = request.style.lower()
    style_instruction = style_instructions.get(
        style,
        style_instructions["engaging"],
    )

    instructions = f"""
You are the narration script writer for ShortCraft AI,
an application that turns Reddit stories into YouTube Shorts.

Rewrite the user's source story as narration suitable for spoken audio.

Requirements:
- Aim for approximately {target_words} words for a
  {request.target_duration}-second video.
- {style_instruction}
- Start with a compelling hook based on the actual source.
- Use clear, natural spoken English and short sentences.
- Preserve the source's important events and meaning.
- Do not invent characters, events, dialogue, or outcomes.
- Do not claim that fictional or unverified events are facts.
- Do not include camera directions, headings, or explanations.
- Return only the narration script.
- If the source is too short to reach the target naturally,
  do not add fabricated events just to increase its length.
"""

    try:
        client = OpenAI(api_key=api_key)

        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            instructions=instructions,
            input=story_text,
        )

        generated_script = response.output_text.strip()

        if not generated_script:
            raise HTTPException(
                status_code=502,
                detail="The AI returned an empty script. Please try again.",
            )

        script_word_count = len(generated_script.split())
        estimated_seconds = round((script_word_count / 150) * 60)

        return {
            "success": True,
            "original_word_count": len(story_text.split()),
            "script": generated_script,
            "script_word_count": script_word_count,
            "target_duration": request.target_duration,
            "estimated_script_seconds": estimated_seconds,
            "style": style,
            "message": "Narration script generated successfully.",
        }

    except AuthenticationError:
        raise HTTPException(
            status_code=401,
            detail="OpenAI authentication failed. Check your API key.",
        )

    except RateLimitError:
        raise HTTPException(
            status_code=429,
            detail=(
                "OpenAI rate limit or quota reached. "
                "Check your API account and billing limits."
            ),
        )

    except APIError:
        raise HTTPException(
            status_code=502,
            detail="OpenAI could not complete the request. Please try again.",
        )

@app.post("/api/v1/video/compose")
async def compose_video(
    background_video: UploadFile = File(...),
    narration_audio: UploadFile = File(...),
):
    if background_video.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Upload an MP4, MOV, AVI, or MKV background video.",
        )

    if narration_audio.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Upload the narration as an MP3 file.",
        )

    job_dir = tempfile.TemporaryDirectory()
    work_dir = Path(job_dir.name)

    input_video = work_dir / "background_video"
    input_audio = work_dir / "narration.mp3"
    output_video = Path(OUTPUT_DIR) / f"shortcraft_{uuid.uuid4().hex}.mp4"

    try:
        with input_video.open("wb") as f:
            f.write(await background_video.read())

        with input_audio.open("wb") as f:
            f.write(await narration_audio.read())

        command = [
            FFMPEG_PATH,
            "-y",
            "-i", str(input_video),
            "-stream_loop", "-1",
            "-i", str(input_video),
            "-i", str(input_audio),
            "-map", "1:v:0",
            "-map", "2:a:0",
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_video),
        ]

        # Use the original video and narration as the actual inputs.
        # Loop the background video so it can cover the narration duration.
        command = [
            FFMPEG_PATH,
            "-y",
            "-stream_loop", "-1",
            "-i", str(input_video),
            "-i", str(input_audio),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_video),
        ]

        _run_ffmpeg(command)

        if not output_video.exists() or output_video.stat().st_size == 0:
            raise HTTPException(
                status_code=500,
                detail="FFmpeg did not produce a valid MP4 file.",
            )

        return FileResponse(
            path=str(output_video),
            media_type="video/mp4",
            filename="shortcraft_video.mp4",
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="Video composition timed out.",
        )

    except HTTPException:
        raise

    except Exception as exc:
        print(f"Video composition error: {exc}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred during video composition.",
        )

    finally:
        job_dir.cleanup()
        await background_video.close()
        await narration_audio.close()


@app.post("/api/v1/video/compose-with-card")
async def compose_video_with_card(
    background_video: UploadFile = File(...),
    narration_audio: UploadFile = File(...),
    card_image: UploadFile = File(...),
    card_duration: float = Form(...),
    caption_style: str = Form(default=""),
    caption_script: str = Form(default=""),
    title_audio_duration: float = Form(default=0.0),
    caption_word_timings: str = Form(default=""),
):
    if background_video.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Upload an MP4, MOV, AVI, or MKV background video.",
        )

    if narration_audio.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Upload the narration as an MP3 file.",
        )

    if card_image.content_type not in ALLOWED_CARD_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Upload the Reddit card as a PNG image.",
        )

    if not 0.5 <= card_duration <= 10:
        raise HTTPException(
            status_code=400,
            detail="Card duration must be between 0.5 and 10 seconds.",
        )

    job_dir = tempfile.TemporaryDirectory()
    work_dir = Path(job_dir.name)

    input_video = work_dir / "background_video"
    input_audio = work_dir / "narration.mp3"
    input_card = work_dir / "reddit_card.png"
    intro_video = work_dir / "intro.mp4"
    main_video = work_dir / "main.mp4"
    concat_list = work_dir / "concat.txt"
    merged_video = work_dir / "merged_video.mp4"
    captioned_video = work_dir / "captioned.mp4"
    output_video = Path(OUTPUT_DIR) / f"shortcraft_{uuid.uuid4().hex}.mp4"

    try:
        with input_video.open("wb") as f:
            f.write(await background_video.read())

        with input_audio.open("wb") as f:
            f.write(await narration_audio.read())

        with input_card.open("wb") as f:
            f.write(await card_image.read())

        narration_duration = _media_duration_seconds(input_audio)
        main_end = card_duration + narration_duration
        compose_timeout = FFMPEG_COMPOSE_TIMEOUT_SECONDS

        intro_frame_count = max(1, int(30 * card_duration))
        intro_filter = (
            f"[0:v]trim=0:{card_duration},setpts=PTS-STARTPTS,"
            f"{VERTICAL_VIDEO_FILTER}[bg];"
            f"[1:v]scale={CARD_OVERLAY_WIDTH}:-1,"
            f"scale=w='{CARD_OVERLAY_WIDTH}*min({CARD_INTRO_ZOOM_MAX},"
            f"1+{CARD_INTRO_ZOOM_DELTA}*n/{intro_frame_count})':h=-1:eval=frame[card];"
            f"[bg][card]overlay=(W-w)/2:{CARD_OVERLAY_TOP_Y}:format=auto[outv]"
        )
        intro_command = [
            FFMPEG_PATH,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(input_video),
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(input_card),
            "-t",
            str(card_duration),
            "-filter_complex",
            intro_filter,
            "-map",
            "[outv]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-an",
            str(intro_video),
        ]
        _run_ffmpeg(
            intro_command,
            timeout=compose_timeout,
            error_detail="Card intro rendering failed.",
        )

        main_filter = (
            f"[0:v]trim={card_duration}:{main_end},setpts=PTS-STARTPTS,"
            f"{VERTICAL_VIDEO_FILTER}[outv]"
        )
        main_command = [
            FFMPEG_PATH,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(input_video),
            "-filter_complex",
            main_filter,
            "-map",
            "[outv]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-an",
            str(main_video),
        ]
        _run_ffmpeg(
            main_command,
            timeout=compose_timeout,
            error_detail="Background segment rendering failed.",
        )

        concat_list.write_text(
            f"file '{intro_video.as_posix()}'\nfile '{main_video.as_posix()}'\n",
            encoding="utf-8",
        )
        concat_command = [
            FFMPEG_PATH,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(merged_video),
        ]
        _run_ffmpeg(
            concat_command,
            timeout=compose_timeout,
            error_detail="Video concat failed.",
        )

        muxed_video = work_dir / "muxed.mp4"
        mux_command = [
            FFMPEG_PATH,
            "-y",
            "-i",
            str(merged_video),
            "-i",
            str(input_audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(muxed_video),
        ]
        _run_ffmpeg(
            mux_command,
            timeout=compose_timeout,
            error_detail="Final video mux failed.",
        )

        final_video = muxed_video
        parsed_word_timings: list[dict] = []
        if caption_word_timings.strip():
            try:
                payload = json.loads(caption_word_timings)
                if isinstance(payload, list):
                    parsed_word_timings = [
                        item for item in payload if isinstance(item, dict)
                    ]
            except json.JSONDecodeError:
                parsed_word_timings = []

        if caption_style.strip() == "Classic Bold" and (
            parsed_word_timings or caption_script.strip()
        ):
            ass_path = work_dir / "captions.ass"
            build_classic_bold_ass(
                caption_script,
                title_audio_duration=max(0.0, title_audio_duration),
                total_audio_duration=narration_duration,
                output_path=ass_path,
                word_timings=parsed_word_timings or None,
            )
            ass_filter_path = _ffmpeg_filter_path(ass_path)
            caption_command = [
                FFMPEG_PATH,
                "-y",
                "-i",
                str(muxed_video),
                "-vf",
                f"ass='{ass_filter_path}'",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                str(captioned_video),
            ]
            _run_ffmpeg(
                caption_command,
                timeout=compose_timeout,
                error_detail="Caption rendering failed.",
            )
            final_video = captioned_video

        shutil.copyfile(final_video, output_video)

        if not output_video.exists() or output_video.stat().st_size == 0:
            raise HTTPException(
                status_code=500,
                detail="FFmpeg did not produce a valid MP4 file.",
            )

        return FileResponse(
            path=str(output_video),
            media_type="video/mp4",
            filename="shortcraft_video.mp4",
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="Video composition timed out.",
        )

    except HTTPException:
        raise

    except Exception as exc:
        print(f"Video composition with card error: {exc}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred during video composition.",
        )

    finally:
        job_dir.cleanup()
        await background_video.close()
        await narration_audio.close()
        await card_image.close()


class RedditCardRequest(BaseModel):
    username: str = Field(default="Anonymous", max_length=60)
    title: str = Field(min_length=1, max_length=500)
    subreddit: str = Field(default="", max_length=100)
    verified: bool = False
    upvotes: str = Field(default="99+", max_length=20)
    comments: str = Field(default="99+", max_length=20)
    avatar_base64: str | None = None


MAX_AVATAR_BYTES = 2 * 1024 * 1024


def _decode_avatar_base64(data: str) -> Image.Image:
    payload = data.strip()
    if "," in payload and payload.lower().startswith("data:"):
        payload = payload.split(",", 1)[1]

    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid avatar image encoding.",
        ) from exc

    if len(raw) > MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=400,
            detail="Avatar image must be 2 MB or smaller.",
        )

    try:
        return Image.open(io.BytesIO(raw))
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail="Avatar must be a valid image file.",
        ) from exc


@app.post("/api/v1/card/render")
def render_card(request: RedditCardRequest):
    card_dir = Path(OUTPUT_DIR) / "reddit_cards"
    card_dir.mkdir(parents=True, exist_ok=True)

    card_path = card_dir / f"reddit_{uuid.uuid4().hex}.png"

    avatar_image = None
    if request.avatar_base64:
        avatar_image = _decode_avatar_base64(request.avatar_base64)

    try:
        render_reddit_card(
            username=request.username,
            title=request.title,
            subreddit=request.subreddit,
            verified=request.verified,
            upvotes=request.upvotes,
            comments=request.comments,
            avatar_image=avatar_image,
            output_path=str(card_path),
        )

        return FileResponse(
            path=str(card_path),
            media_type="image/png",
            filename="shortcraft_reddit_card.png",
        )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    except Exception as exc:
        print(f"Reddit card rendering error: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Could not render the Reddit card.",
        )
