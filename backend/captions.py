import re
from pathlib import Path


def split_script_sentences(text: str) -> list[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [part.strip() for part in parts if part.strip()]


def _format_ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def sentence_timings(
    sentences: list[str],
    start_offset: float,
    end_time: float,
) -> list[tuple[str, float, float]]:
    if not sentences or end_time <= start_offset:
        return []

    word_counts = [max(len(sentence.split()), 1) for sentence in sentences]
    total_words = sum(word_counts)
    window = end_time - start_offset
    timings: list[tuple[str, float, float]] = []
    cursor = start_offset

    for index, sentence in enumerate(sentences):
        if index == len(sentences) - 1:
            end = end_time
        else:
            share = word_counts[index] / total_words
            end = min(end_time, cursor + window * share)
        timings.append((sentence, cursor, end))
        cursor = end

    return timings


def _ass_header(
    *,
    play_res_x: int,
    play_res_y: int,
    font_size: int,
    alignment: int,
) -> str:
    return f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {play_res_x}
PlayResY: {play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ClassicBold,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,5,1,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_spoken_word_ass(
    word_timings: list[dict],
    *,
    total_audio_duration: float,
    output_path: Path,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
) -> Path:
    header = _ass_header(
        play_res_x=play_res_x,
        play_res_y=play_res_y,
        font_size=92,
        alignment=5,
    )
    lines = [header]
    max_end = max(0.0, total_audio_duration)

    for item in word_timings:
        text = str(item.get("text", "")).strip()
        if not text:
            continue

        try:
            start = float(item.get("start", 0.0))
            end = float(item.get("end", start))
        except (TypeError, ValueError):
            continue

        start = max(0.0, min(start, max_end))
        end = max(start + 0.05, min(end, max_end))
        if end <= start:
            continue

        lines.append(
            "Dialogue: 0,"
            f"{_format_ass_time(start)},"
            f"{_format_ass_time(end)},"
            "ClassicBold,,0,0,0,,"
            f"{_escape_ass_text(text)}\n"
        )

    output_path.write_text("".join(lines), encoding="utf-8-sig")
    return output_path


def build_classic_bold_ass(
    script_text: str,
    *,
    title_audio_duration: float,
    total_audio_duration: float,
    output_path: Path,
    word_timings: list[dict] | None = None,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
) -> Path:
    if word_timings:
        return build_spoken_word_ass(
            word_timings,
            total_audio_duration=total_audio_duration,
            output_path=output_path,
            play_res_x=play_res_x,
            play_res_y=play_res_y,
        )

    sentences = split_script_sentences(script_text)
    caption_start = max(0.0, title_audio_duration)
    caption_end = max(caption_start, total_audio_duration)
    events = sentence_timings(sentences, caption_start, caption_end)

    header = _ass_header(
        play_res_x=play_res_x,
        play_res_y=play_res_y,
        font_size=72,
        alignment=5,
    )

    lines = [header]
    for sentence, start, end in events:
        if end <= start:
            continue
        lines.append(
            "Dialogue: 0,"
            f"{_format_ass_time(start)},"
            f"{_format_ass_time(end)},"
            "ClassicBold,,0,0,0,,"
            f"{_escape_ass_text(sentence)}\n"
        )

    output_path.write_text("".join(lines), encoding="utf-8-sig")
    return output_path
