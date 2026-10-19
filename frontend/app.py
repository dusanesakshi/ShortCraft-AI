import asyncio
import os
import tempfile
import requests
import edge_tts
import streamlit as st


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


@st.cache_data(ttl=3600, show_spinner=False)
def get_voices():
    """Retrieve and cache the available Edge TTS voices."""
    return asyncio.run(edge_tts.list_voices())


def generate_voice_sample(text, voice_name):
    """Generate a temporary MP3 sample and return its bytes."""
    path = None

    try:
        # Convert the selected speed into an Edge TTS rate adjustment.
        rate_percent = round((speed - 1.0) * 100)
        rate = f"{rate_percent:+d}%"

        with tempfile.NamedTemporaryFile(
            suffix=".mp3",
            delete=False
        ) as temp:
            path = temp.name

        async def generate():
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice_name,
                rate=rate
            )
            await communicate.save(path)

        asyncio.run(generate())

        with open(path, "rb") as audio_file:
            return audio_file.read()

    finally:
        if path and os.path.exists(path):
            os.remove(path)

def generate_narration_audio(text, voice_name, speed):
    path = None

    try:
        rate_percent = round((speed - 1.0) * 100)
        rate = f"{rate_percent:+d}%"

        with tempfile.NamedTemporaryFile(
            suffix=".mp3",
            delete=False
        ) as temp:
            path = temp.name

        async def generate():
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice_name,
                rate=rate
            )
            await communicate.save(path)

        asyncio.run(generate())

        with open(path, "rb") as audio_file:
            return audio_file.read()

    finally:
        if path and os.path.exists(path):
            os.remove(path)
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

    st.markdown("---")
    st.markdown(
        '<div class="section-heading">Background footage</div>',
        unsafe_allow_html=True,
    )
    if "background_video_uploader_key" not in st.session_state:
        st.session_state.background_video_uploader_key = 0

    if st.session_state.pop("clear_video", False):
        st.session_state.background_video_uploader_key += 1

    uploaded_video = st.file_uploader(
        "Upload your background video",
        type=["mp4", "mov", "webm"],
        help="Use a video you own or have permission to use.",
        key=f"background_video_{st.session_state.background_video_uploader_key}",
    )

    if uploaded_video is not None:
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
        try:
            with st.spinner("Loading online voices..."):
                voices = get_voices()

            english_voices = [
                voice
                for voice in voices
                if voice.get("Locale", "").startswith("en-")
            ]

            voice_type = st.selectbox(
                "Voice type",
                ["All", "Female", "Male"],
                key="voice_type",
            )

            locale_options = sorted(
                {voice["Locale"] for voice in english_voices}
            )
            selected_locale = st.selectbox(
                "Accent / locale",
                ["All"] + locale_options,
                key="voice_locale",
            )

            filtered_voices = english_voices

            if voice_type != "All":
                filtered_voices = [
                    voice
                    for voice in filtered_voices
                    if voice.get("Gender", "").lower()
                    == voice_type.lower()
                ]

            if selected_locale != "All":
                filtered_voices = [
                    voice
                    for voice in filtered_voices
                    if voice.get("Locale") == selected_locale
                ]

            if filtered_voices:
                def voice_label(voice):
                    return (
                        f'{voice.get("ShortName", "Unknown")} · '
                        f'{voice.get("Gender", "Unknown")} · '
                        f'{voice.get("Locale", "Unknown")}'
                    )

                selected_voice = st.selectbox(
                    "Choose narrator",
                    filtered_voices,
                    format_func=voice_label,
                    key="selected_voice",
                )

                sample_text = st.text_input(
                    "Voice sample",
                    value="Hi! Welcome to ShortCraft AI.",
                    key="voice_sample_text",
                )

                preview_btn_col, _ = st.columns([1, 1])
                with preview_btn_col:
                    if st.button("▶ Preview voice", use_container_width=True):
                        if not sample_text.strip():
                            st.warning("Enter sample text.")
                        else:
                            try:
                                with st.spinner("Generating voice sample..."):
                                    audio_bytes = generate_voice_sample(
                                        sample_text,
                                        selected_voice["ShortName"],
                                    )
                                st.audio(audio_bytes, format="audio/mp3")
                            except Exception as exc:
                                st.error("Voice sample generation failed.")
                                st.caption(str(exc))
            else:
                st.warning("No voices match these filters.")

        except Exception as exc:
            st.error("Could not load online voices.")
            st.caption(str(exc))

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
            selected_voice = st.session_state.get("selected_voice")

            if not script_text:
                st.warning(
                    "Generate or enter a script before creating narration."
                )
            elif not selected_voice:
                st.warning(
                    "Please open Voice settings and select a voice first."
                )
            else:
                try:
                    with st.spinner("Generating narration audio..."):
                        audio_bytes = generate_narration_audio(
                            text=script_text,
                            voice_name=selected_voice["ShortName"],
                            speed=speed,
                        )

                    st.session_state["narration_audio"] = audio_bytes
                    st.session_state["narration_script"] = script_text

                    st.toast(
                        "Narration audio generated successfully.",
                        icon="✅",
                    )

                except Exception as e:
                    st.error(f"Could not generate narration: {e}")

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
    st.caption(
        "The source clip can be previewed here. "
        "Narration, captions, and MP4 export will be connected in the next phase."
    )
