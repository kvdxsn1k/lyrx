#!/usr/bin/env python3
"""Spotify lyrics TUI — big text, time-synced, 1-2 words at a time."""

import argparse
import colorsys
import io
import subprocess
import sys
import time
import os
import re
from pathlib import Path
from urllib.request import urlopen

from PIL import Image, ImageDraw, ImageFont
import syncedlyrics

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "lyrx"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

FONT_PATH = str(Path(__file__).parent / "QuinqueFive.otf")
FONT_NATIVE = 5  # QuinqueFive is a 5px tall pixel font
MARGIN = 0.8  # use 80% of terminal width for text
MAX_LINE_DURATION = 8.0  # seconds — beyond this, show idle animation after chunks
SECS_PER_SYLLABLE = 0.45  # rough singing rate for timing chunks

# Number words for syllable counting
NUMBER_WORDS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    "10": "ten", "11": "eleven", "12": "twelve", "13": "thirteen",
    "14": "fourteen", "15": "fifteen", "16": "sixteen", "17": "seventeen",
    "18": "eighteen", "19": "nineteen", "20": "twenty", "30": "thirty",
    "40": "forty", "50": "fifty", "60": "sixty", "70": "seventy",
    "80": "eighty", "90": "ninety", "100": "onehundred",
    "1000": "onethousand",
}

IDLE_ANIMATIONS = {
    "wave": ["~", "~~", "~~~", "~~~~", "~~~", "~~"],
    "dots": [".", "..", "...", "....", "...", ".."],
    "bounce": [".","o","O","o","."],
    "dance": [
        r"""
   \o/
    |
   / \
""",
        r"""
    o/
   /|
   / \
""",
        r"""
    o
   /|\
   / \
""",
        r"""
   \o
    |\
   / \
""",
        r"""
   \o/
    |
   / \
""",
        r"""
   _o_
    |
   | |
""",
        r"""
    o
   -|-
   / \
""",
        r"""
   _o_
    |
   | |
""",
    ],
    "girl": [
        r"""
     /)/)
    ( ..)    ~
   /  づ♡  /
""",
        r"""
     /)/)
    (.. )  ~
   ♡づ  \   \
""",
        r"""
     /)/)
    ( ..)   ~
   c(  づ  |
""",
        r"""
     /)/)
    (.. ) ~
    づ  )つ |
""",
        r"""
     /)/)
    ( ..)  ♡
   /  づ  /
""",
        r"""
     /)/)
    (.. )♡
   づ  \   \
""",
    ],
    "cat": [
        r"""
  /\_/\
 ( o.o )
  > ^ <
 /|   |\
""",
        r"""
  /\_/\
 ( o.o )
  > ^ <
  |\ /|
""",
        r"""
  /\_/\
 ( -.- )
  > ^ <
 /|   |\
""",
        r"""
  /\_/\
 ( o.o )
  > ^ <~
  |/ \|
""",
    ],
    "music": [
        "♪",
        "♫",
        "♪♫",
        "♫♪",
        "♪♫♪",
        "♫♪♫",
        "♪♫",
        "♫",
    ],
}

COLOR_PRESETS = {
    "white": "ffffff",
    "red": "ff0000",
    "green": "00ff00",
    "blue": "0088ff",
    "yellow": "ffff00",
    "cyan": "00ffff",
    "magenta": "ff00ff",
    "orange": "ff8800",
    "pink": "ff66aa",
    "purple": "aa44ff",
    "spotify": "1db954",
}


def parse_color(color_str):
    """Return ANSI escape for a color name or hex value, or empty string."""
    if not color_str:
        return "", ""
    c = color_str.lower().strip("#")
    if c in COLOR_PRESETS:
        c = COLOR_PRESETS[c]
    if len(c) == 6:
        try:
            r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            return f"\033[38;2;{r};{g};{b}m", "\033[0m"
        except ValueError:
            pass
    return "", ""


def get_player_info():
    """Get current track info, position, and art URL from playerctl."""
    try:
        meta = subprocess.check_output(
            ["playerctl", "-p", "spotify", "metadata", "--format",
             "{{artist}}|||{{title}}|||{{mpris:artUrl}}"],
            text=True, stderr=subprocess.DEVNULL
        ).strip()
        pos_us = subprocess.check_output(
            ["playerctl", "-p", "spotify", "position"],
            text=True, stderr=subprocess.DEVNULL
        ).strip()
        artist, title, art_url = meta.split("|||")
        position_s = float(pos_us)
        return artist, title, position_s, art_url
    except (subprocess.CalledProcessError, ValueError):
        return None, None, 0.0, ""


def extract_cover_color(art_url):
    """Download album art and extract a vibrant dominant color, bright enough for dark bg."""
    try:
        data = urlopen(art_url, timeout=5).read()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        # Shrink and quantize to find dominant colors
        img = img.resize((80, 80))
        colors = img.quantize(colors=8, method=Image.Quantize.FASTOCTREE).convert("RGB")
        palette = colors.getcolors(maxcolors=8)
        if not palette:
            return None

        # Pick the most vibrant color that's bright enough
        best = None
        best_score = -1
        for count, (r, g, b) in palette:
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            # Skip very dark or very desaturated colors
            if v < 0.3 or s < 0.15:
                continue
            # Score: prefer saturated + bright + common
            score = s * v * (count ** 0.5)
            if score > best_score:
                best_score = score
                best = (r, g, b, h, s, v)

        if not best:
            # Fallback: just pick the brightest
            palette.sort(key=lambda x: sum(x[1]), reverse=True)
            r, g, b = palette[0][1]
            best = (r, g, b, *colorsys.rgb_to_hsv(r / 255, g / 255, b / 255))

        r, g, b, h, s, v = best

        # Boost brightness if too dark for terminal
        if v < 0.6:
            v = max(v, 0.6)
            s = min(s, 0.9)  # slight desaturate to keep it readable
            r, g, b = colorsys.hsv_to_rgb(h, s, v)
            r, g, b = int(r * 255), int(g * 255), int(b * 255)

        return f"\033[38;2;{r};{g};{b}m", "\033[0m"
    except Exception:
        return None


def parse_lrc(lrc_text):
    """Parse LRC format into list of (timestamp_s, text)."""
    lines = []
    for line in lrc_text.splitlines():
        m = re.match(r"\[(\d+):(\d+\.\d+)\]\s*(.*)", line)
        if m:
            ts = int(m.group(1)) * 60 + float(m.group(2))
            text = m.group(3).strip()
            if text:
                lines.append((ts, text))
    lines.sort(key=lambda x: x[0])
    return lines


def fetch_lyrics(artist, title):
    """Fetch synced lyrics, with file cache."""
    safe_name = re.sub(r'[^\w\s-]', '', f"{artist} - {title}").strip()
    cache_file = CACHE_DIR / f"{safe_name}.lrc"

    if cache_file.exists():
        return cache_file.read_text()

    lrc = syncedlyrics.search(f"{artist} {title}", synced_only=True)
    if lrc:
        cache_file.write_text(lrc)
    return lrc


def _count_syllables(word):
    """Estimate syllable count for a word (works for English and rough for Cyrillic)."""
    word = word.lower().strip("-',!?.\"")
    if not word:
        return 1
    # Expand numbers to words for better syllable estimation
    if word.isdigit():
        expanded = NUMBER_WORDS.get(word)
        if not expanded:
            # For multi-digit numbers, expand digit by digit as fallback
            expanded = "".join(NUMBER_WORDS.get(d, "one") for d in word)
        word = expanded
    # Count vowel groups (works for Latin and Cyrillic)
    vowels = re.findall(r'[aeiouyаеёиоуыэюя]+', word, re.IGNORECASE)
    count = len(vowels)
    # Silent trailing 'e' in English (love, make, come, etc.)
    if word.endswith("e") and count > 1 and not word.endswith(("ee", "ie", "ye")):
        count -= 1
    return max(1, count)


def _chunk_timings(chunks, total_duration):
    """Return list of (start, end) times for chunks, proportional to syllable count.
    If total_duration is too long, caps speech time and leaves a gap at the end."""
    syllables = []
    for chunk in chunks:
        count = sum(_count_syllables(w) for w in chunk.replace("-", " ").split())
        syllables.append(max(1, count))
    total_syl = sum(syllables)

    # Estimate how long the lyrics actually take to say
    speech_duration = min(total_duration, total_syl * SECS_PER_SYLLABLE + 1.0)
    # But at least give each chunk some time
    speech_duration = max(speech_duration, len(chunks) * 0.4)
    # Don't exceed the actual line duration
    speech_duration = min(speech_duration, total_duration)

    timings = []
    t = 0.0
    for syl in syllables:
        dur = speech_duration * (syl / total_syl)
        timings.append((t, t + dur))
        t += dur

    return timings, speech_duration


def _measure_text(text):
    """Return pixel width of text at native font size."""
    try:
        font = ImageFont.truetype(FONT_PATH, FONT_NATIVE)
    except OSError:
        font = ImageFont.load_default()
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def calc_scale_for_lyrics(lyrics, term_width):
    """Find a consistent integer scale based on typical word widths in the song.
    Uses MARGIN ratio to leave breathing room on the sides."""
    term_width = int(term_width * MARGIN)
    try:
        font = ImageFont.truetype(FONT_PATH, FONT_NATIVE)
    except OSError:
        font = ImageFont.load_default()

    widths = []
    for _, text in lyrics:
        for word in text.split():
            bbox = font.getbbox(word)
            widths.append(bbox[2] - bbox[0])

    if not widths:
        return 2

    # Size for ~90th percentile word width so most words look good
    widths.sort()
    idx = min(len(widths) - 1, int(len(widths) * 0.9))
    target_px = widths[idx]

    return max(2, term_width // target_px)


def split_into_chunks(text, term_width, scale):
    """Split a lyric line into chunks, greedily packing pieces that fit.
    Splits on spaces and hyphens."""
    # Split into pieces keeping hyphens attached: "yeah-yeah" -> ["yeah-", "yeah"]
    pieces = re.findall(r'[^\s-]+-?', text)
    if not pieces:
        return [text]
    max_px = term_width // scale
    chunks = []
    i = 0
    while i < len(pieces):
        chunk = pieces[i]
        j = i + 1
        while j < len(pieces):
            # Use no space if previous piece ends with hyphen
            sep = "" if chunk.endswith("-") else " "
            candidate = chunk + sep + pieces[j]
            if _measure_text(candidate) <= max_px:
                chunk = candidate
                j += 1
            else:
                break
        i = j
        chunks.append(chunk)
    return chunks


def render_big_text(text, scale, term_width):
    """Render text as big block characters, centered. Integer-scaled pixel font."""
    if not text:
        return ""

    try:
        font = ImageFont.truetype(FONT_PATH, FONT_NATIVE)
    except OSError:
        font = ImageFont.load_default()

    bbox = font.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    img = Image.new("1", (tw + 1, th + 1), 0)
    draw = ImageDraw.Draw(img)
    draw.text((-bbox[0], -bbox[1]), text, fill=1, font=font)

    # Shrink scale if text doesn't fit
    while tw * scale > term_width and scale > 1:
        scale -= 1

    pixels = img.load()
    total_px_h = th * scale
    if total_px_h % 2 != 0:
        total_px_h += 1

    # Hard clamp so nothing ever wraps
    text_width = min(tw * scale, term_width)
    pad = max(0, (term_width - text_width) // 2)
    prefix = " " * pad

    lines = []
    for py in range(0, total_px_h, 2):
        row = []
        for px in range(text_width):
            fx = px // scale
            fy_top = py // scale
            fy_bot = (py + 1) // scale
            top = pixels[fx, fy_top] if fx < tw and fy_top < th else 0
            bot = pixels[fx, fy_bot] if fx < tw and fy_bot < th else 0
            if top and bot:
                row.append("█")
            elif top:
                row.append("▀")
            elif bot:
                row.append("▄")
            else:
                row.append(" ")
        lines.append(prefix + "".join(row).rstrip())

    return "\n".join(lines)


def render_idle_frame(frame, is_ascii, scale, term_width):
    """Render an idle animation frame — either as ASCII art or through pixel font."""
    if is_ascii:
        lines = frame.strip("\n").split("\n")
        width = max(len(l) for l in lines)
        pad = max(0, (term_width - width) // 2)
        return "\n".join(" " * pad + l for l in lines)
    else:
        return render_big_text(frame, scale, term_width)


def get_current_line(lyrics, position):
    """Find the current lyric line index for the given position."""
    current_idx = None
    for i, (ts, text) in enumerate(lyrics):
        if ts <= position:
            current_idx = i
        else:
            break
    return current_idx


def main():
    parser = argparse.ArgumentParser(description="Spotify lyrics TUI")
    parser.add_argument(
        "--color", "-c",
        help=f"Text color: hex (ff0000), name ({', '.join(COLOR_PRESETS)}), or 'cover' for album art color",
        default="white",
    )
    parser.add_argument(
        "--offset", "-o", type=float, default=-0.4,
        help="Audio offset in seconds, negative = show lyrics earlier (default: -0.4)",
    )
    parser.add_argument(
        "--idle", "-i",
        choices=list(IDLE_ANIMATIONS.keys()),
        default="wave",
        help=f"Idle animation style (default: wave)",
    )
    args = parser.parse_args()
    use_cover_color = args.color.lower() == "cover"
    if use_cover_color:
        color_on, color_off = "", ""
    else:
        color_on, color_off = parse_color(args.color)
    audio_offset = args.offset
    idle_frames = IDLE_ANIMATIONS[args.idle]
    idle_is_ascii = isinstance(idle_frames[0], str) and "\n" in idle_frames[0]

    term_size = os.get_terminal_size()
    term_width = term_size.columns
    term_height = term_size.lines
    last_artist, last_title = None, None
    lyrics = None
    scale = 2
    last_chunk = None

    print("\033[?25l", end="")  # hide cursor
    print("\033[2J\033[H", end="")  # clear screen
    print("Waiting for Spotify...")

    while True:
        try:
            artist, title, position, art_url = get_player_info()
            position -= audio_offset  # negative offset = lyrics appear earlier

            if not artist:
                time.sleep(1)
                continue

            # Refetch lyrics if song changed
            if (artist, title) != (last_artist, last_title):
                last_artist, last_title = artist, title
                last_chunk = None
                print(f"\033[2J\033[H", end="")
                print(f"{artist} — {title}")
                print("  Fetching lyrics...")

                # Extract color from cover art
                if use_cover_color and art_url:
                    result = extract_cover_color(art_url)
                    if result:
                        color_on, color_off = result

                lrc = fetch_lyrics(artist, title)
                if lrc:
                    lyrics = parse_lrc(lrc)
                    term_size = os.get_terminal_size()
                    term_width = term_size.columns
                    term_height = term_size.lines
                    # Show song info centered while waiting for lyrics to start
                    header = f"♫ {artist} — {title}"
                    top_pad = max(0, (term_height - 2) // 2)
                    print("\033[2J\033[H", end="")
                    print("\n" * top_pad, end="")
                    print(f"\033[2m{header:^{term_width}}\033[0m")
                    sys.stdout.flush()
                    scale = calc_scale_for_lyrics(lyrics, term_width - 10)
                else:
                    lyrics = None
                    print("  No synced lyrics found")

            if not lyrics:
                time.sleep(1)
                continue

            line_idx = get_current_line(lyrics, position)
            if line_idx is None:
                # Before first lyric — show wave animation
                frame_idx = int(position * 2) % len(idle_frames)
                current_chunk = f"__idle_{frame_idx}"
                if current_chunk != last_chunk:
                    last_chunk = current_chunk
                    frame = idle_frames[frame_idx]
                    big = render_idle_frame(frame, idle_is_ascii, scale, term_width)
                    big_lines = big.split("\n")
                    big_height = len(big_lines)
                    header = f"♫ {artist} — {title}"
                    content_height = 3 + big_height
                    top_pad = max(0, (term_height - content_height) // 2)
                    print("\033[2J\033[H", end="")
                    print("\n" * top_pad, end="")
                    print(f"\033[2m{header:^{term_width}}\033[0m")
                    print()
                    print(f"{color_on}{big}{color_off}")
                    sys.stdout.flush()
                time.sleep(0.05)
                continue

            line_start, line_text = lyrics[line_idx]
            line_end = lyrics[line_idx + 1][0] if line_idx + 1 < len(lyrics) else line_start + 4.0

            chunks = split_into_chunks(line_text, int(term_width * MARGIN), scale)
            line_duration = line_end - line_start
            elapsed_in_line = position - line_start

            timings, speech_end = _chunk_timings(chunks, line_duration)

            # Determine what to show
            if elapsed_in_line >= speech_end:
                # Past the lyrics — show idle animation
                frame_idx = int(elapsed_in_line * 2) % len(idle_frames)
                current_chunk = f"__idle_{frame_idx}"
            else:
                # Find current chunk by proportional timing
                chunk_idx = len(chunks) - 1
                for ci, (t_start, t_end) in enumerate(timings):
                    if elapsed_in_line < t_end:
                        chunk_idx = ci
                        break
                current_chunk = chunks[chunk_idx]

            if current_chunk != last_chunk:
                last_chunk = current_chunk
                term_size = os.get_terminal_size()
                term_width = term_size.columns
                term_height = term_size.lines

                if current_chunk.startswith("__idle_"):
                    frame = idle_frames[int(current_chunk.split("_")[-1])]
                    big = render_idle_frame(frame, idle_is_ascii, scale, term_width)
                    subtitle = ""
                else:
                    big = render_big_text(current_chunk, scale, term_width)
                    subtitle = line_text

                big_lines = big.split("\n")
                big_height = len(big_lines)

                header = f"♫ {artist} — {title}"
                content_height = 3 + big_height
                top_pad = max(0, (term_height - content_height) // 2)

                print("\033[2J\033[H", end="")
                print("\n" * top_pad, end="")
                print(f"\033[2m{header:^{term_width}}\033[0m")
                print(f"\033[2m{subtitle:^{term_width}}\033[0m")
                print()
                print(f"{color_on}{big}{color_off}")
                sys.stdout.flush()

            time.sleep(0.05)

        except KeyboardInterrupt:
            print("\033[?25h\033[0m\n")  # restore cursor + reset style
            sys.exit(0)


if __name__ == "__main__":
    main()
