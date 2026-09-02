#!/usr/bin/env python3

import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


# ============================================================
# CONFIGURATION
# ============================================================

SUBREDDITS = [
    "nsfwanimegifs",
    "ecchi",
    "OverOppai",
    "CFNM_Hentai", 
    "EcchiCurves", 
    "animeplot"
]

POSTS_PER_SUBREDDIT = 50
SEARCH_ROUNDS = 5
HISTORY_LIMIT = 5000

MAX_SOURCE_SIZE = 50 * 1024 * 1024

# Keep safely below Telegram's image size limit.
MAX_IMAGE_UPLOAD = 9 * 1024 * 1024

# Keep safely below Telegram's animation limit.
MAX_GIF_UPLOAD = 47 * 1024 * 1024

# GIF conversion settings.
GIF_FPS = 12
GIF_WIDTH = 480

MEME_API_URL = "https://meme-api.com/gimme/{subreddit}/{count}"
REDDIT_JSON_URL = "https://www.reddit.com/r/{subreddit}/new.json"

USER_AGENT = (
    "RedditTelegramBot/12.0 "
    "(GitHub Actions)"
)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HISTORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "posted.json",
)


# ============================================================
# HISTORY
# ============================================================

def default_history():
    return {
        "urls": [],
        "ids": [],
        "hashes": [],
        "sequence_index": 0,
    }


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return default_history()

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return {
                "urls": data,
                "ids": [],
                "hashes": [],
                "sequence_index": 0,
            }

        if not isinstance(data, dict):
            return default_history()

        try:
            sequence_index = int(data.get("sequence_index", 0)) % 3
        except (TypeError, ValueError):
            sequence_index = 0

        return {
            "urls": list(data.get("urls", [])),
            "ids": list(data.get("ids", [])),
            "hashes": list(data.get("hashes", [])),
            "sequence_index": sequence_index,
        }

    except Exception as exc:
        print(
            f"Could not load posted.json: {exc}",
            file=sys.stderr,
        )
        return default_history()


def save_history(history):
    history["urls"] = history.get("urls", [])[-HISTORY_LIMIT:]
    history["ids"] = history.get("ids", [])[-HISTORY_LIMIT:]
    history["hashes"] = history.get("hashes", [])[-HISTORY_LIMIT:]

    try:
        history["sequence_index"] = (
            int(history.get("sequence_index", 0)) % 3
        )
    except (TypeError, ValueError):
        history["sequence_index"] = 0

    temp_path = HISTORY_FILE + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    os.replace(temp_path, HISTORY_FILE)


# ============================================================
# HTTP
# ============================================================

def fetch_json(url, attempts=4):
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                },
            )

            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()

            return json.loads(
                raw.decode("utf-8", errors="replace")
            )

        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.reason}"

            if exc.code not in {
                429, 500, 502, 503, 504, 530
            }:
                break

        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
        ) as exc:
            last_error = str(exc)

        except Exception as exc:
            last_error = str(exc)

        if attempt < attempts:
            wait = min(2 ** attempt, 12)
            print(
                f"Request failed ({last_error}). "
                f"Retrying in {wait}s..."
            )
            time.sleep(wait)

    print(
        f"Request failed permanently: {last_error}",
        file=sys.stderr,
    )
    return None


# ============================================================
# REDDIT SOURCES
# ============================================================

def fetch_from_meme_api(subreddit):
    url = MEME_API_URL.format(
        subreddit=urllib.parse.quote(subreddit),
        count=min(POSTS_PER_SUBREDDIT, 50),
    )

    data = fetch_json(url)

    if not data:
        return []

    posts = data.get("memes", [])

    if not isinstance(posts, list):
        return []

    normalized = []

    for post in posts:
        if not isinstance(post, dict):
            continue

        if not post.get("url"):
            continue

        post.setdefault("subreddit", subreddit)
        normalized.append(post)

    print(
        f"Meme API: {len(normalized)} posts from r/{subreddit}"
    )

    return normalized


def normalize_reddit_child(child):
    if not isinstance(child, dict):
        return None

    data = child.get("data", {})

    if not isinstance(data, dict):
        return None

    url = (
        data.get("url_overridden_by_dest")
        or data.get("url")
        or ""
    )

    if not url:
        return None

    post_id = str(data.get("id", ""))

    permalink = data.get("permalink", "")

    if permalink:
        post_link = (
            "https://www.reddit.com" + permalink
        )
    elif post_id:
        post_link = (
            "https://redd.it/" + post_id
        )
    else:
        post_link = ""

    return {
        "url": url,
        "postLink": post_link,
        "subreddit": data.get(
            "subreddit",
            "",
        ),
        "title": data.get(
            "title",
            "",
        ),
    }


def fetch_from_reddit(subreddit):
    url = (
        REDDIT_JSON_URL.format(
            subreddit=urllib.parse.quote(subreddit)
        )
        + "?"
        + urllib.parse.urlencode(
            {
                "limit": min(
                    POSTS_PER_SUBREDDIT,
                    100,
                ),
                "raw_json": 1,
            }
        )
    )

    data = fetch_json(url, attempts=3)

    if not data:
        return []

    children = (
        data.get("data", {})
        .get("children", [])
    )

    posts = []

    for child in children:
        post = normalize_reddit_child(child)

        if post:
            posts.append(post)

    print(
        f"Reddit fallback: {len(posts)} posts from "
        f"r/{subreddit}"
    )

    return posts


def fetch_all_candidates():
    order = list(SUBREDDITS)
    random.shuffle(order)

    print()
    print("Checking subreddits:")

    all_posts = []

    for subreddit in order:
        print(f"  r/{subreddit}")

        posts = fetch_from_meme_api(subreddit)

        if not posts:
            print(
                f"Meme API failed for r/{subreddit}; "
                "trying Reddit fallback..."
            )

            posts = fetch_from_reddit(subreddit)

        all_posts.extend(posts)

    random.shuffle(all_posts)

    return all_posts


# ============================================================
# MEDIA DOWNLOAD
# ============================================================

def download_media(url):
    print()
    print(f"Downloading: {url}")

    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
            },
        )

        with urllib.request.urlopen(
            request,
            timeout=60,
        ) as response:

            content_type = (
                response.headers.get(
                    "Content-Type",
                    "",
                )
                .lower()
            )

            data = response.read(
                MAX_SOURCE_SIZE + 1
            )

        if not data:
            return None, ""

        if len(data) > MAX_SOURCE_SIZE:
            print("Skipped: source is larger than 50 MB.")
            return None, ""

        print(
            f"Downloaded: "
            f"{len(data) / 1024 / 1024:.2f} MB"
        )

        print(
            f"Content-Type: {content_type}"
        )

        return data, content_type

    except Exception as exc:
        print(
            f"Download failed: {exc}",
            file=sys.stderr,
        )
        return None, ""


# ============================================================
# MEDIA TYPE
# ============================================================

def detect_media_type(url, data, content_type):
    clean_url = (
        url
        .lower()
        .split("?", 1)[0]
        .split("#", 1)[0]
    )

    content_type = (
        content_type
        or ""
    ).lower()

    # Real GIF.
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"

    if "image/gif" in content_type:
        return "gif"

    if clean_url.endswith(".gif"):
        return "gif"

    # MP4 / MOV.
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "video"

    if content_type.startswith("video/"):
        return "video"

    if clean_url.endswith(
        (
            ".mp4",
            ".m4v",
            ".mov",
            ".webm",
        )
    ):
        return "video"

    # JPEG.
    if data.startswith(b"\xff\xd8\xff"):
        return "photo"

    # PNG.
    if data.startswith(b"\x89PNG"):
        return "photo"

    # WEBP.
    if (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):
        return "photo"

    if content_type.startswith("image/"):
        return "photo"

    if clean_url.endswith(
        (
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        )
    ):
        return "photo"

    return "unknown"


# ============================================================
# TEMPORARY FILE
# ============================================================

def write_temp_file(data, suffix):
    fd, path = tempfile.mkstemp(
        suffix=suffix
    )

    os.close(fd)

    with open(path, "wb") as f:
        f.write(data)

    return path


# ============================================================
# IMAGE COMPRESSION
# ============================================================

def compress_photo(data):
    if len(data) <= MAX_IMAGE_UPLOAD:
        return data

    print("Large image detected; compressing...")

    source = write_temp_file(
        data,
        ".source",
    )

    try:
        settings = [
            (90, 1920),
            (80, 1600),
            (70, 1400),
            (60, 1200),
            (50, 1000),
            (40, 800),
        ]

        for quality, width in settings:

            result = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    source,
                    "-vf",
                    (
                        f"scale={width}:-1:"
                        "force_original_aspect_ratio=decrease"
                    ),
                    "-frames:v",
                    "1",
                    "-q:v",
                    str(quality),
                    "-f",
                    "image2",
                    "pipe:1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )

            if result.returncode != 0:
                continue

            output = result.stdout

            if not output:
                continue

            size_mb = len(output) / 1024 / 1024

            print(
                f"Image {width}px q{quality}: "
                f"{size_mb:.2f} MB"
            )

            if len(output) <= MAX_IMAGE_UPLOAD:
                return output

        return None

    finally:
        try:
            os.remove(source)
        except OSError:
            pass


# ============================================================
# VIDEO → REAL GIF
# ============================================================

def video_to_gif(data):
    print("Converting animated video to real GIF...")

    source = write_temp_file(
        data,
        ".source",
    )

    palette = tempfile.mktemp(
        suffix=".png"
    )

    output = tempfile.mktemp(
        suffix=".gif"
    )

    try:
        palette_result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                source,
                "-vf",
                (
                    f"fps={GIF_FPS},"
                    f"scale={GIF_WIDTH}:-1:"
                    "force_original_aspect_ratio=decrease,"
                    "palettegen"
                ),
                palette,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
        )

        if (
            palette_result.returncode != 0
            or not os.path.exists(palette)
        ):
            print("GIF palette creation failed.")
            return None

        gif_result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                source,
                "-i",
                palette,
                "-filter_complex",
                (
                    f"[0:v]"
                    f"fps={GIF_FPS},"
                    f"scale={GIF_WIDTH}:-1:"
                    "force_original_aspect_ratio=decrease"
                    "[v];"
                    "[v][1:v]"
                    "paletteuse=dither=sierra2_4a"
                ),
                "-loop",
                "0",
                output,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=240,
        )

        if (
            gif_result.returncode != 0
            or not os.path.exists(output)
        ):
            print("GIF creation failed.")
            return None

        with open(output, "rb") as f:
            gif_data = f.read()

        if not gif_data.startswith(
            (b"GIF87a", b"GIF89a")
        ):
            print("Output is not a real GIF.")
            return None

        if len(gif_data) > MAX_GIF_UPLOAD:
            print("GIF is too large.")
            return None

        print(
            f"Real GIF created: "
            f"{len(gif_data) / 1024 / 1024:.2f} MB"
        )

        return gif_data

    except Exception as exc:
        print(
            f"GIF conversion failed: {exc}",
            file=sys.stderr,
        )
        return None

    finally:
        for path in (
            source,
            palette,
            output,
        ):
            try:
                os.remove(path)
            except OSError:
                pass


# ============================================================
# HASH
# ============================================================

def sha256(data):
    return hashlib.sha256(data).hexdigest()


# ============================================================
# REQUIRED SEQUENCE
# ============================================================

def required_type(history):
    index = history.get(
        "sequence_index",
        0,
    )

    try:
        index = int(index) % 3
    except (TypeError, ValueError):
        index = 0

    if index == 2:
        return "gif"

    return "photo"


def advance_sequence(history):
    current = history.get(
        "sequence_index",
        0,
    )

    try:
        current = int(current) % 3
    except (TypeError, ValueError):
        current = 0

    history["sequence_index"] = (
        (current + 1) % 3
    )


# ============================================================
# FIND MEDIA
# ============================================================

def find_media(history):
    seen_urls = set(
        history.get("urls", [])
    )

    seen_ids = set(
        history.get("ids", [])
    )

    seen_hashes = set(
        history.get("hashes", [])
    )

    wanted = required_type(history)

    print()
    print(
        "========================================"
    )
    print(
        "CURRENT SLOT: "
        + wanted.upper()
    )
    print(
        "PATTERN: IMAGE → IMAGE → GIF"
    )
    print(
        "========================================"
    )

    for round_number in range(
        1,
        SEARCH_ROUNDS + 1
    ):

        print()
        print(
            f"SEARCH ROUND "
            f"{round_number}/{SEARCH_ROUNDS}"
        )

        posts = fetch_all_candidates()

        if not posts:
            time.sleep(2)
            continue

        for post in posts:

            url = post.get(
                "url",
                ""
            )

            post_id = post.get(
                "postLink",
                ""
            )

            subreddit = post.get(
                "subreddit",
                "unknown"
            )

            if not url:
                continue

            # ------------------------------------------------
            # DUPLICATES
            # ------------------------------------------------

            if url in seen_urls:

                print(
                    f"r/{subreddit}: "
                    "duplicate URL."
                )

                continue

            if (
                post_id
                and post_id in seen_ids
            ):

                print(
                    f"r/{subreddit}: "
                    "duplicate Reddit post."
                )

                continue

            # ------------------------------------------------
            # DOWNLOAD
            # ------------------------------------------------

            data, content_type = (
                download_media(url)
            )

            if data is None:
                continue

            source_type = detect_media_type(
                url,
                data,
                content_type
            )

            print(
                f"r/{subreddit}: "
                f"detected {source_type}"
            )

            if source_type == "unknown":
                continue

            digest = sha256(data)

            if digest in seen_hashes:

                print(
                    "Exact duplicate."
                )

                continue

            # =================================================
            # IMAGE SLOT
            # =================================================

            if wanted == "photo":

                # ONLY photos.
                # Never convert GIF/video to photo.

                if source_type != "photo":

                    print(
                        f"r/{subreddit}: "
                        "not an image; trying another source."
                    )

                    continue

                prepared = compress_photo(
                    data
                )

                if prepared is None:

                    print(
                        "Could not prepare image."
                    )

                    continue

                telegram_type = "photo"

            # =================================================
            # GIF SLOT
            # =================================================

            else:

                # Never convert a normal image to GIF.
                if source_type == "photo":

                    print(
                        f"r/{subreddit}: "
                        "image found, but GIF required."
                    )

                    continue

                if source_type == "gif":

                    print(
                        f"r/{subreddit}: "
                        "REAL GIF found."
                    )

                    prepared = data

                elif source_type == "video":

                    print(
                        f"r/{subreddit}: "
                        "animated video found."
                    )

                    prepared = video_to_gif(
                        data
                    )

                    if prepared is None:
                        continue

                else:

                    continue

                # Final hard check.
                if not prepared.startswith(
                    (b"GIF87a", b"GIF89a")
                ):

                    print(
                        "Rejected: final output "
                        "is not a real GIF."
                    )

                    continue

                telegram_type = "gif"

            # ------------------------------------------------
            # ACCEPT
            # ------------------------------------------------

            post["_media_data"] = prepared
            post["_media_type"] = telegram_type
            post["_media_hash"] = digest

            print()
            print(
                "========================================"
            )
            print(
                "MEDIA SELECTED"
            )
            print(
                f"Subreddit: r/{subreddit}"
            )
            print(
                f"Original: {source_type}"
            )
            print(
                f"Telegram: {telegram_type}"
            )
            print(
                "========================================"
            )

            return post

    return None


# ============================================================
# MULTIPART HELPERS
# ============================================================

def make_field(
    boundary,
    name,
    value,
):
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; '
        f'name="{name}"\r\n'
        f"\r\n"
        f"{value}\r\n"
    ).encode("utf-8")


def make_file(
    boundary,
    field_name,
    filename,
    content_type,
    data,
):
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; '
        f'name="{field_name}"; '
        f'filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n"
        f"\r\n"
    ).encode("utf-8")

    return (
        header
        + data
        + b"\r\n"
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_upload(
    method,
    field_name,
    filename,
    content_type,
    data,
):
    url = (
        "https://api.telegram.org/"
        f"bot{BOT_TOKEN}/{method}"
    )

    boundary = (
        "----RedditTelegramBot"
        + hashlib.md5(
            os.urandom(16)
        ).hexdigest()
    )

    body = bytearray()

    body.extend(
        make_field(
            boundary,
            "chat_id",
            CHAT_ID,
        )
    )

    body.extend(
        make_file(
            boundary,
            field_name,
            filename,
            content_type,
            data,
        )
    )

    body.extend(
        f"--{boundary}--\r\n".encode(
            "utf-8"
        )
    )

    request = urllib.request.Request(
        url,
        data=bytes(body),
        method="POST",
        headers={
            "Content-Type":
                (
                    "multipart/form-data; "
                    f"boundary={boundary}"
                )
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=240,
    ) as response:

        return json.loads(
            response
            .read()
            .decode("utf-8")
        )


def send_to_telegram(post):
    data = post.get(
        "_media_data"
    )

    media_type = post.get(
        "_media_type"
    )

    if not data:
        return False

    print()
    print(
        "========================================"
    )
    print(
        "UPLOADING TO TELEGRAM"
    )
    print(
        f"Type: {media_type}"
    )
    print(
        f"Size: "
        f"{len(data) / 1024 / 1024:.2f} MB"
    )
    print(
        "========================================"
    )

    try:

        if media_type == "photo":

            print(
                "Sending as PHOTO..."
            )

            result = telegram_upload(
                "sendPhoto",
                "photo",
                "image.jpg",
                "image/jpeg",
                data,
            )

        elif media_type == "gif":

            print(
                "Sending as REAL GIF..."
            )

            result = telegram_upload(
                "sendAnimation",
                "animation",
                "animation.gif",
                "image/gif",
                data,
            )

        else:

            print(
                "Unknown Telegram media type."
            )

            return False

        if not result.get("ok"):

            print(
                "Telegram API error:"
            )

            print(
                json.dumps(
                    result,
                    indent=2,
                )
            )

            return False

        print()
        print(
            "POSTED SUCCESSFULLY"
        )

        return True

    except urllib.error.HTTPError as exc:

        details = exc.read().decode(
            "utf-8",
            errors="ignore"
        )

        print(
            f"Telegram HTTP {exc.code}:"
        )

        print(
            details,
            file=sys.stderr
        )

        return False

    except Exception as exc:

        print(
            f"Telegram error: {exc}",
            file=sys.stderr
        )

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "========================================"
    )
    print(
        "REDDIT → TELEGRAM MEDIA BOT"
    )
    print(
        "2 IMAGES → 1 GIF"
    )
    print(
        "NO CROSS-FORMAT CONVERSION"
    )
    print(
        "========================================"
    )

    if not BOT_TOKEN:
        print(
            "ERROR: TELEGRAM_BOT_TOKEN is missing.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not CHAT_ID:
        print(
            "ERROR: TELEGRAM_CHAT_ID is missing.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not SUBREDDITS:
        print(
            "ERROR: SUBREDDITS is empty.",
            file=sys.stderr,
        )
        sys.exit(1)

    history = load_history()

    post = find_media(
        history
    )

    if post is None:

        print()
        print(
            "========================================"
        )
        print(
            "NO SUITABLE MEDIA FOUND"
        )
        print(
            "Sequence was NOT advanced."
        )
        print(
            "========================================"
        )

        return

    if not send_to_telegram(
        post
    ):

        print(
            "Posting failed."
        )

        print(
            "History was NOT changed."
        )

        return

    url = post.get(
        "url",
        ""
    )

    post_id = post.get(
        "postLink",
        ""
    )

    digest = post.get(
        "_media_hash",
        ""
    )

    if url:
        history["urls"].append(
            url
        )

    if post_id:
        history["ids"].append(
            post_id
        )

    if digest:
        history["hashes"].append(
            digest
        )

    advance_sequence(
        history
    )

    save_history(
        history
    )

    print()
    print(
        "========================================"
    )
    print(
        "SUCCESS"
    )
    print(
        f"Next required: "
        f"{required_type(history).upper()}"
    )
    print(
        "========================================"
    )


if __name__ == "__main__":
    main()
