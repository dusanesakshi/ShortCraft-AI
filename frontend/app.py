import asyncio
import base64
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

import edge_tts
import requests
import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH, override=True)


def format_api_error_detail(detail):
    """Format FastAPI validation errors for Streamlit display."""
    if isinstance(detail, list):
        lines = []
        for item in detail:
            loc = item.get("loc", ())
            msg = item.get("msg", item)
            field = ".".join(str(part) for part in loc if part != "body")
            lines.append(f"{field}: {msg}" if field else str(msg))
        return "\n".join(lines)
    return str(detail)


# ---------------------------------------------------------
# Page configuration
# ---------------------------------------------------------
st.set_page_config(
    page_title="ShortCraft AI",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------
# Styling
# ---------------------------------------------------------
st.markdown(
    """
    <style>
    .stApp {
        background: #17191f;
        color: #f2f2f5;
    }

    [data-testid="stHeader"] {
        background: #17191f;
    }

    [data-testid="stSidebar"] {
        background: #20232b;
    }

    .block-container {
        max-width: 1500px;
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }

    .project-header {
        background: #22252d;
        border: 1px solid #383b46;
        border-radius: 12px;
        padding: 18px 22px;
        margin-bottom: 14px;
    }

    .project-name {
        font-size: 21px;
        font-weight: 700;
    }

    .muted {
        color: #b0b2bd;
        font-size: 13px;
    }

    .stage-bar {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        background: #20232b;
        border: 1px solid #383b46;
        border-radius: 12px;
        padding: 14px;
        margin-bottom: 22px;
    }

    .stage {
        background: #2b2e38;
        color: #d0d1d9;
        padding: 9px 13px;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 600;
    }

    .stage.active {
        background: #42241f;
        color: #ff9a78;
        border: 1px solid #a64b2b;
    }

    .section-heading {
        font-size: 19px;
        font-weight: 700;
        margin-bottom: 12px;
    }

    .story-card {
        background: #22252d;
        border: 1px solid #383b46;
        border-radius: 12px;
        padding: 17px;
        margin: 10px 0;
    }

    .story-label {
        color: #b0b2bd;
        font-size: 12px;
        margin-bottom: 8px;
    }

    .preview-shell {
        background: #22252d;
        border: 1px solid #383b46;
        border-radius: 14px;
        padding: 16px;
    }

    .preview-screen {
        background: #111319;
        border: 1px solid #383b46;
        border-radius: 14px;
        padding: 12px;
        width: 100%;
        max-width: 330px;
        height: 440px;
        box-sizing: border-box;
        overflow: hidden;
        margin: 12px auto;
        display: flex;
        flex-direction: column;
        justify-content: center;
        text-align: center;
    }

    .preview-placeholder {
        color: #b0b2bd;
        font-size: 14px;
        line-height: 1.7;
    }

    /* Keep Streamlit's uploaded-video player at the same preview height. */
    [data-testid="stVideo"] {
        width: 100%;
        max-width: 330px;
        margin: 12px auto;
    }

    [data-testid="stVideo"] video {
        width: 100% !important;
        height: 440px !important;
        object-fit: cover !important;
        background: #111319;
        border-radius: 14px;
    }

    div.stButton > button {
        border-radius: 8px;
        font-weight: 600;
        min-height: 2.5rem;
    }

    div[data-testid="stFileUploader"] {
        background: #20232b;
        border: 1px solid #383b46;
        border-radius: 10px;
        padding: 8px;
    }

    div[data-testid="stTextArea"] textarea,
    div[data-testid="stTextInput"] input,
    div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
        background: #20232b;
    }

    hr {
        border-color: #383b46;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# Voice helpers
# ---------------------------------------------------------
def clear_story():
    st.session_state["story_text"] = ""
    st.session_state["reddit_url"] = ""
    st.session_state["script"] = ""
    st.session_state["script_editor"] = ""
    st.session_state["show_extra_story"] = False
    st.session_state["clear_video"] = True


FISH_TTS_URL = "https://api.fish.audio/v1/tts/stream/with-timestamp"
FISH_MODEL = "s2.1-pro-free"
NARRATION_CACHE_DIR = PROJECT_ROOT / "generated_videos" / "narration_cache"
EDGE_FALLBACK_VOICES = {
    "male": "en-US-GuyNeural",
    "female": "en-US-JennyNeural",
}

CURATED_REDDIT_FISH_VOICES = [
    {
        "id": "04205de46c44475a9fec148c805a8b3b",
        "title": "reddit",
        "gender": "female",
        "sample_url": "",
    },
    {
        "id": "ba9f1b6bde7f4d18ac2dcea831f8783d",
        "title": "Reddit",
        "gender": "female",
        "sample_url": "",
    },
    {
        "id": "a4d1a512d6b94f4bad685fbfb87cd800",
        "title": "UFR REDDIT",
        "gender": "female",
        "sample_url": "",
    },
    {
        "id": "d215c300d52243fdb1c411e1304f4777",
        "title": "m reddit reads",
        "gender": "male",
        "sample_url": "",
    },
    {
        "id": "d3dd3ce9f56847ed9629ca5c9019b890",
        "title": "Reddit male",
        "gender": "male",
        "sample_url": "",
    },
    {
        "id": "a9fad72fe99645a0853e75694f1c2d8a",
        "title": "Sane Reddit",
        "gender": "male",
        "sample_url": "",
    },
]


class FishUnavailable(Exception):
    """Fish refused the request because payment, quota, or the service is down."""


class FishAuthMissing(Exception):
    """FISH_API_KEY is not set in the project .env file."""


class FishAuthInvalid(Exception):
    """FISH_API_KEY was rejected by Fish Audio."""


def _reload_env() -> None:
    load_dotenv(ENV_PATH, override=True)


def fish_api_key() -> str:
    _reload_env()
    key = os.getenv("FISH_API_KEY", "").strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in ('"', "'"):
        key = key[1:-1].strip()
    if not key:
        raise FishAuthMissing(
            "Add FISH_API_KEY to the project .env file. "
            "Create one at https://fish.audio/app/api-keys"
        )
    return key


def _fish_error_is_unavailable(status: int, body: str) -> bool:
    if status in (400, 401, 404, 422):
        return False
    if status in (402, 429, 500, 502, 503, 504):
        return True
    lowered = body.lower()
    markers = (
        "payment",
        "quota",
        "credit",
        "insufficient",
        "billing",
        "subscribe",
        "subscription",
        "fair use",
        "rate limit",
        "unavailable",
    )
    return any(marker in lowered for marker in markers)


def _cache_paths(provider: str, text: str, voice_id: str, speed: float):
    payload = f"{provider}\n{voice_id}\n{float(speed):.2f}\n{text}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return (
        NARRATION_CACHE_DIR / f"{digest}.mp3",
        NARRATION_CACHE_DIR / f"{digest}.json",
    )


def _read_narration_cache(provider: str, text: str, voice_id: str, speed: float):
    audio_path, timings_path = _cache_paths(provider, text, voice_id, speed)
    if not audio_path.is_file() or not timings_path.is_file():
        return None
    try:
        timings = json.loads(timings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(timings, list):
        return None
    return audio_path.read_bytes(), timings


def _write_narration_cache(
    provider: str,
    text: str,
    voice_id: str,
    speed: float,
    audio_bytes: bytes,
    word_timings: list[dict],
):
    audio_path, timings_path = _cache_paths(provider, text, voice_id, speed)
    NARRATION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(audio_bytes)
    timings_path.write_text(
        json.dumps(word_timings),
        encoding="utf-8",
    )


def _curated_fish_voices() -> list[dict]:
    return [dict(voice) for voice in CURATED_REDDIT_FISH_VOICES]


@st.cache_data(ttl=300, show_spinner=False)
def get_fish_voices():
    """Curated Reddit narrators."""
    voices = _curated_fish_voices()
    try:
        fish_api_key()
    except FishAuthMissing:
        return {
            "voices": voices,
            "missing_key": True,
            "invalid_key": False,
        }

    return {
        "voices": voices,
        "missing_key": False,
        "invalid_key": False,
    }


def _parse_fish_sse(response) -> tuple[bytes, list[dict]]:
    audio_chunks = []
    alignment_by_chunk = {}

    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("error"):
            message = event["error"]
            if isinstance(message, dict):
                message = message.get("message") or json.dumps(message)
            message = str(message)
            if _fish_error_is_unavailable(response.status_code, message):
                raise FishUnavailable(message)
            raise RuntimeError(message)

        audio_b64 = event.get("audio_base64")
        if audio_b64:
            audio_chunks.append(base64.b64decode(audio_b64))

        alignment = event.get("alignment")
        if alignment:
            alignment_by_chunk[event.get("chunk_seq", 0)] = {
                "offset": float(event.get("chunk_audio_offset_sec") or 0),
                "alignment": alignment,
            }

    if not audio_chunks:
        raise RuntimeError("Fish Audio returned no audio.")

    word_timings = []
    for chunk_seq in sorted(alignment_by_chunk):
        item = alignment_by_chunk[chunk_seq]
        offset = item["offset"]
        for segment in item["alignment"].get("segments") or []:
            word = str(segment.get("text") or "").strip()
            if not word:
                continue
            start = float(segment.get("start") or 0) + offset
            end = float(segment.get("end") or 0) + offset
            word_timings.append({"text": word, "start": start, "end": end})

    return b"".join(audio_chunks), word_timings


def generate_fish_narration_audio_with_words(text, voice_id, speed):
    cached = _read_narration_cache("fish", text, voice_id, speed)
    if cached:
        return cached

    try:
        response_context = requests.post(
            FISH_TTS_URL,
            headers={
                "Authorization": f"Bearer {fish_api_key()}",
                "Content-Type": "application/json",
                "model": FISH_MODEL,
            },
            json={
                "text": text,
                "reference_id": voice_id,
                "format": "mp3",
                "language": "en",
                "latency": "balanced",
                "prosody": {"speed": float(speed)},
            },
            stream=True,
            timeout=180,
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise FishUnavailable(str(exc)) from exc

    with response_context as response:
        if response.status_code != 200:
            body = response.content.decode("utf-8", errors="replace")[:800]
            if _fish_error_is_unavailable(response.status_code, body):
                raise FishUnavailable(
                    body or f"Fish Audio returned HTTP {response.status_code}."
                )
            raise RuntimeError(
                f"Fish Audio returned HTTP {response.status_code}: {body}"
            )
        audio_bytes, word_timings = _parse_fish_sse(response)

    _write_narration_cache("fish", text, voice_id, speed, audio_bytes, word_timings)
    return audio_bytes, word_timings


def _word_boundary_to_seconds(offset: float, duration: float) -> tuple[float, float]:
    # Edge TTS reports offset/duration in 100-nanosecond units.
    start = offset / 10_000_000
    end = (offset + duration) / 10_000_000
    return start, end


def edge_voice_for(voice: dict, voice_type: str) -> str:
    gender = (voice.get("gender") or "").lower()
    if gender not in EDGE_FALLBACK_VOICES:
        gender = "female" if voice_type.lower() == "female" else "male"
    return EDGE_FALLBACK_VOICES[gender]


def generate_edge_narration_audio_with_words(text, voice_name, speed):
    cached = _read_narration_cache("edge", text, voice_name, speed)
    if cached:
        return cached

    path = None

    try:
        rate_percent = round((float(speed) - 1.0) * 100)
        rate = f"{rate_percent:+d}%"
        word_timings: list[dict] = []

        with tempfile.NamedTemporaryFile(
            suffix=".mp3",
            delete=False,
        ) as temp:
            path = temp.name

        async def generate():
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice_name,
                rate=rate,
                boundary="WordBoundary",
            )
            with open(path, "wb") as audio_file:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_file.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        word = (chunk.get("text") or "").strip()
                        if not word:
                            continue
                        start, end = _word_boundary_to_seconds(
                            chunk["offset"],
                            chunk["duration"],
                        )
                        word_timings.append(
                            {"text": word, "start": start, "end": end}
                        )

        asyncio.run(generate())

        with open(path, "rb") as audio_file:
            audio_bytes = audio_file.read()

    finally:
        if path and os.path.exists(path):
            os.remove(path)

    _write_narration_cache("edge", text, voice_name, speed, audio_bytes, word_timings)
    return audio_bytes, word_timings


def narrate_sections(
    sections: list[str],
    fish_voice_id: str,
    speed: float,
    edge_voice_name: str,
    skip_fish: bool = False,
):
    """Speak each section with Fish, or the free Edge voice if Fish cannot."""
    note = (
        "Fish Audio needs payment or is unavailable, so this used the free "
        f"backup voice ({edge_voice_name})."
    )
    if not skip_fish:
        try:
            spoken = [
                generate_fish_narration_audio_with_words(section, fish_voice_id, speed)
                for section in sections
            ]
            return spoken, False, ""
        except FishUnavailable:
            pass

    spoken = [
        generate_edge_narration_audio_with_words(section, edge_voice_name, speed)
        for section in sections
    ]
    return spoken, True, note


def _ffprobe_path() -> str:
    ffmpeg_path = Path(os.getenv("FFMPEG_PATH", ""))
    if not ffmpeg_path.is_file():
        raise RuntimeError("FFMPEG_PATH is missing or invalid in the project .env file.")
    probe_name = "ffprobe.exe" if ffmpeg_path.suffix.lower() == ".exe" else "ffprobe"
    probe_path = ffmpeg_path.with_name(probe_name)
    if not probe_path.is_file():
        raise RuntimeError(f"ffprobe was not found next to FFmpeg at: {probe_path}")
    return str(probe_path)


def probe_mp3_duration_seconds(mp3_bytes: bytes) -> float:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp:
        temp.write(mp3_bytes)
        temp_path = temp.name

    try:
        command = [
            _ffprobe_path(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            temp_path,
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("Could not read MP3 duration.")
        payload = json.loads(result.stdout)
        return float(payload["format"]["duration"])
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def concat_mp3_bytes(first_bytes: bytes, second_bytes: bytes) -> bytes:
    ffmpeg_path = os.getenv("FFMPEG_PATH")
    if not ffmpeg_path or not os.path.isfile(ffmpeg_path):
        raise RuntimeError("FFMPEG_PATH is missing or invalid in the project .env file.")

    work_dir = Path(tempfile.mkdtemp())
    first_path = work_dir / "part1.mp3"
    second_path = work_dir / "part2.mp3"
    concat_list = work_dir / "concat.txt"
    output_path = work_dir / "combined.mp3"

    try:
        first_path.write_bytes(first_bytes)
        second_path.write_bytes(second_bytes)
        concat_list.write_text(
            f"file '{first_path.as_posix()}'\nfile '{second_path.as_posix()}'\n",
            encoding="utf-8",
        )
        command = [
            ffmpeg_path,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(output_path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("Could not merge title and script narration audio.")
        return output_path.read_bytes()
    finally:
        for path in (first_path, second_path, concat_list, output_path):
            if path.exists():
                path.unlink()
        if work_dir.exists():
            work_dir.rmdir()


# ---------------------------------------------------------
# Header
# ---------------------------------------------------------
header_left, header_right = st.columns([4, 1])

with header_left:
    st.markdown(
        """
        <div class="project-header">
            <div class="project-name">🎬 ShortCraft AI</div>
            <div class="muted">
                Turn Reddit stories into narrated vertical videos
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with header_right:
    st.write("")
    st.caption("LOCAL PROJECT")
    st.markdown("🟢 Backend configured")


# ---------------------------------------------------------
# Editing stages
# ---------------------------------------------------------
st.markdown(
    """
    <div class="stage-bar">
        <div class="stage active">1 · Script</div>
        <div class="stage">2 · Voice</div>
        <div class="stage">3 · Background</div>
        <div class="stage">4 · Captions</div>
        <div class="stage">5 · Music</div>
        <div class="stage">6 · Export</div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# Main workspace
# ---------------------------------------------------------
target_duration = st.selectbox(
    "Target duration",
    ["30 seconds", "45 seconds", "60 seconds"],
    index=1,
    key="target_duration",
)
editor_col, preview_col = st.columns([1.35, 0.85], gap="large")


with editor_col:
    st.markdown(
        '<div class="section-heading">Your story</div>',
        unsafe_allow_html=True,
    )

    input_method = st.radio(
        "Import story",
        ["Paste text", "Reddit URL"],
        horizontal=True,
        key="input_method",
    )

    if input_method == "Paste text":
        story_text = st.text_area(
            "Reddit post or story",
            height=130,
            placeholder="Paste your Reddit story here...",
            key="story_text",
        )
    else:
        reddit_url = st.text_input(
            "Reddit post URL",
            placeholder="https://www.reddit.com/r/...",
            key="reddit_url",
        )
        story_text = ""
        st.caption(
            "Reddit URL retrieval will be connected after we confirm API access."
        )

    action1, action2, action3 = st.columns(3)

    with action1:
        if st.button("＋ Add story", use_container_width=True):
            st.session_state["show_extra_story"] = True

    
    with action2:
        if st.button(
            "✦ Generate AI script",
            type="primary",
            use_container_width=True,
        ):
            if not story_text.strip():
                if input_method == "Reddit URL":
                    st.info(
                        "Reddit retrieval is not implemented yet. "
                        "Paste the story text for now."
                    )
                else:
                    st.warning("Paste a story first.")
            else:
                try:
                    with st.spinner("Generating your narration script..."):
                        response = requests.post(
                            "http://127.0.0.1:8000/api/v1/story/generate-script",
                            json={
                                "text": story_text.strip(),
                                "target_duration": int(
                                    st.session_state["target_duration"].split()[0]
                                ),
                                "style": "engaging",
                            },
                            timeout=120,
                        )
                        response.raise_for_status()
                        result = response.json()

                    st.session_state["script"] = result["script"]
                    st.session_state["script_editor"] = result["script"]

                    st.toast(
                        "AI narration generated successfully! "
                        f'{result["script_word_count"]} words · '
                        f'Approximately {result["estimated_script_seconds"]} seconds',
                        icon="✅",
                    )

                except requests.RequestException as exc:
                    st.error("Could not generate the AI script.")
                    if exc.response is not None:
                        try:
                            st.error(exc.response.json().get("detail", str(exc)))
                        except ValueError:
                            st.error(str(exc))
                    else:
                        st.error(str(exc))


    with action3:
        st.button("Clear", use_container_width=True, on_click=clear_story)



    st.markdown("---")
    st.markdown(
        '<div class="section-heading">Narration script</div>',
        unsafe_allow_html=True,
    )

    # Keep the script editor in sync when Prepare script is clicked.
    if "script" in st.session_state and st.session_state.get(
        "script_editor"
    ) != st.session_state["script"]:
        st.session_state["script_editor"] = st.session_state["script"]

    script = st.text_area(
        "Edit the narration before generating your video",
        height=200,
        key="script_editor",
        placeholder="Your narration script will appear here...",
    )

    st.caption(f"{len(script.split())} words · Editable narration")

    # ---------------------------------------------------------
    # Reddit introduction card
    # ---------------------------------------------------------
    st.markdown("---")
    st.markdown(
        '<div class="section-heading">Reddit introduction card</div>',
        unsafe_allow_html=True,
    )

    st.caption(
        "Customize the card shown before the narration starts."
    )

    has_card = bool(st.session_state.get("reddit_card_image"))

    with st.expander(
        "Customize Reddit intro card",
        expanded=not has_card,
    ):
        card_username = st.text_input(
            "Display handle",
            value="Storybud01",
            placeholder="@YourHandle",
            key="card_username",
        )

        card_avatar = st.file_uploader(
            "Profile picture (optional)",
            type=["png", "jpg", "jpeg", "webp"],
            key="card_avatar",
        )
        st.caption(
            "Leave empty for a generated avatar from your handle."
        )

        card_title = st.text_area(
            "Reddit post title",
            placeholder="Enter the heading shown on the card...",
            height=90,
            key="card_title",
        )

        card_subreddit = st.text_input(
            "Subreddit",
            value="r/AmItheAsshole",
            key="card_subreddit",
        )

        card_verified = st.checkbox(
            "Show verification badge",
            value=False,
            key="card_verified",
        )

        card_col1, card_col2 = st.columns(2)

        with card_col1:
            card_upvotes = st.text_input(
                "Upvotes",
                value="99+",
                key="card_upvotes",
            )

        with card_col2:
            card_comments = st.text_input(
                "Comments",
                value="99+",
                key="card_comments",
            )

        if st.button(
            "Generate Reddit Card",
            use_container_width=True,
            key="generate_reddit_card",
        ):
            if not card_title.strip():
                st.warning("Please enter the Reddit post title.")
            else:
                try:
                    with st.spinner("Rendering Reddit card..."):
                        payload = {
                            "username": card_username.strip(),
                            "title": card_title.strip(),
                            "subreddit": card_subreddit.strip(),
                            "verified": card_verified,
                            "upvotes": card_upvotes.strip(),
                            "comments": card_comments.strip(),
                        }
                        if card_avatar is not None:
                            payload["avatar_base64"] = base64.b64encode(
                                card_avatar.getvalue()
                            ).decode("ascii")

                        response = requests.post(
                            "http://127.0.0.1:8000/api/v1/card/render",
                            json=payload,
                            timeout=30,
                        )

                        response.raise_for_status()

                        st.session_state["reddit_card_image"] = (
                            response.content
                        )
                        st.session_state["reddit_card_summary"] = {
                            "username": card_username.strip(),
                            "title": card_title.strip(),
                            "subreddit": card_subreddit.strip(),
                        }

                    st.toast(
                        "Reddit card generated successfully!",
                        icon="✅",
                    )

                except requests.RequestException as exc:
                    st.error("Could not generate Reddit card.")

                    if exc.response is not None:
                        st.error(exc.response.text)
                    else:
                        st.error(str(exc))

        if st.session_state.get("reddit_card_image"):
            st.markdown("#### Card preview")

            st.image(
                st.session_state["reddit_card_image"],
                width=330,
            )

    if st.session_state.get("reddit_card_image"):
        summary = st.session_state.get("reddit_card_summary") or {}
        username = summary.get(
            "username",
            st.session_state.get("card_username", "Storybud01"),
        )
        subreddit = summary.get(
            "subreddit",
            st.session_state.get("card_subreddit", ""),
        )
        title = summary.get("title", st.session_state.get("card_title", ""))
        title_short = title if len(title) <= 60 else f"{title[:57]}..."

        #st.caption("Intro card ready")
        #st.caption(
        #    f"u/{username} · {subreddit} · {title_short}"
        #)

        card_dl_col, _ = st.columns([1, 1])
        with card_dl_col:
            st.download_button(
                "Download Reddit Card",
                data=st.session_state["reddit_card_image"],
                file_name="shortcraft_reddit_card.png",
                mime="image/png",
                use_container_width=True,
            )

    st.markdown("---")
    st.markdown(
        '<div class="section-heading">Background footage</div>',
        unsafe_allow_html=True,
    )

    if "background_video_uploader_key" not in st.session_state:
        st.session_state.background_video_uploader_key = 0

    if st.session_state.pop("clear_video", False):
        st.session_state.background_video_uploader_key += 1
        for key in (
            "background_video_name",
            "background_video_bytes",
            "background_video_type",
        ):
            st.session_state.pop(key, None)

    uploaded_video = st.file_uploader(
        "Upload your background video",
        type=["mp4", "mov", "webm"],
        help="Use a video you own or have permission to use.",
        key=f"background_video_{st.session_state.background_video_uploader_key}",
    )

    if uploaded_video is not None:
        video_bytes = uploaded_video.getvalue()
        if video_bytes:
            st.session_state["background_video_name"] = uploaded_video.name
            st.session_state["background_video_bytes"] = video_bytes
            mime = uploaded_video.type or "video/mp4"
            if uploaded_video.name.lower().endswith(".webm") and mime == "application/octet-stream":
                mime = "video/webm"
            st.session_state["background_video_type"] = mime

        st.caption(
            f"{uploaded_video.name} · "
            f"{uploaded_video.size / (1024 * 1024):.1f} MB"
        )
        st.caption(
            "Your footage is shown in the fixed-size preview panel on the right."
        )


with preview_col:
    st.markdown(
        '<div class="section-heading">Video preview</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="preview-shell">', unsafe_allow_html=True)

    if uploaded_video is not None:
        # Use the same preview panel for uploaded footage; don't show a
        # second, oversized video under Background footage.
        st.video(uploaded_video)
    else:
        st.markdown(
            """
            <div class="preview-screen">
                <div style="font-size:42px;">▶</div>
                <div style="font-size:18px;font-weight:700;margin-top:14px;">
                    Your Short preview
                </div>
                <div class="preview-placeholder">
                    Upload background footage<br>
                    Add your story and narration<br>
                    Generate a video to preview it here
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(
        '<div class="section-heading">Narrator settings</div>',
        unsafe_allow_html=True,
    )

    speed = st.select_slider(
        "Narration speed",
        options=[0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0],
        value=1.0,
        format_func=lambda value: f"{value:g}×",
    )

    

    # Collapsible voice controls: no reload button or persistent open section.
    with st.expander("🎙️ Voice settings", expanded=False):
        voice_type = st.selectbox(
            "Voice type",
            ["All", "Female", "Male"],
            key="voice_type",
        )

        voices = _curated_fish_voices()
        fish_list_unavailable = False
        voice_load = {
            "missing_key": False,
            "invalid_key": False,
        }
        try:
            with st.spinner("Loading Fish Audio voices..."):
                voice_load = get_fish_voices()
                voices = voice_load["voices"]
        except FishAuthInvalid as exc:
            st.warning(str(exc))
        except FishUnavailable as exc:
            fish_list_unavailable = True
            st.info(
                "Fish Audio needs payment or is unavailable. "
                "You can still generate with a free backup voice."
            )
            st.caption(str(exc))
            voices = [
                {
                    "id": "",
                    "title": "Free backup",
                    "gender": "female",
                    "sample_url": "",
                    "backup_only": True,
                },
                {
                    "id": "",
                    "title": "Free backup",
                    "gender": "male",
                    "sample_url": "",
                    "backup_only": True,
                },
            ]
        except Exception as exc:
            st.caption(f"Could not verify Fish Audio: {exc}")

        if voice_load.get("missing_key"):
            st.info(
                "Add FISH_API_KEY to the project .env file to use Fish narrators. "
                "Create one at https://fish.audio/app/api-keys"
            )

        st.session_state["fish_list_unavailable"] = fish_list_unavailable
        st.session_state["fish_key_missing"] = voice_load.get("missing_key", False)
        st.session_state["fish_voices_available"] = (
            bool(voices)
            and not fish_list_unavailable
            and not voice_load.get("missing_key")
        )

        filtered_voices = voices
        if voice_type != "All":
            filtered_voices = [
                voice
                for voice in voices
                if voice.get("gender", "").lower() == voice_type.lower()
            ]

        if filtered_voices:
            def voice_label(voice):
                gender = (voice.get("gender") or "unknown").capitalize()
                return f'{voice.get("title", "Untitled")} · {gender}'

            selected_voice = st.selectbox(
                "Choose narrator",
                filtered_voices,
                format_func=voice_label,
                key="selected_backup_voice" if fish_list_unavailable else "selected_fish_voice",
            )

            preview_btn_col, _ = st.columns([1, 1])
            with preview_btn_col:
                if st.button("▶ Preview voice", use_container_width=True):
                    try:
                        with st.spinner("Generating voice sample..."):
                            spoken, _used_fallback, note = narrate_sections(
                                ["Welcome to ShortCraft AI."],
                                selected_voice.get("id") or "",
                                speed,
                                edge_voice_for(selected_voice, voice_type),
                                skip_fish=bool(selected_voice.get("backup_only")),
                            )
                        if note:
                            st.info(note)
                        st.audio(spoken[0][0], format="audio/mp3")
                    except Exception as exc:
                        st.error("Voice sample generation failed.")
                        st.caption(str(exc))
        elif voices:
            st.warning("No Fish Audio voices match this voice type.")

    st.markdown("---")
    st.markdown(
        '<div class="section-heading">Narration audio</div>',
        unsafe_allow_html=True,
    )

    gen_col, _ = st.columns([1, 1])
    with gen_col:
        if st.button(
            "Generate narration audio",
            use_container_width=True,
            type="primary",
        ):
            script_text = st.session_state.get("script_editor", "").strip()
            if st.session_state.get("fish_list_unavailable"):
                selected_voice = st.session_state.get("selected_backup_voice")
            else:
                selected_voice = st.session_state.get("selected_fish_voice")

            if not script_text:
                st.toast(
                    "Generate or enter a script before creating narration."
                )
            elif not selected_voice or (
                not selected_voice.get("id") and not selected_voice.get("backup_only")
            ):
                st.toast(
                    "Please open Voice settings and select a voice first."
                )
            else:
                try:
                    summary = st.session_state.get("reddit_card_summary") or {}
                    card_title = summary.get(
                        "title",
                        st.session_state.get("card_title", ""),
                    ).strip()
                    sections = [script_text]
                    if card_title:
                        sections = [card_title, script_text]

                    with st.spinner("Generating narration audio..."):
                        spoken, _used_fallback, note = narrate_sections(
                            sections,
                            selected_voice.get("id") or "",
                            speed,
                            edge_voice_for(
                                selected_voice,
                                st.session_state.get("voice_type", "All"),
                            ),
                            skip_fish=bool(selected_voice.get("backup_only")),
                        )

                        if card_title:
                            title_bytes, title_words = spoken[0]
                            script_bytes, script_words = spoken[1]
                            title_duration = probe_mp3_duration_seconds(title_bytes)
                            audio_bytes = concat_mp3_bytes(
                                title_bytes,
                                script_bytes,
                            )
                            for word in script_words:
                                word["start"] += title_duration
                                word["end"] += title_duration
                            caption_word_timings = title_words + script_words
                        else:
                            title_duration = 0.0
                            audio_bytes, caption_word_timings = spoken[0]

                    st.session_state["narration_audio"] = audio_bytes
                    st.session_state["narration_script"] = script_text
                    st.session_state["title_audio_duration"] = title_duration
                    st.session_state["caption_word_timings"] = caption_word_timings
                    st.session_state["narration_voice_note"] = note

                    st.toast(
                        note or "Narration audio generated successfully.",
                        icon="✅",
                    )

                except Exception as e:
                    st.error(f"Could not generate narration: {e}")

    if st.session_state.get("narration_voice_note"):
        st.info(st.session_state["narration_voice_note"])

    if st.session_state.get("narration_audio"):
        st.audio(
            st.session_state["narration_audio"],
            format="audio/mp3",
        )

        dl_col, _ = st.columns([1, 1])
        with dl_col:
            st.download_button(
                label="Download narration MP3",
                data=st.session_state["narration_audio"],
                file_name="shortcraft_narration.mp3",
                mime="audio/mpeg",
                use_container_width=True,
            )

    st.markdown("---")
    st.markdown('<div class="section-heading">Create your Short</div>', unsafe_allow_html=True)
    st.caption(
        "Gameplay runs from the first frame with the Reddit card on top. "
        "Narration speaks the card title first, then continues with your script."
    )

    intro_duration = st.selectbox(
        "Reddit intro duration",
        options=[2.0, 3.0, 4.0],
        index=1,
        format_func=lambda value: f"{value:g} seconds",
        key="intro_duration",
    )

    caption_style = st.selectbox(
        "Caption style",
        options=[
            "Classic Bold",
            "Highlighted Words",
            "Karaoke / Word-by-Word",
            "Sentence Captions",
            "Reddit Story Style",
        ],
        index=0,
        key="caption_style",
        help=(
            "Classic Bold burns centered word-by-word captions synced to your "
            "narration. Regenerate narration after script changes."
        ),
    )
    if caption_style != "Classic Bold":
        st.caption("Only Classic Bold captions are rendered in this export.")

    if st.button("Generate Short", type="primary", use_container_width=True, key="generate_short"):
        narration_bytes = st.session_state.get("narration_audio")
        card_bytes = st.session_state.get("reddit_card_image")
        background_bytes = st.session_state.get("background_video_bytes")
        background_name = st.session_state.get(
            "background_video_name",
            "background.mp4",
        )
        background_type = st.session_state.get(
            "background_video_type",
            "video/mp4",
        )

        if not background_bytes:
            st.warning("Upload background footage first.")
        elif not narration_bytes:
            st.warning("Generate narration audio first.")
        elif not card_bytes:
            st.warning("Generate the Reddit introduction card first.")
        else:
            try:
                with st.spinner("Composing your video. Longer narration takes longer to render..."):
                    response = requests.post(
                        "http://127.0.0.1:8000/api/v1/video/compose-with-card",
                        files={
                            "background_video": (
                                background_name,
                                background_bytes,
                                background_type,
                            ),
                            "narration_audio": (
                                "narration.mp3", narration_bytes, "audio/mpeg"
                            ),
                            "card_image": (
                                "reddit_card.png", card_bytes, "image/png"
                            ),
                        },
                        data={
                            "card_duration": str(intro_duration),
                            "caption_style": st.session_state.get(
                                "caption_style",
                                "Classic Bold",
                            ),
                            "caption_script": st.session_state.get(
                                "narration_script",
                                "",
                            ),
                            "title_audio_duration": str(
                                st.session_state.get("title_audio_duration", 0.0)
                            ),
                            "caption_word_timings": json.dumps(
                                st.session_state.get("caption_word_timings", [])
                            ),
                        },
                        timeout=3600,
                    )
                    response.raise_for_status()
                    st.session_state["generated_video"] = response.content
                    st.toast("Video created successfully.", icon="✅")
            except requests.RequestException as exc:
                st.error("Could not compose the video.")
                if exc.response is not None:
                    try:
                        payload = exc.response.json()
                        st.error(format_api_error_detail(payload.get("detail", payload)))
                    except ValueError:
                        st.error(exc.response.text)
                else:
                    st.error(str(exc))

    if st.session_state.get("generated_video"):
        st.markdown("#### Generated video")
        st.video(st.session_state["generated_video"])
        st.download_button(
            "Download finished MP4",
            data=st.session_state["generated_video"],
            file_name="shortcraft_video.mp4",
            mime="video/mp4",
            use_container_width=True,
        )
