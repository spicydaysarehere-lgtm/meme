#!/usr/bin/env python3

import os
import sys
import json
import time
import random
import hashlib
import tempfile
import mimetypes
import urllib.request
import urllib.error
import urllib.parse


# ============================================================
# SUBREDDITS
# ============================================================

SUBREDDITS = [
    "HENTAI_GIF",
]


# ============================================================
# SETTINGS
# ============================================================

SUBREDDITS_PER_RUN = 2

MEMES_PER_SUBREDDIT = 50

HISTORY_LIMIT = 5000

FETCH_ATTEMPTS = 8

# Maximum downloaded media size.
# Telegram supports considerably larger files, but keeping
# this limit prevents a huge Reddit file from consuming the
# GitHub Actions runner.
MAX_MEDIA_SIZE = 50 * 1024 * 1024

MEME_API_URL = "https://meme-api.com/gimme/{subreddit}/{count}"


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
                "urls": data.get(
                    "urls",
                    []
                ),
                "ids": data.get(
                    "ids",
                    []
                ),
                "hashes": data.get(
                    "hashes",
                    []
                )
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

    try:

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

    except Exception as error:

        print(
            f"Could not save posted.json: {error}",
            file=sys.stderr
        )


# ============================================================
# DOWNLOAD REDDIT MEDIA
# ============================================================

def download_media(media_url):

    try:

        print(
            f"Downloading: {media_url}"
        )

        request = urllib.request.Request(
            media_url,
            headers={
                "User-Agent":
                    "TelegramRedditMediaBot/2.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=40
        ) as response:

            content_type = (
                response.headers.get(
                    "Content-Type",
                    ""
                )
                .lower()
            )

            content_length = (
                response.headers.get(
                    "Content-Length"
                )
            )

            if content_length:

                try:

                    if (
                        int(content_length)
                        > MAX_MEDIA_SIZE
                    ):

                        print(
                            "Skipped: media is too large."
                        )

                        return None, None

                except ValueError:
                    pass

            data = response.read(
                MAX_MEDIA_SIZE + 1
            )

            if len(data) > MAX_MEDIA_SIZE:

                print(
                    "Skipped: media is too large."
                )

                return None, None

            if not data:

                print(
                    "Skipped: empty download."
                )

                return None, None

            return data, content_type

    except Exception as error:

        print(
            f"Media download failed: {error}",
            file=sys.stderr
        )

        return None, None


# ============================================================
# MEDIA TYPE DETECTION
# ============================================================

def detect_media_type(
    url,
    data,
    content_type=""
):

    url_lower = (
        url.lower()
        .split("?")[0]
    )

    content_type = (
        content_type
        or ""
    ).lower()

    # --------------------------------------------------------
    # GIF
    # --------------------------------------------------------

    if data.startswith(
        b"GIF87a"
    ) or data.startswith(
        b"GIF89a"
    ):

        return "gif"

    if (
        "image/gif"
        in content_type
    ):

        return "gif"

    if url_lower.endswith(
        ".gif"
    ):

        return "gif"

    # --------------------------------------------------------
    # MP4 / MOV
    # --------------------------------------------------------

    # MP4 files normally contain "ftyp" around byte 4.
    if (
        len(data) >= 12
        and data[4:8] == b"ftyp"
    ):

        return "video"

    if (
        content_type.startswith(
            "video/"
        )
    ):

        return "video"

    if any(
        url_lower.endswith(ext)
        for ext in [
            ".mp4",
            ".m4v",
            ".mov",
            ".webm",
            ".avi",
            ".mkv"
        ]
    ):

        return "video"

    # --------------------------------------------------------
    # Images
    # --------------------------------------------------------

    if (
        data.startswith(b"\xff\xd8\xff")
    ):

        return "photo"

    if data.startswith(
        b"\x89PNG"
    ):

        return "photo"

    if data.startswith(
        b"RIFF"
    ) and b"WEBP" in data[:16]:

        return "photo"

    if (
        content_type.startswith(
            "image/"
        )
        and "gif"
        not in content_type
    ):

        return "photo"

    if any(
        url_lower.endswith(ext)
        for ext in [
            ".jpg",
            ".jpeg",
            ".png",
            ".webp"
        ]
    ):

        return "photo"

    # --------------------------------------------------------
    # Unknown
    # --------------------------------------------------------

    return "unknown"


# ============================================================
# HASH
# ============================================================

def media_hash(media_data):

    return hashlib.sha256(
        media_data
    ).hexdigest()


# ============================================================
# FETCH REDDIT POSTS
# ============================================================

def fetch_candidate_posts():

    if not SUBREDDITS:

        print(
            "ERROR: No subreddits configured.",
            file=sys.stderr
        )

        return []

    number_to_choose = min(
        SUBREDDITS_PER_RUN,
        len(SUBREDDITS)
    )

    chosen = random.sample(
        SUBREDDITS,
        number_to_choose
    )

    print(
        "Checking: "
        + ", ".join(
            f"r/{name}"
            for name in chosen
        )
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
                    "TelegramRedditMediaBot/2.0"
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

            data = json.loads(raw)

            posts = data.get(
                "memes",
                []
            )

            if isinstance(
                posts,
                list
            ):

                all_posts.extend(posts)

                print(
                    f"r/{subreddit}: "
                    f"{len(posts)} posts received"
                )

        except urllib.error.HTTPError as error:

            print(
                f"r/{subreddit}: HTTP "
                f"{error.code}",
                file=sys.stderr
            )

        except urllib.error.URLError as error:

            print(
                f"r/{subreddit}: connection error: "
                f"{error}",
                file=sys.stderr
            )

        except json.JSONDecodeError:

            print(
                f"r/{subreddit}: invalid API response",
                file=sys.stderr
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
        history.get(
            "urls",
            []
        )
    )

    seen_ids = set(
        history.get(
            "ids",
            []
        )
    )

    seen_hashes = set(
        history.get(
            "hashes",
            []
        )
    )

    for attempt in range(
        1,
        FETCH_ATTEMPTS + 1
    ):

        print()

        print(
            f"Searching batch "
            f"{attempt}/{FETCH_ATTEMPTS}"
        )

        posts = fetch_candidate_posts()

        if not posts:

            time.sleep(2)

            continue

        random.shuffle(posts)

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

            # ------------------------------------------------
            # URL duplicate
            # ------------------------------------------------

            if url in seen_urls:

                print(
                    "Skipped duplicate URL."
                )

                continue

            # ------------------------------------------------
            # Reddit post duplicate
            # ------------------------------------------------

            if (
                post_id
                and post_id in seen_ids
            ):

                print(
                    "Skipped duplicate Reddit post."
                )

                continue

            # ------------------------------------------------
            # Download
            # ------------------------------------------------

            media_data, content_type = (
                download_media(url)
            )

            if media_data is None:

                print(
                    "Skipped: download failed."
                )

                continue

            # ------------------------------------------------
            # Detect media type
            # ------------------------------------------------

            media_type = detect_media_type(
                url,
                media_data,
                content_type
            )

            print(
                f"Detected media type: "
                f"{media_type}"
            )

            if media_type == "unknown":

                print(
                    "Skipped: unsupported media type."
                )

                continue

            # ------------------------------------------------
            # Hash
            # ------------------------------------------------

            digest = media_hash(
                media_data
            )

            if digest in seen_hashes:

                print(
                    "Skipped: EXACT MEDIA was "
                    "already posted."
                )

                continue

            # ------------------------------------------------
            # New media
            # ------------------------------------------------

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
                "========================================"
            )

            post["_media_hash"] = digest

            post["_media_data"] = media_data

            post["_media_type"] = media_type

            post["_content_type"] = content_type

            return post

        print(
            "No new media found in this batch."
        )

    return None


# ============================================================
# TELEGRAM MULTIPART
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
        f'filename="{filename}"\r\n"
        f"Content-Type: {content_type}\r\n"
        f"\r\n"
    ).encode()

    return (
        header
        + data
        + b"\r\n"
    )


# ============================================================
# TELEGRAM SEND PHOTO
# ============================================================

def send_photo(
    media_data
):

    telegram_url = (
        "https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendPhoto"
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
            "photo",
            "image.jpg",
            "image/jpeg",
            media_data
        )
    )

    body.extend(
        f"--{boundary}--\r\n".encode()
    )

    request = urllib.request.Request(
        telegram_url,
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
        timeout=60
    ) as response:

        return json.loads(
            response.read().decode(
                "utf-8"
            )
        )


# ============================================================
# TELEGRAM SEND ANIMATION
# ============================================================

def send_animation(
    media_data,
    media_type
):

    telegram_url = (
        "https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendAnimation"
    )

    boundary = (
        "----TelegramRedditBot"
        + hashlib.md5(
            os.urandom(16)
        ).hexdigest()
    )

    if media_type == "gif":

        filename = "animation.gif"

        content_type = "image/gif"

    else:

        filename = "animation.mp4"

        content_type = "video/mp4"

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
            "animation",
            filename,
            content_type,
            media_data
        )
    )

    body.extend(
        f"--{boundary}--\r\n".encode()
    )

    request = urllib.request.Request(
        telegram_url,
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
        timeout=90
    ) as response:

        return json.loads(
            response.read().decode(
                "utf-8"
            )
        )


# ============================================================
# TELEGRAM SEND VIDEO FALLBACK
# ============================================================

def send_video(
    media_data
):

    telegram_url = (
        "https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendVideo"
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
            "video",
            "video.mp4",
            "video/mp4",
            media_data
        )
    )

    body.extend(
        f"--{boundary}--\r\n".encode()
    )

    request = urllib.request.Request(
        telegram_url,
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
        timeout=90
    ) as response:

        return json.loads(
            response.read().decode(
                "utf-8"
            )
        )


# ============================================================
# TELEGRAM
# ============================================================

def send_to_telegram(post):

    if not BOT_TOKEN:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN is missing.",
            file=sys.stderr
        )

        return False

    if not CHAT_ID:

        print(
            "ERROR: TELEGRAM_CHAT_ID is missing.",
            file=sys.stderr
        )

        return False

    media_data = post.get(
        "_media_data"
    )

    media_type = post.get(
        "_media_type"
    )

    if not media_data:

        print(
            "ERROR: Media data is missing.",
            file=sys.stderr
        )

        return False

    print()
    print(
        f"Uploading {media_type} to Telegram..."
    )

    try:

        # ----------------------------------------------------
        # NORMAL IMAGE
        # ----------------------------------------------------

        if media_type == "photo":

            print(
                "Using Telegram sendPhoto."
            )

            result = send_photo(
                media_data
            )

        # ----------------------------------------------------
        # GIF
        # ----------------------------------------------------

        elif media_type == "gif":

            print(
                "Using Telegram sendAnimation "
                "for GIF."
            )

            result = send_animation(
                media_data,
                "gif"
            )

        # ----------------------------------------------------
        # VIDEO
        # ----------------------------------------------------

        elif media_type == "video":

            print(
                "Using Telegram sendAnimation "
                "for animated video."
            )

            result = send_animation(
                media_data,
                "video"
            )

            # If Telegram doesn't accept it as an
            # animation, try sendVideo.
            if not result.get("ok"):

                print(
                    "Animation upload rejected."
                )

                print(
                    "Trying Telegram sendVideo..."
                )

                result = send_video(
                    media_data
                )

        else:

            print(
                "Unsupported media type.",
                file=sys.stderr
            )

            return False

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        if not result.get("ok"):

            print(
                "Telegram API error:",
                result,
                file=sys.stderr
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
            f"Telegram HTTP {error.code}: "
            f"{details}",
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
        "       INTERVAL: ~30 MINUTES"
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

    if not SUBREDDITS:

        print(
            "ERROR: SUBREDDITS is empty.",
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
        f"Stored media hashes: "
        f"{len(history['hashes'])}"
    )

    # --------------------------------------------------------
    # FIND NEW MEDIA
    # --------------------------------------------------------

    post = find_new_media(
        history
    )

    if not post:

        print()
        print(
            "No new media was found this run."
        )

        return

    # --------------------------------------------------------
    # SEND
    # --------------------------------------------------------

    success = send_to_telegram(
        post
    )

    if not success:

        print()
        print(
            "Posting failed."
        )

        print(
            "History was NOT changed."
        )

        return

    # --------------------------------------------------------
    # SAVE HISTORY ONLY AFTER SUCCESS
    # --------------------------------------------------------

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


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
