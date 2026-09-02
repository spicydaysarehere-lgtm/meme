#!/usr/bin/env python3

import os
import sys
import json
import time
import random
import hashlib
import urllib.request
import urllib.error
import urllib.parse
import subprocess
import tempfile


# ============================================================
# SUBREDDITS
# ============================================================

# Use SFW subreddits here.
SUBREDDITS = [
    "gifs",
    "aww",
    "wholesome",
]


# ============================================================
# SETTINGS
# ============================================================

SUBREDDITS_PER_RUN = 2
MEMES_PER_SUBREDDIT = 50
HISTORY_LIMIT = 5000
FETCH_ATTEMPTS = 8

MAX_MEDIA_SIZE = 50 * 1024 * 1024

TELEGRAM_IMAGE_LIMIT = 9 * 1024 * 1024

TELEGRAM_ANIMATION_LIMIT = 49 * 1024 * 1024

MEME_API_URL = (
    "https://meme-api.com/gimme/{subreddit}/{count}"
)


# ============================================================
# TELEGRAM
# ============================================================

BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN"
)

CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID"
)


# ============================================================
# HISTORY
# ============================================================

HISTORY_FILE = os.path.join(
    os.path.dirname(
        os.path.abspath(__file__)
    ),
    "posted.json"
)


def empty_history():
    return {
        "urls": [],
        "ids": [],
        "hashes": []
    }


def load_history():

    if not os.path.exists(HISTORY_FILE):
        return empty_history()

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, dict):

            return {
                "urls": data.get("urls", []),
                "ids": data.get("ids", []),
                "hashes": data.get("hashes", [])
            }

        if isinstance(data, list):

            return {
                "urls": data,
                "ids": [],
                "hashes": []
            }

    except Exception as error:

        print(
            f"Could not load posted.json: {error}",
            file=sys.stderr
        )

    return empty_history()


def save_history(history):

    history["urls"] = (
        history.get("urls", [])
        [-HISTORY_LIMIT:]
    )

    history["ids"] = (
        history.get("ids", [])
        [-HISTORY_LIMIT:]
    )

    history["hashes"] = (
        history.get("hashes", [])
        [-HISTORY_LIMIT:]
    )

    with open(
        HISTORY_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            history,
            file,
            indent=2
        )


# ============================================================
# DOWNLOAD
# ============================================================

def download_media(url):

    print()
    print("Downloading media:")
    print(url)

    try:

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent":
                    "SFWRedditTelegramBot/1.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=60
        ) as response:

            content_type = (
                response.headers.get(
                    "Content-Type",
                    ""
                )
                .lower()
            )

            data = response.read(
                MAX_MEDIA_SIZE + 1
            )

        if len(data) > MAX_MEDIA_SIZE:

            print(
                "Skipped: media is larger than 50 MB."
            )

            return None, ""

        if not data:

            print(
                "Skipped: empty media."
            )

            return None, ""

        print(
            f"Downloaded: "
            f"{len(data) / 1024 / 1024:.2f} MB"
        )

        print(
            f"Content-Type: {content_type}"
        )

        return data, content_type

    except Exception as error:

        print(
            f"Download failed: {error}",
            file=sys.stderr
        )

        return None, ""


# ============================================================
# DETECT MEDIA TYPE
# ============================================================

def detect_media_type(
    url,
    data,
    content_type
):

    clean_url = (
        url.lower()
        .split("?")[0]
        .split("#")[0]
    )

    content_type = (
        content_type or ""
    ).lower()

    # --------------------------------------------------------
    # GIF
    # --------------------------------------------------------

    if data.startswith(b"GIF87a"):
        return "gif"

    if data.startswith(b"GIF89a"):
        return "gif"

    if "image/gif" in content_type:
        return "gif"

    if clean_url.endswith(".gif"):
        return "gif"

    # --------------------------------------------------------
    # VIDEO
    # --------------------------------------------------------

    if (
        len(data) >= 12
        and data[4:8] == b"ftyp"
    ):
        return "animated_video"

    if content_type.startswith("video/"):
        return "animated_video"

    if clean_url.endswith(".mp4"):
        return "animated_video"

    if clean_url.endswith(".m4v"):
        return "animated_video"

    if clean_url.endswith(".mov"):
        return "animated_video"

    if clean_url.endswith(".webm"):
        return "animated_video"

    # --------------------------------------------------------
    # PHOTO
    # --------------------------------------------------------

    if data.startswith(b"\xff\xd8\xff"):
        return "photo"

    if data.startswith(b"\x89PNG"):
        return "photo"

    if (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):
        return "photo"

    if content_type.startswith("image/"):
        return "photo"

    if clean_url.endswith(
        (".jpg", ".jpeg", ".png", ".webp")
    ):
        return "photo"

    return "unknown"


# ============================================================
# TEMPORARY FILE
# ============================================================

def save_temp_file(data, suffix):

    fd, path = tempfile.mkstemp(
        suffix=suffix
    )

    os.close(fd)

    with open(
        path,
        "wb"
    ) as file:

        file.write(data)

    return path


# ============================================================
# CONVERT VIDEO/GIF-LIKE VIDEO TO ANIMATION MP4
# ============================================================

def convert_to_animation_mp4(data):

    source = save_temp_file(
        data,
        ".source"
    )

    output = tempfile.mktemp(
        suffix=".mp4"
    )

    try:

        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",

            "-i",
            source,

            "-an",

            "-vf",
            (
                "scale="
                "min(720,iw):"
                "min(720,ih):"
                "force_original_aspect_ratio=decrease"
            ),

            "-c:v",
            "libx264",

            "-preset",
            "veryfast",

            "-crf",
            "23",

            "-pix_fmt",
            "yuv420p",

            "-movflags",
            "+faststart",

            output
        ]

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180
        )

        if result.returncode != 0:
            print(
                result.stderr.decode(
                    "utf-8",
                    errors="ignore"
                ),
                file=sys.stderr
            )
            return None

        with open(
            output,
            "rb"
        ) as file:

            converted = file.read()

        if len(converted) > (
            TELEGRAM_ANIMATION_LIMIT
        ):

            print(
                "Animation is too large."
            )

            return None

        print(
            f"Animation MP4: "
            f"{len(converted) / 1024 / 1024:.2f} MB"
        )

        return converted

    except Exception as error:

        print(
            f"Animation conversion failed: "
            f"{error}",
            file=sys.stderr
        )

        return None

    finally:

        try:
            os.remove(source)
        except Exception:
            pass

        try:
            os.remove(output)
        except Exception:
            pass


# ============================================================
# COMPRESS PHOTO
# ============================================================

def compress_photo(data):

    if len(data) <= TELEGRAM_IMAGE_LIMIT:
        return data

    source = save_temp_file(
        data,
        ".source"
    )

    try:

        attempts = [
            ("90", "1920:-2"),
            ("80", "1600:-2"),
            ("70", "1400:-2"),
            ("60", "1200:-2"),
            ("50", "1000:-2"),
            ("40", "900:-2"),
        ]

        for quality, scale in attempts:

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
                        f"scale={scale}:"
                        "force_original_aspect_ratio=decrease"
                    ),

                    "-frames:v",
                    "1",

                    "-q:v",
                    quality,

                    "-f",
                    "image2",

                    "pipe:1"
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60
            )

            output = result.stdout

            if not output:
                continue

            size_mb = (
                len(output)
                / 1024
                / 1024
            )

            print(
                f"JPEG quality {quality}: "
                f"{size_mb:.2f} MB"
            )

            if len(output) <= (
                TELEGRAM_IMAGE_LIMIT
            ):

                return output

        return None

    finally:

        try:
            os.remove(source)
        except Exception:
            pass


# ============================================================
# HASH
# ============================================================

def media_hash(data):

    return hashlib.sha256(
        data
    ).hexdigest()


# ============================================================
# FETCH REDDIT POSTS
# ============================================================

def fetch_candidate_posts():

    count = min(
        SUBREDDITS_PER_RUN,
        len(SUBREDDITS)
    )

    chosen = random.sample(
        SUBREDDITS,
        count
    )

    print()
    print("Checking subreddits:")

    for subreddit in chosen:
        print(f"  r/{subreddit}")

    all_posts = []

    for subreddit in chosen:

        encoded = urllib.parse.quote(
            subreddit
        )

        url = MEME_API_URL.format(
            subreddit=encoded,
            count=MEMES_PER_SUBREDDIT
        )

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent":
                    "SFWRedditTelegramBot/1.0"
            }
        )

        try:

            with urllib.request.urlopen(
                request,
                timeout=30
            ) as response:

                raw = response.read().decode(
                    "utf-8"
                )

            data = json.loads(
                raw
            )

            posts = data.get(
                "memes",
                []
            )

            if isinstance(
                posts,
                list
            ):

                all_posts.extend(
                    posts
                )

                print(
                    f"r/{subreddit}: "
                    f"{len(posts)} posts received"
                )

        except Exception as error:

            print(
                f"r/{subreddit}: {error}",
                file=sys.stderr
            )

    return all_posts


# ============================================================
# FIND NEW MEDIA
# ============================================================

def find_new_media(history):

    seen_urls = set(
        history.get("urls", [])
    )

    seen_ids = set(
        history.get("ids", [])
    )

    seen_hashes = set(
        history.get("hashes", [])
    )

    for attempt in range(
        1,
        FETCH_ATTEMPTS + 1
    ):

        print()
        print(
            f"SEARCH BATCH "
            f"{attempt}/{FETCH_ATTEMPTS}"
        )

        posts = fetch_candidate_posts()

        if not posts:

            time.sleep(2)
            continue

        random.shuffle(posts)

        for post in posts:

            url = post.get("url")

            post_id = post.get(
                "postLink",
                ""
            )

            if not url:
                continue

            if url in seen_urls:
                print(
                    "Skipped duplicate URL."
                )
                continue

            if (
                post_id
                and post_id in seen_ids
            ):

                print(
                    "Skipped duplicate Reddit post."
                )

                continue

            media_data, content_type = (
                download_media(url)
            )

            if media_data is None:
                continue

            media_type = detect_media_type(
                url,
                media_data,
                content_type
            )

            print(
                f"Detected type: {media_type}"
            )

            if media_type == "unknown":

                print(
                    "Skipped unsupported media."
                )

                continue

            digest = media_hash(
                media_data
            )

            if digest in seen_hashes:

                print(
                    "Skipped exact duplicate."
                )

                continue

            # ------------------------------------------------
            # NORMAL PHOTO
            # ------------------------------------------------

            if media_type == "photo":

                prepared = compress_photo(
                    media_data
                )

                if prepared is None:

                    print(
                        "Could not prepare photo."
                    )

                    continue

                telegram_type = "photo"

            # ------------------------------------------------
            # REAL GIF
            # ------------------------------------------------

            elif media_type == "gif":

                prepared = media_data

                telegram_type = "gif"

            # ------------------------------------------------
            # MP4/WEBM REPRESENTING ANIMATION
            # ------------------------------------------------

            elif media_type == "animated_video":

                prepared = convert_to_animation_mp4(
                    media_data
                )

                if prepared is None:
                    continue

                # IMPORTANT:
                # Send through sendAnimation, NOT sendVideo.
                telegram_type = "animation_mp4"

            else:

                continue

            post["_media_data"] = prepared

            post["_media_type"] = telegram_type

            post["_media_hash"] = digest

            print()
            print(
                "========================================"
            )
            print(
                "NEW MEDIA FOUND"
            )
            print(
                f"Original: {media_type}"
            )
            print(
                f"Telegram: {telegram_type}"
            )
            print(
                f"Subreddit: "
                f"r/{post.get('subreddit', 'unknown')}"
            )
            print(
                "========================================"
            )

            return post

        print(
            "No new media found in this batch."
        )

    return None


# ============================================================
# MULTIPART HELPERS
# ============================================================

def multipart_field(
    boundary,
    name,
    value
):

    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; '
        f'name="{name}"\r\n'
        f"\r\n"
        f"{value}\r\n"
    ).encode()


def multipart_file(
    boundary,
    field_name,
    filename,
    content_type,
    data
):

    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; '
        f'name="{field_name}"; '
        f'filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n"
        f"\r\n"
    ).encode()

    return (
        header
        + data
        + b"\r\n"
    )


# ============================================================
# TELEGRAM UPLOAD
# ============================================================

def telegram_upload(
    method,
    field_name,
    filename,
    content_type,
    data
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
        multipart_field(
            boundary,
            "chat_id",
            CHAT_ID
        )
    )

    body.extend(
        multipart_file(
            boundary,
            field_name,
            filename,
            content_type,
            data
        )
    )

    body.extend(
        f"--{boundary}--\r\n".encode()
    )

    request = urllib.request.Request(
        url,
        data=bytes(body),
        method="POST",
        headers={
            "Content-Type":
                "multipart/form-data; "
                f"boundary={boundary}"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=180
    ) as response:

        return json.loads(
            response.read().decode(
                "utf-8"
            )
        )


# ============================================================
# TELEGRAM SEND
# ============================================================

def send_to_telegram(post):

    data = post.get(
        "_media_data"
    )

    media_type = post.get(
        "_media_type"
    )

    try:

        if media_type == "photo":

            print(
                "Sending image with sendPhoto..."
            )

            result = telegram_upload(
                "sendPhoto",
                "photo",
                "image.jpg",
                "image/jpeg",
                data
            )

        elif media_type == "gif":

            print(
                "Sending GIF with sendAnimation..."
            )

            result = telegram_upload(
                "sendAnimation",
                "animation",
                "animation.gif",
                "image/gif",
                data
            )

        elif media_type == "animation_mp4":

            print(
                "Sending animated MP4 "
                "with sendAnimation..."
            )

            result = telegram_upload(
                "sendAnimation",
                "animation",
                "animation.mp4",
                "video/mp4",
                data
            )

        else:

            print(
                "Unknown media type."
            )

            return False

        if not result.get("ok"):

            print(
                "Telegram API error:"
            )

            print(
                json.dumps(
                    result,
                    indent=2
                )
            )

            return False

        print()
        print(
            "========================================"
        )
        print(
            "POSTED SUCCESSFULLY"
        )
        print(
            "========================================"
        )
        print(
            f"Type: {media_type}"
        )
        print(
            f"URL: {post.get('url')}"
        )
        print(
            "========================================"
        )

        return True

    except Exception as error:

        print(
            f"Telegram upload failed: "
            f"{error}",
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
        "PHOTO + GIF + ANIMATED VIDEO"
    )
    print(
        "========================================"
    )

    if not BOT_TOKEN:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN is missing.",
            file=sys.stderr
        )

        sys.exit(1)

    if not CHAT_ID:

        print(
            "ERROR: TELEGRAM_CHAT_ID is missing.",
            file=sys.stderr
        )

        sys.exit(1)

    history = load_history()

    print(
        f"Stored URLs: "
        f"{len(history['urls'])}"
    )

    print(
        f"Stored Reddit IDs: "
        f"{len(history['ids'])}"
    )

    print(
        f"Stored hashes: "
        f"{len(history['hashes'])}"
    )

    post = find_new_media(
        history
    )

    if not post:

        print(
            "No new media found this run."
        )

        return

    if not send_to_telegram(post):

        print(
            "Posting failed."
        )

        print(
            "History was NOT changed."
        )

        return

    url = post.get(
        "url"
    )

    post_id = post.get(
        "postLink",
        ""
    )

    digest = post.get(
        "_media_hash"
    )

    if url:
        history["urls"].append(url)

    if post_id:
        history["ids"].append(post_id)

    if digest:
        history["hashes"].append(digest)

    save_history(history)

    print(
        "posted.json updated."
    )

    print(
        "Finished successfully."
    )


if __name__ == "__main__":
    main()
