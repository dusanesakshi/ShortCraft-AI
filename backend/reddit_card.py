
import colorsys
import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


CARD_WIDTH = 900
CARD_PADDING = 36
CARD_RADIUS = 42
BACKGROUND_COLOR = (255, 255, 255, 255)
TEXT_COLOR = (25, 25, 25, 255)
MUTED_COLOR = (150, 150, 150, 255)
ACCENT_COLOR = (0, 190, 220, 255)

AVATAR_SIZE = 76
HEADER_TOP = 36
TITLE_FONT_SIZE = 39
TITLE_LINE_HEIGHT = 48
MAX_TITLE_LINES = 6
FOOTER_HEIGHT = 56
BOTTOM_PAD = 28


def load_font(size, bold=False):
    """Load a Windows font, with a Pillow default fallback."""
    candidates = []

    if bold:
        candidates.extend([
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
        ])
    else:
        candidates.extend([
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
        ])

    for font_path in candidates:
        if Path(font_path).exists():
            return ImageFont.truetype(font_path, size)

    return ImageFont.load_default()


def normalize_username_display(username):
    """Return display handle with a single @ prefix."""
    name = (username or "").strip() or "Anonymous"
    name = name.lstrip("@")
    return f"@{name}"


def wrap_text(draw, text, font, max_width):
    """Wrap text according to actual pixel width."""
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        candidate = f"{current_line} {word}".strip()

        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current_line = candidate
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def _avatar_color_from_username(username):
    """Deterministic accent color from username."""
    digest = hashlib.sha256(username.encode("utf-8")).hexdigest()
    hue = int(digest[:8], 16) % 360
    r, g, b = colorsys.hls_to_rgb(hue / 360.0, 0.45, 0.55)
    return (int(r * 255), int(g * 255), int(b * 255), 255)


def _avatar_initials(username):
    name = (username or "").strip().lstrip("@") or "A"
    parts = name.replace("_", " ").split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[0].upper()


def _center_crop_square(image):
    w, h = image.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return image.crop((left, top, left + side, top + side))


def paste_circular_avatar(card, x, y, size, image):
    """Paste a square image as a circle onto card."""
    square = _center_crop_square(image.convert("RGBA"))
    square = square.resize((size, size), Image.Resampling.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size, size), fill=255)

    card.paste(square, (int(x), int(y)), mask)


def draw_dynamic_avatar(card, x, y, size, username):
    """Letter avatar with hash-based background."""
    draw = ImageDraw.Draw(card)
    fill = _avatar_color_from_username(username)
    draw.ellipse((x, y, x + size, y + size), fill=fill)

    initials = _avatar_initials(username)
    font_size = 32 if len(initials) == 1 else 26
    font = load_font(font_size, bold=True)
    bbox = draw.textbbox((0, 0), initials, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = x + (size - tw) / 2
    ty = y + (size - th) / 2 - 2
    draw.text((tx, ty), initials, font=font, fill=(255, 255, 255, 255))


def draw_avatar(card, x, y, size, username, avatar_image=None):
    if avatar_image is not None:
        paste_circular_avatar(card, x, y, size, avatar_image)
    else:
        draw_dynamic_avatar(card, x, y, size, username)


def draw_verification_badge(draw, badge_x, badge_y, size=28):
    draw.ellipse(
        (badge_x, badge_y, badge_x + size, badge_y + size),
        fill=ACCENT_COLOR,
    )
    draw.line(
        (
            badge_x + 7,
            badge_y + 14,
            badge_x + 12,
            badge_y + 19,
            badge_x + 21,
            badge_y + 9,
        ),
        fill="white",
        width=4,
    )


def draw_upvote_icon(draw, x, y, color, scale=1.0):
    """Reddit-style upvote caret."""
    w = 22 * scale
    h = 14 * scale
    cx = x + w / 2
    draw.polygon(
        (
            (cx, y),
            (x + w, y + h),
            (x, y + h),
        ),
        fill=color,
    )


def draw_comment_icon(draw, x, y, color, scale=1.0):
    """Speech bubble outline with tail."""
    bw = 28 * scale
    bh = 22 * scale
    outline = max(2, int(2.5 * scale))
    draw.rounded_rectangle(
        (x, y, x + bw, y + bh),
        radius=int(6 * scale),
        outline=color,
        width=outline,
    )
    tail_y = y + bh - 2
    draw.polygon(
        (
            (x + 6 * scale, tail_y),
            (x + 2 * scale, tail_y + 10 * scale),
            (x + 14 * scale, tail_y),
        ),
        fill=color,
    )


def render_reddit_card(
    username,
    title,
    output_path="reddit_card.png",
    subreddit="",
    verified=True,
    upvotes="99+",
    comments="99+",
    avatar_image=None,
):
    """
    Render a Shorts-style Reddit introduction card.

    ``subreddit`` is accepted for API compatibility but not drawn on the card.
    ``avatar_image`` is an optional PIL Image for the profile picture.

    Returns the output PNG path.
    """
    del subreddit  # not shown on card face

    title = title.strip()
    raw_username = (username or "").strip() or "Anonymous"
    display_name = normalize_username_display(raw_username)

    if not title:
        raise ValueError("The post title cannot be empty.")

    measure = Image.new("RGBA", (CARD_WIDTH, 100), (0, 0, 0, 0))
    measure_draw = ImageDraw.Draw(measure)
    title_font = load_font(TITLE_FONT_SIZE, bold=True)
    max_text_width = CARD_WIDTH - CARD_PADDING * 2
    title_lines = wrap_text(measure_draw, title, title_font, max_text_width)
    visible_lines = min(len(title_lines), MAX_TITLE_LINES)
    if len(title_lines) > MAX_TITLE_LINES:
        visible_lines = MAX_TITLE_LINES

    header_bottom = HEADER_TOP + AVATAR_SIZE + 20
    title_top = header_bottom + 8
    title_block_height = visible_lines * TITLE_LINE_HEIGHT
    inner_height = (
        title_top + title_block_height + FOOTER_HEIGHT + BOTTOM_PAD
    )
    card_height = inner_height + 22

    card = Image.new("RGBA", (CARD_WIDTH, card_height), (0, 0, 0, 0))

    shadow = Image.new("RGBA", (CARD_WIDTH, card_height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (12, 14, CARD_WIDTH - 12, card_height - 14),
        radius=CARD_RADIUS,
        fill=(0, 0, 0, 40),
    )
    card.alpha_composite(shadow)

    draw = ImageDraw.Draw(card)
    card_body_bottom = card_height - 22
    draw.rounded_rectangle(
        (8, 8, CARD_WIDTH - 16, card_body_bottom),
        radius=CARD_RADIUS,
        fill=BACKGROUND_COLOR,
    )

    avatar_x = CARD_PADDING
    avatar_y = HEADER_TOP
    draw_avatar(
        card,
        avatar_x,
        avatar_y,
        AVATAR_SIZE,
        raw_username,
        avatar_image=avatar_image,
    )

    username_font = load_font(31, bold=True)
    username_x = avatar_x + AVATAR_SIZE + 18
    username_y = HEADER_TOP + 4

    draw.text(
        (username_x, username_y),
        display_name,
        font=username_font,
        fill=TEXT_COLOR,
    )

    username_width = draw.textbbox(
        (username_x, username_y),
        display_name,
        font=username_font,
    )[2] - username_x

    if verified:
        badge_x = min(username_x + username_width + 12, CARD_WIDTH - 70)
        badge_y = username_y + 7
        draw_verification_badge(draw, badge_x, badge_y)

    for index, line in enumerate(title_lines[:MAX_TITLE_LINES]):
        text = line
        if (
            index == MAX_TITLE_LINES - 1
            and len(title_lines) > MAX_TITLE_LINES
        ):
            text = line.rstrip(".") + "..."
        draw.text(
            (CARD_PADDING, title_top + index * TITLE_LINE_HEIGHT),
            text,
            font=title_font,
            fill=TEXT_COLOR,
        )

    engagement_y = card_body_bottom - FOOTER_HEIGHT + 8
    icon_color = MUTED_COLOR
    count_font = load_font(24)

    up_x = CARD_PADDING
    draw_upvote_icon(draw, up_x, engagement_y + 4, icon_color)
    draw.text(
        (up_x + 34, engagement_y + 8),
        upvotes,
        font=count_font,
        fill=icon_color,
    )

    comment_count_bbox = draw.textbbox((0, 0), comments, font=count_font)
    comment_text_w = comment_count_bbox[2] - comment_count_bbox[0]
    icon_w = 28
    gap = 10
    block_w = icon_w + gap + comment_text_w
    comment_block_x = CARD_WIDTH - CARD_PADDING - block_w

    draw_comment_icon(draw, comment_block_x, engagement_y + 6, icon_color)
    draw.text(
        (comment_block_x + icon_w + gap, engagement_y + 8),
        comments,
        font=count_font,
        fill=icon_color,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    card.save(output, "PNG")

    return str(output.resolve())


if __name__ == "__main__":
    path = render_reddit_card(
        username="LimaReadIt",
        title=(
            "I planted an empty ring box, and my sister-in-law "
            "told the whole family."
        ),
        verified=True,
    )
    print(f"Reddit card created: {path}")
