#!/usr/bin/env python3

import json
import os
import random
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests


# ============================================================
# CONFIGURATION
# ============================================================

# Put SFW/neutral subreddits here.
# The bot will try ALL of them until it finds the required
# media type.
SUBREDDITS = [
    "nsfwanimegifs",
    "ecchi",
    "OverOppai",
    "CFNM_Hentai",
    "EcchiCurves",
    "animeplot",
]

MEME_API_URL = "https://meme-api.com/gimme/{subreddit}/{count}"

TELEGRAM_API = "https://api.telegram.org/bot{token}"

POSTED_FILE = Path("posted.json")

# Maximum Telegram upload sizes
TELEGRAM_IMAGE_LIMIT = 9 * 1024 * 1024
TELEGRAM_ANIMATION_LIMIT = 49 * 1024 * 1024

# Maximum download size we will accept before processing
MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024

REQUEST_TIMEOUT = 30

# Number of posts requested from meme-api for each subreddit
POSTS_PER_SUBREDDIT = 50

# Retry settings
API_RETRIES = 3
DOWNLOAD_RETRIES = 3

# GIF conversion defaults
GIF_FPS = 12
GIF_WIDTH = 480

# ============================================================
# ENVIRONMENT
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

if not TELEGRAM_BOT_TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN is not set.")
    sys.exit(1)

if not TELEGRAM_CHAT_ID:
    print("ERROR: TELEGRAM_CHAT_ID is not set.")
    sys.exit(1)


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 "
            "(compatible; TelegramMediaBot/1.0; +https://github.com/)"
        )
    }
)


# ============================================================
# STATE
# ============================================================

def load_state():
    """
    State format:

    {
        "sequence_index": 0,
        "posted": []
    }

    sequence_index:
        0 = photo
        1 = photo
        2 = GIF
    """

    if not POSTED_FILE.exists():
        return {
            "sequence_index": 0,
            "posted": [],
        }

    try:
        with POSTED_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("State is not an object")

        sequence_index = int(data.get("sequence_index", 0))
        posted = data.get("posted", [])

        if not isinstance(posted, list):
            posted = []

        return {
            "sequence_index": sequence_index,
            "posted": posted,
        }

    except Exception as e:
        print(f"WARNING: Could not read {POSTED_FILE}: {e}")

        return {
            "sequence_index": 0,
            "posted": [],
        }


def save_state(state):
    """Safely save bot state."""

    temporary = POSTED_FILE.with_suffix(".tmp")

    with temporary.open("w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            indent=2,
            ensure_ascii=False,
        )

    temporary.replace(POSTED_FILE)


def required_media_type(sequence_index):
    """
    Exact sequence:

        photo
        photo
        gif
        photo
        photo
        gif
        ...

    """

    position = sequence_index % 3

    if position == 2:
        return "gif"

    return "photo"


# ============================================================
# HELPERS
# ============================================================

def filename_from_url(url):
    try:
        path = urlparse(url).path
        name = Path(path).name

        if name and "." in name:
            return name

    except Exception:
        pass

    return "media"


def is_gif_bytes(data):
    return data.startswith(b"GIF87a") or data.startswith(b"GIF89a")


def is_jpeg_bytes(data):
    return data.startswith(b"\xff\xd8\xff")


def is_png_bytes(data):
    return data.startswith(b"\x89PNG\r\n\x1a\n")


def is_webp_bytes(data):
    return (
        len(data) >= 12
        and data[0:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    )


def looks_like_image(data):
    return (
        is_jpeg_bytes(data)
        or is_png_bytes(data)
        or is_webp_bytes(data)
    )


def looks_like_video_url(url):
    lower = url.lower().split("?")[0]

    return lower.endswith(
        (
            ".mp4",
            ".webm",
            ".mov",
            ".mkv",
            ".avi",
            ".m4v",
        )
    )


def looks_like_gif_url(url):
    lower = url.lower().split("?")[0]
    return lower.endswith(".gif")


def safe_subreddit_name(name):
    return str(name).strip().replace("/", "").replace("\\", "")


# ============================================================
# MEME API
# ============================================================

def get_subreddit_posts(subreddit):
    """Get posts from meme-api with retries."""

    subreddit = safe_subreddit_name(subreddit)

    url = MEME_API_URL.format(
        subreddit=subreddit,
        count=POSTS_PER_SUBREDDIT,
    )

    for attempt in range(1, API_RETRIES + 1):
        try:
            print(
                f"Fetching r/{subreddit} "
                f"(attempt {attempt}/{API_RETRIES})..."
            )

            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT,
            )

            print(
                f"meme-api response: HTTP {response.status_code}"
            )

            if response.status_code != 200:
                if attempt < API_RETRIES:
                    time.sleep(2 * attempt)
                    continue

                return []

            data = response.json()

            memes = data.get("memes", [])

            if not isinstance(memes, list):
                return []

            random.shuffle(memes)

            print(
                f"Found {len(memes)} candidate posts "
                f"from r/{subreddit}"
            )

            return memes

        except Exception as e:
            print(
                f"ERROR fetching r/{subreddit}: {e}"
            )

            if attempt < API_RETRIES:
                time.sleep(2 * attempt)

    return []


# ============================================================
# DOWNLOAD
# ============================================================

def download_file(url, destination):
    """Download a media file with size protection."""

    for attempt in range(1, DOWNLOAD_RETRIES + 1):

        try:
            print(
                f"Downloading media "
                f"(attempt {attempt}/{DOWNLOAD_RETRIES})..."
            )

            response = session.get(
                url,
                stream=True,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            if response.status_code != 200:
                print(
                    f"Download HTTP status: "
                    f"{response.status_code}"
                )

                if attempt < DOWNLOAD_RETRIES:
                    time.sleep(2)
                    continue

                return False

            content_length = response.headers.get("Content-Length")

            if content_length:
                try:
                    content_length = int(content_length)

                    if content_length > MAX_DOWNLOAD_SIZE:
                        print(
                            "Skipping file because it is too large: "
                            f"{content_length} bytes"
                        )
                        return False

                except ValueError:
                    pass

            total = 0

            with open(destination, "wb") as f:
                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):
                    if not chunk:
                        continue

                    total += len(chunk)

                    if total > MAX_DOWNLOAD_SIZE:
                        print(
                            "Download exceeded maximum size."
                        )

                        f.close()

                        try:
                            os.remove(destination)
                        except OSError:
                            pass

                        return False

                    f.write(chunk)

            if total == 0:
                print("Downloaded file is empty.")
                return False

            print(
                f"Downloaded {total / 1024 / 1024:.2f} MB"
            )

            return True

        except Exception as e:
            print(f"Download error: {e}")

            if attempt < DOWNLOAD_RETRIES:
                time.sleep(2)

    return False


# ============================================================
# MEDIA TYPE DETECTION
# ============================================================

def detect_media_type(path):
    """
    Return:

        gif
        image
        video
        unknown
    """

    try:
        with open(path, "rb") as f:
            header = f.read(32)

        if is_gif_bytes(header):
            return "gif"

        if looks_like_image(header):
            return "image"

    except Exception:
        pass

    suffix = path.suffix.lower()

    if suffix == ".gif":
        return "gif"

    if suffix in (
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".bmp",
    ):
        return "image"

    if suffix in (
        ".mp4",
        ".webm",
        ".mov",
        ".mkv",
        ".avi",
        ".m4v",
    ):
        return "video"

    return "unknown"


# ============================================================
# FFMPEG
# ============================================================

def check_ffmpeg():
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            print("FFmpeg: OK")
            return True

    except Exception as e:
        print(f"FFmpeg check failed: {e}")

    print("ERROR: FFmpeg is not available.")
    return False


def run_ffmpeg(command):
    print(
        "Running FFmpeg:",
        " ".join(command),
    )

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        print("FFmpeg failed:")
        print(result.stderr[-4000:])

        return False

    return True


# ============================================================
# VIDEO -> REAL GIF
# ============================================================

def convert_video_to_gif(video_path, gif_path):
    """
    Convert the ENTIRE video into a real GIF.

    This does NOT take a single frame.

    The resulting file starts with GIF87a/GIF89a and is sent
    to Telegram as animation.gif.
    """

    palette_path = gif_path.with_suffix(".palette.png")

    # First create an optimized palette.
    palette_filter = (
        f"fps={GIF_FPS},"
        f"scale={GIF_WIDTH}:-1:flags=lanczos,"
        "split[s0][s1];"
        "[s0]palettegen=max_colors=256:stats_mode=diff[p];"
        "[s1][p]paletteuse=dither=sierra2_4a"
    )

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        palette_filter,
        "-loop",
        "0",
        str(gif_path),
    ]

    success = run_ffmpeg(command)

    try:
        if palette_path.exists():
            palette_path.unlink()
    except OSError:
        pass

    if not success:
        return False

    if not gif_path.exists():
        return False

    media_type = detect_media_type(gif_path)

    if media_type != "gif":
        print(
            "ERROR: FFmpeg output is not a real GIF."
        )
        return False

    print(
        f"Created GIF: "
        f"{gif_path.stat().st_size / 1024 / 1024:.2f} MB"
    )

    return True


# ============================================================
# GIF COMPRESSION
# ============================================================

def compress_gif(input_gif, output_gif, fps, width):
    """
    Re-encode a GIF while keeping the full animation.
    """

    filter_value = (
        f"fps={fps},"
        f"scale={width}:-1:flags=lanczos,"
        "split[s0][s1];"
        "[s0]palettegen=max_colors=256:stats_mode=diff[p];"
        "[s1][p]paletteuse=dither=sierra2_4a"
    )

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_gif),
        "-vf",
        filter_value,
        "-loop",
        "0",
        str(output_gif),
    ]

    if not run_ffmpeg(command):
        return False

    if not output_gif.exists():
        return False

    if detect_media_type(output_gif) != "gif":
        return False

    return True


def make_gif_small_enough(gif_path):
    """
    Keep trying smaller GIF settings until it is under Telegram's
    animation upload limit.

    The complete animation is retained.
    """

    if gif_path.stat().st_size <= TELEGRAM_ANIMATION_LIMIT:
        return gif_path

    print(
        "GIF is larger than Telegram's animation limit."
    )

    attempts = [
        (10, 480),
        (8, 420),
        (8, 360),
        (6, 360),
        (5, 320),
    ]

    current = gif_path

    for index, (fps, width) in enumerate(attempts):

        output = gif_path.with_name(
            f"{gif_path.stem}_compressed_{index}.gif"
        )

        print(
            f"Compressing GIF: "
            f"{fps} FPS, width {width}"
        )

        if not compress_gif(
            current,
            output,
            fps,
            width,
        ):
            continue

        size = output.stat().st_size

        print(
            f"Compressed GIF size: "
            f"{size / 1024 / 1024:.2f} MB"
        )

        if size <= TELEGRAM_ANIMATION_LIMIT:
            return output

    return None


# ============================================================
# IMAGE COMPRESSION
# ============================================================

def compress_image(image_path):
    """
    Convert a large image to JPEG.

    IMPORTANT:
    This is only used for the PHOTO slot.

    GIFs are never passed through this function.
    """

    output = image_path.with_name(
        f"{image_path.stem}_telegram.jpg"
    )

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(image_path),
        "-vf",
        "scale='min(1920,iw)':-2",
        "-q:v",
        "5",
        str(output),
    ]

    if not run_ffmpeg(command):
        return None

    if not output.exists():
        return None

    if not is_jpeg_bytes(output.read_bytes()[:16]):
        return None

    if output.stat().st_size > TELEGRAM_IMAGE_LIMIT:
        output2 = image_path.with_name(
            f"{image_path.stem}_telegram_small.jpg"
        )

        command2 = [
            "ffmpeg",
            "-y",
            "-i",
            str(output),
            "-vf",
            "scale='min(1280,iw)':-2",
            "-q:v",
            "8",
            str(output2),
        ]

        if not run_ffmpeg(command2):
            return None

        if not output2.exists():
            return None

        return output2

    return output


# ============================================================
# TELEGRAM MULTIPART
# ============================================================

def telegram_upload(
    method,
    field_name,
    file_path,
    filename,
    content_type,
    caption,
):
    """
    Upload a file using multipart/form-data.

    IMPORTANT:
    This is the corrected multipart implementation.

    The broken old code had something similar to:

        f'filename="{filename}\r\n"

    which caused the SyntaxError.

    This version uses properly separated strings.
    """

    boundary = (
        "----TelegramMediaBot"
        + uuid.uuid4().hex
    )

    body = bytearray()

    def add_text_field(name, value):
        body.extend(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n'
                f"\r\n"
                f"{value}\r\n"
            ).encode("utf-8")
        )

    def add_file_field(name, path, upload_filename, mime):
        body.extend(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; '
                f'name="{name}"; '
                f'filename="{upload_filename}"\r\n'
                f"Content-Type: {mime}\r\n"
                f"\r\n"
            ).encode("utf-8")
        )

        with open(path, "rb") as f:
            body.extend(f.read())

        body.extend(b"\r\n")

    add_text_field(
        "chat_id",
        TELEGRAM_CHAT_ID,
    )

    if caption:
        add_text_field(
            "caption",
            caption,
        )

    add_file_field(
        field_name,
        file_path,
        filename,
        content_type,
    )

    body.extend(
        f"--{boundary}--\r\n".encode("utf-8")
    )

    url = (
        f"{TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)}"
        f"/{method}"
    )

    headers = {
        "Content-Type": (
            f"multipart/form-data; boundary={boundary}"
        )
    }

    try:
        response = session.post(
            url,
            data=bytes(body),
            headers=headers,
            timeout=120,
        )

        try:
            result = response.json()
        except Exception:
            result = {
                "ok": False,
                "description": response.text,
            }

        if response.status_code != 200 or not result.get("ok"):
            print(
                "Telegram API error:",
                result,
            )

            return False

        print(
            f"Telegram {method}: SUCCESS"
        )

        return True

    except Exception as e:
        print(
            f"Telegram upload error: {e}"
        )

        return False


# ============================================================
# TELEGRAM PHOTO
# ============================================================

def send_photo(file_path, subreddit):
    caption = f"r/{subreddit}"

    print(
        f"Sending PHOTO from r/{subreddit}..."
    )

    path_to_send = file_path

    # Telegram photo uploads have a smaller limit than animations.
    if path_to_send.stat().st_size > TELEGRAM_IMAGE_LIMIT:
        print(
            "Photo is too large. Compressing..."
        )

        compressed = compress_image(
            path_to_send
        )

        if compressed is None:
            print(
                "Could not compress photo."
            )
            return False

        path_to_send = compressed

    if path_to_send.stat().st_size > TELEGRAM_IMAGE_LIMIT:
        print(
            "Photo is still too large for Telegram."
        )
        return False

    return telegram_upload(
        method="sendPhoto",
        field_name="photo",
        file_path=path_to_send,
        filename="image.jpg",
        content_type="image/jpeg",
        caption=caption,
    )


# ============================================================
# TELEGRAM GIF
# ============================================================

def send_gif(file_path, subreddit):
    """
    Send a REAL GIF using Telegram sendAnimation.

    The field name is "animation".
    The filename is "animation.gif".

    This prevents Telegram from treating the GIF as a generic
    downloadable document.
    """

    if detect_media_type(file_path) != "gif":
        print(
            "ERROR: Refusing to send non-GIF file "
            "as GIF."
        )
        return False

    gif_to_send = make_gif_small_enough(
        file_path
    )

    if gif_to_send is None:
        print(
            "ERROR: Could not make GIF small enough."
        )
        return False

    if detect_media_type(gif_to_send) != "gif":
        print(
            "ERROR: Final file is not a GIF."
        )
        return False

    size = gif_to_send.stat().st_size

    if size > TELEGRAM_ANIMATION_LIMIT:
        print(
            "ERROR: GIF is still over Telegram's limit."
        )
        return False

    caption = f"r/{subreddit}"

    print(
        f"Sending REAL GIF from r/{subreddit}..."
    )

    return telegram_upload(
        method="sendAnimation",
        field_name="animation",
        file_path=gif_to_send,
        filename="animation.gif",
        content_type="image/gif",
        caption=caption,
    )


# ============================================================
# FIND MEDIA
# ============================================================

def find_media(required_type, posted):
    """
    Search every configured subreddit until we find the media
    type required by the sequence.

    PHOTO:
        only actual image files are accepted.

    GIF:
        actual GIF files are accepted.
        Videos can be converted to a REAL GIF.
        Photos are NEVER converted to GIF.
    """

    subreddits = list(SUBREDDITS)
    random.shuffle(subreddits)

    posted_set = set(posted)

    for subreddit in subreddits:

        subreddit = safe_subreddit_name(subreddit)

        if not subreddit:
            continue

        print()
        print("=" * 60)
        print(
            f"Searching r/{subreddit} "
            f"for {required_type.upper()}..."
        )
        print("=" * 60)

        posts = get_subreddit_posts(
            subreddit
        )

        if not posts:
            print(
                f"No API results from r/{subreddit}."
            )
            continue

        for post in posts:

            post_id = str(
                post.get("postLink")
                or post.get("id")
                or post.get("url")
                or ""
            )

            if not post_id:
                continue

            if post_id in posted_set:
                continue

            # Skip explicit/NSFW entries.
            if post.get("nsfw") is True:
                print(
                    "Skipping NSFW post."
                )
                continue

            title = str(
                post.get("title")
                or ""
            ).strip()

            url = str(
                post.get("url")
                or ""
            ).strip()

            if not url:
                continue

            print()
            print(
                f"Candidate: {title[:100]}"
            )
            print(
                f"URL: {url}"
            )

            with tempfile.TemporaryDirectory() as temp_dir:

                temp_dir_path = Path(temp_dir)

                source_name = filename_from_url(
                    url
                )

                source_path = (
                    temp_dir_path / source_name
                )

                # ====================================================
                # PHOTO SLOT
                # ====================================================

                if required_type == "photo":

                    # Never use GIF/video for photo slot.
                    if (
                        looks_like_gif_url(url)
                        or looks_like_video_url(url)
                    ):
                        print(
                            "Skipping: source is not a photo."
                        )
                        continue

                    if not download_file(
                        url,
                        source_path,
                    ):
                        continue

                    detected = detect_media_type(
                        source_path
                    )

                    if detected != "image":
                        print(
                            "Skipping: downloaded file "
                            f"is {detected}, not an image."
                        )
                        continue

                    print(
                        "Valid PHOTO found."
                    )

                    return {
                        "type": "photo",
                        "path": source_path,
                        "subreddit": subreddit,
                        "post_id": post_id,
                        "title": title,
                        "url": url,
                        "temp_dir": temp_dir,
                    }

                # ====================================================
                # GIF SLOT
                # ====================================================

                if required_type == "gif":

                    if not download_file(
                        url,
                        source_path,
                    ):
                        continue

                    detected = detect_media_type(
                        source_path
                    )

                    # --------------------------------------------
                    # Already a real GIF
                    # --------------------------------------------

                    if detected == "gif":

                        print(
                            "Valid REAL GIF found."
                        )

                        return {
                            "type": "gif",
                            "path": source_path,
                            "subreddit": subreddit,
                            "post_id": post_id,
                            "title": title,
                            "url": url,
                            "temp_dir": temp_dir,
                        }

                    # --------------------------------------------
                    # Video -> REAL GIF
                    # --------------------------------------------

                    if detected == "video":

                        print(
                            "Video found. Converting "
                            "the COMPLETE video to GIF..."
                        )

                        output_gif = (
                            temp_dir_path
                            / "animation.gif"
                        )

                        if not convert_video_to_gif(
                            source_path,
                            output_gif,
                        ):
                            print(
                                "Video -> GIF conversion failed."
                            )
                            continue

                        if detect_media_type(
                            output_gif
                        ) != "gif":
                            print(
                                "Conversion did not "
                                "produce a real GIF."
                            )
                            continue

                        print(
                            "Valid REAL GIF created."
                        )

                        return {
                            "type": "gif",
                            "path": output_gif,
                            "subreddit": subreddit,
                            "post_id": post_id,
                            "title": title,
                            "url": url,
                            "temp_dir": temp_dir,
                        }

                    # --------------------------------------------
                    # PHOTO -> NEVER GIF
                    # --------------------------------------------

                    if detected == "image":
                        print(
                            "Skipping photo because "
                            "GIF slot requires animation."
                        )
                        continue

                    print(
                        f"Skipping unsupported media type: "
                        f"{detected}"
                    )

    return None


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("Telegram Reddit Media Bot")
    print("=" * 70)

    print(
        f"Configured subreddits: {len(SUBREDDITS)}"
    )

    if not SUBREDDITS:
        print(
            "ERROR: SUBREDDITS is empty."
        )
        return 1

    if not check_ffmpeg():
        return 1

    state = load_state()

    sequence_index = int(
        state.get("sequence_index", 0)
    )

    posted = state.get(
        "posted",
        [],
    )

    required_type = required_media_type(
        sequence_index
    )

    print()
    print(
        f"Sequence index: {sequence_index}"
    )
    print(
        f"Required media: {required_type.upper()}"
    )

    if required_type == "photo":
        print(
            "Sequence position: PHOTO"
        )
    else:
        print(
            "Sequence position: GIF"
        )

    print()
    print(
        "Searching all configured subreddits..."
    )

    media = find_media(
        required_type,
        posted,
    )

    if media is None:
        print()
        print("=" * 70)
        print(
            "ERROR: No suitable media was found."
        )
        print(
            f"Required type: {required_type}"
        )
        print(
            "The bot did NOT advance the sequence."
        )
        print("=" * 70)

        # Exit with error so GitHub Actions does not falsely
        # report that the bot successfully posted.
        return 1

    print()
    print("=" * 70)
    print("MEDIA FOUND")
    print("=" * 70)
    print(
        f"Type: {media['type']}"
    )
    print(
        f"Subreddit: r/{media['subreddit']}"
    )
    print(
        f"Title: {media['title'][:150]}"
    )
    print("=" * 70)

    success = False

    try:

        if media["type"] == "photo":
            success = send_photo(
                media["path"],
                media["subreddit"],
            )

        elif media["type"] == "gif":
            success = send_gif(
                media["path"],
                media["subreddit"],
            )

        else:
            print(
                "ERROR: Unknown media type."
            )
            success = False

    except Exception as e:
        print()
        print(
            f"ERROR while posting: {e}"
        )
        success = False

    if not success:
        print()
        print(
            "ERROR: Telegram post failed."
        )
        print(
            "Sequence was NOT advanced."
        )
        return 1

    # ========================================================
    # SUCCESS
    # ========================================================

    posted.append(
        media["post_id"]
    )

    # Keep state reasonably small.
    if len(posted) > 1000:
        posted = posted[-1000:]

    state["posted"] = posted

    # Advance only after Telegram successfully posted.
    state["sequence_index"] = (
        sequence_index + 1
    )

    save_state(state)

    print()
    print("=" * 70)
    print("POST SUCCESSFUL")
    print("=" * 70)
    print(
        f"Next sequence index: "
        f"{state['sequence_index']}"
    )
    print(
        f"Next media type: "
        f"{required_media_type(state['sequence_index']).upper()}"
    )
    print("=" * 70)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        print("Bot interrupted.")
        sys.exit(130)
    except Exception as e:
        print()
        print(
            f"FATAL ERROR: {e}"
        )
        sys.exit(1)
