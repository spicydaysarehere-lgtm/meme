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

SUBREDDITS = [
    "nsfwanimegifs",
    "ecchi",
    "OverOppai",
    "CFNM_Hentai",
    "EcchiCurves"
]


# ============================================================
# SETTINGS
# ============================================================

SUBREDDITS_PER_RUN = 2
MEMES_PER_SUBREDDIT = 50
HISTORY_LIMIT = 5000
FETCH_ATTEMPTS = 8

MAX_MEDIA_SIZE = 50 * 1024 * 1024

# Keep images safely below Telegram's photo limit.
TELEGRAM_IMAGE_LIMIT = 9 * 1024 * 1024

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
                    "TelegramRedditMediaBot/4.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=45
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

            print("Skipped: empty download.")

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

    # GIF
    if data.startswith(b"GIF87a"):
        return "gif"

    if data.startswith(b"GIF89a"):
        return "gif"

    if "image/gif" in content_type:
        return "gif"

    if clean_url.endswith(".gif"):
        return "gif"

    # MP4 / MOV / M4V
    if (
        len(data) >= 12
        and data[4:8] == b"ftyp"
    ):
        return "video"

    if content_type.startswith("video/"):
        return "video"

    if clean_url.endswith(".mp4"):
        return "video"

    if clean_url.endswith(".m4v"):
        return "video"

    if clean_url.endswith(".mov"):
        return "video"

    if clean_url.endswith(".webm"):
        return "video"

    # JPEG
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"

    if "image/jpeg" in content_type:
        return "jpg"

    if clean_url.endswith(".jpg"):
        return "jpg"

    if clean_url.endswith(".jpeg"):
        return "jpg"

    # PNG
    if data.startswith(b"\x89PNG"):
        return "png"

    if "image/png" in content_type:
        return "png"

    if clean_url.endswith(".png"):
        return "png"

    # WEBP
    if (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):
        return "webp"

    if "image/webp" in content_type:
        return "webp"

    if clean_url.endswith(".webp"):
        return "webp"

    return "unknown"


# ============================================================
# FFMPEG IMAGE COMPRESSION
# ============================================================

def compress_image(data):

    original_size = len(data)

    print()
    print("Preparing image for Telegram...")

    print(
        f"Original size: "
        f"{original_size / 1024 / 1024:.2f} MB"
    )

    # Already small enough.
    if original_size <= TELEGRAM_IMAGE_LIMIT:

        print(
            "Image is already small enough."
        )

        return data, "jpg"

    print(
        "Image is too large."
    )

    print(
        "Compressing with FFmpeg..."
    )

    # Try increasingly smaller JPEG settings.
    attempts = [
        ("90", "1920:-2"),
        ("80", "1920:-2"),
        ("70", "1920:-2"),
        ("60", "1920:-2"),
        ("50", "1600:-2"),
        ("40", "1280:-2"),
        ("35", "1080:-2"),
        ("30", "960:-2"),
    ]

    for quality, scale in attempts:

        try:

            process = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",

                    "-i",
                    "pipe:0",

                    "-vf",
                    f"scale={scale}:force_original_aspect_ratio=decrease",

                    "-frames:v",
                    "1",

                    "-q:v",
                    quality,

                    "-f",
                    "image2",

                    "pipe:1",
                ],
                input=data,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60
            )

            output = process.stdout

            if not output:
                continue

            size_mb = (
                len(output)
                / 1024
                / 1024
            )

            print(
                f"Compression attempt "
                f"quality={quality}, "
                f"scale={scale}: "
                f"{size_mb:.2f} MB"
            )

            if len(output) <= TELEGRAM_IMAGE_LIMIT:

                print(
                    "Image compressed successfully."
                )

                print(
                    f"Final size: "
                    f"{size_mb:.2f} MB"
                )

                return output, "jpg"

        except Exception as error:

            print(
                f"FFmpeg compression attempt "
                f"failed: {error}"
            )

    print(
        "Could not compress image enough "
        "for Telegram.",
        file=sys.stderr
    )

    return None, ""


# ============================================================
# HASH
# ============================================================

def media_hash(data):

    return hashlib.sha256(
        data
    ).hexdigest()


# ============================================================
# FETCH REDDIT
# ============================================================

def fetch_candidate_posts():

    if not SUBREDDITS:

        print(
            "ERROR: No subreddits configured.",
            file=sys.stderr
        )

        return []

    amount = min(
        SUBREDDITS_PER_RUN,
        len(SUBREDDITS)
    )

    chosen = random.sample(
        SUBREDDITS,
        amount
    )

    print()
    print("Checking subreddits:")

    for subreddit in chosen:

        print(
            f"  r/{subreddit}"
        )

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
                    "TelegramRedditMediaBot/4.0"
            }
        )

        try:

            with urllib.request.urlopen(
                request,
                timeout=30
            ) as response:

                raw = (
                    response
                    .read()
                    .decode("utf-8")
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
            "========================================"
        )

        print(
            f"SEARCH BATCH "
            f"{attempt}/{FETCH_ATTEMPTS}"
        )

        print(
            "========================================"
        )

        posts = fetch_candidate_posts()

        if not posts:

            time.sleep(2)

            continue

        random.shuffle(
            posts
        )

        for post in posts:

            url = post.get(
                "url"
            )

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
                f"Detected type: "
                f"{media_type}"
            )

            if media_type == "unknown":

                print(
                    "Skipped: unsupported media."
                )

                continue

            digest = media_hash(
                media_data
            )

            if digest in seen_hashes:

                print(
                    "Skipped: exact media "
                    "was already posted."
                )

                continue

            print()
            print(
                "========================================"
            )

            print(
                "NEW MEDIA FOUND!"
            )

            print(
                f"Type: {media_type}"
            )

            print(
                f"Subreddit: "
                f"r/{post.get('subreddit', 'unknown')}"
            )

            print(
                "========================================"
            )

            # ------------------------------------------------
            # Compress normal images
            # ------------------------------------------------

            if media_type in (
                "jpg",
                "png",
                "webp"
            ):

                compressed, new_type = (
                    compress_image(
                        media_data
                    )
                )

                if compressed is None:

                    continue

                media_data = compressed

                media_type = new_type

            post["_media_data"] = media_data

            post["_media_type"] = media_type

            post["_media_hash"] = digest

            return post

        print(
            "No new media found in this batch."
        )

    return None


# ============================================================
# MULTIPART
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
# TELEGRAM SEND
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
        "----TelegramRedditBot"
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
        timeout=120
    ) as response:

        return json.loads(
            response
            .read()
            .decode()
        )


# ============================================================
# SEND TO TELEGRAM
# ============================================================

def send_to_telegram(post):

    media_data = post.get(
        "_media_data"
    )

    media_type = post.get(
        "_media_type"
    )

    if not media_data:

        print(
            "ERROR: Media data missing.",
            file=sys.stderr
        )

        return False

    print()
    print(
        "========================================"
    )

    print(
        "UPLOADING TO TELEGRAM"
    )

    print(
        f"Media type: {media_type}"
    )

    print(
        f"Upload size: "
        f"{len(media_data) / 1024 / 1024:.2f} MB"
    )

    print(
        "========================================"
    )

    try:

        if media_type == "gif":

            print(
                "Sending GIF with sendAnimation..."
            )

            result = telegram_upload(
                "sendAnimation",
                "animation",
                "animation.gif",
                "image/gif",
                media_data
            )

        elif media_type == "video":

            print(
                "Sending video with sendVideo..."
            )

            result = telegram_upload(
                "sendVideo",
                "video",
                "video.mp4",
                "video/mp4",
                media_data
            )

        else:

            print(
                "Sending image with sendPhoto..."
            )

            result = telegram_upload(
                "sendPhoto",
                "photo",
                "image.jpg",
                "image/jpeg",
                media_data
            )

        if not result.get("ok"):

            print()
            print(
                "Telegram error:"
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
            "       POSTED SUCCESSFULLY"
        )

        print(
            "========================================"
        )

        print(
            f"Type: {media_type}"
        )

        print(
            f"Subreddit: "
            f"r/{post.get('subreddit', 'unknown')}"
        )

        print(
            f"URL: {post.get('url')}"
        )

        print(
            "Duplicate hash: SAVED"
        )

        print(
            "========================================"
        )

        return True

    except urllib.error.HTTPError as error:

        details = error.read().decode(
            "utf-8",
            errors="ignore"
        )

        print(
            f"Telegram HTTP {error.code}:",
            file=sys.stderr
        )

        print(
            details,
            file=sys.stderr
        )

        return False

    except Exception as error:

        print(
            f"Telegram error: {error}",
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
        "       REDDIT → TELEGRAM BOT"
    )

    print(
        "       IMAGE + GIF + VIDEO"
    )

    print(
        "       EVERY ~30 MINUTES"
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

    print()
    print(
        f"Stored URLs: "
        f"{len(history['urls'])}"
    )

    print(
        f"Stored Reddit IDs: "
        f"{len(history['ids'])}"
    )

    print(
        f"Stored media hashes: "
        f"{len(history['hashes'])}"
    )

    post = find_new_media(
        history
    )

    if not post:

        print()
        print(
            "No new media was found this run."
        )

        return

    if not send_to_telegram(post):

        print()
        print(
            "Posting failed."
        )

        print(
            "posted.json was NOT changed."
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

    save_history(
        history
    )

    print()
    print(
        "posted.json updated."
    )

    print(
        "Finished successfully."
    )


if __name__ == "__main__":
    main()
