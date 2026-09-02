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
import io

from PIL import Image


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

# Reddit download limit
MAX_MEDIA_SIZE = 50 * 1024 * 1024

# Telegram photo limit safety target.
# Keep comfortably below 10 MB.
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
# DOWNLOAD MEDIA
# ============================================================

def download_media(media_url):

    try:

        print()
        print(
            "Downloading media:"
        )
        print(
            media_url
        )

        request = urllib.request.Request(
            media_url,
            headers={
                "User-Agent":
                    "TelegramRedditMediaBot/3.0"
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

            content_length = (
                response.headers.get(
                    "Content-Length"
                )
            )

            if content_length:

                try:

                    size = int(
                        content_length
                    )

                    if size > MAX_MEDIA_SIZE:

                        print(
                            "Skipped: media is larger "
                            "than 50 MB."
                        )

                        return None, ""

                except ValueError:

                    pass

            data = response.read(
                MAX_MEDIA_SIZE + 1
            )

            if len(data) > MAX_MEDIA_SIZE:

                print(
                    "Skipped: media is larger "
                    "than 50 MB."
                )

                return None, ""

            if not data:

                print(
                    "Skipped: empty download."
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

    except urllib.error.HTTPError as error:

        print(
            f"Download HTTP error "
            f"{error.code}: {error.reason}",
            file=sys.stderr
        )

        return None, ""

    except urllib.error.URLError as error:

        print(
            f"Download connection error: {error}",
            file=sys.stderr
        )

        return None, ""

    except Exception as error:

        print(
            f"Media download failed: {error}",
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
        url
        .lower()
        .split("?")[0]
        .split("#")[0]
    )

    content_type = (
        content_type
        or ""
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
    # MP4 / MOV / WEBM
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # JPEG
    # --------------------------------------------------------

    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"

    if "image/jpeg" in content_type:
        return "jpg"

    if clean_url.endswith(".jpg"):
        return "jpg"

    if clean_url.endswith(".jpeg"):
        return "jpg"

    # --------------------------------------------------------
    # PNG
    # --------------------------------------------------------

    if data.startswith(b"\x89PNG"):
        return "png"

    if "image/png" in content_type:
        return "png"

    if clean_url.endswith(".png"):
        return "png"

    # --------------------------------------------------------
    # WEBP
    # --------------------------------------------------------

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
# IMAGE COMPRESSION
# ============================================================

def compress_image_for_telegram(
    image_data,
    media_type
):
    """
    Telegram photos must stay below the upload limit.

    Large PNG/WebP/JPEG files are automatically converted
    to JPEG and compressed until they are safely below
    the limit.

    GIFs are NOT passed through this function.
    """

    original_size = len(
        image_data
    )

    print()
    print(
        "Preparing image for Telegram..."
    )

    print(
        f"Original size: "
        f"{original_size / 1024 / 1024:.2f} MB"
    )

    # --------------------------------------------------------
    # Already small enough
    # --------------------------------------------------------

    if (
        original_size
        <= TELEGRAM_IMAGE_LIMIT
        and media_type in (
            "jpg",
            "png"
        )
    ):

        print(
            "Image is already small enough."
        )

        return (
            image_data,
            media_type
        )

    # --------------------------------------------------------
    # Open image
    # --------------------------------------------------------

    try:

        image = Image.open(
            io.BytesIO(
                image_data
            )
        )

        print(
            f"Image size: "
            f"{image.width}x{image.height}"
        )

        # ----------------------------------------------------
        # Convert transparency safely
        # ----------------------------------------------------

        if image.mode in (
            "RGBA",
            "LA",
            "P"
        ):

            background = Image.new(
                "RGB",
                image.size,
                "white"
            )

            if image.mode == "P":

                image = image.convert(
                    "RGBA"
                )

            if image.mode in (
                "RGBA",
                "LA"
            ):

                background.paste(
                    image,
                    mask=image.getchannel(
                        "A"
                    )
                )

                image = background

            else:

                image = image.convert(
                    "RGB"
                )

        else:

            image = image.convert(
                "RGB"
            )

        # ----------------------------------------------------
        # Start with original dimensions
        # ----------------------------------------------------

        working = image

        # ----------------------------------------------------
        # Try several JPEG qualities
        # ----------------------------------------------------

        qualities = [
            90,
            85,
            80,
            75,
            70,
            65,
            60,
            55,
            50,
            45,
            40,
        ]

        for quality in qualities:

            output = io.BytesIO()

            working.save(
                output,
                format="JPEG",
                quality=quality,
                optimize=True
            )

            compressed = (
                output.getvalue()
            )

            size_mb = (
                len(compressed)
                / 1024
                / 1024
            )

            print(
                f"JPEG quality {quality}: "
                f"{size_mb:.2f} MB"
            )

            if (
                len(compressed)
                <= TELEGRAM_IMAGE_LIMIT
            ):

                print(
                    "Image compressed successfully."
                )

                print(
                    f"Final size: "
                    f"{size_mb:.2f} MB"
                )

                return (
                    compressed,
                    "jpg"
                )

        # ----------------------------------------------------
        # Still too large:
        # resize gradually
        # ----------------------------------------------------

        print(
            "Image is still too large."
        )

        print(
            "Reducing dimensions..."
        )

        width = working.width
        height = working.height

        for scale in (
            0.85,
            0.70,
            0.55,
            0.45,
            0.35
        ):

            new_width = max(
                320,
                int(
                    width * scale
                )
            )

            new_height = max(
                320,
                int(
                    height * scale
                )
            )

            resized = working.resize(
                (
                    new_width,
                    new_height
                ),
                Image.Resampling.LANCZOS
            )

            for quality in (
                75,
                65,
                55,
                45
            ):

                output = io.BytesIO()

                resized.save(
                    output,
                    format="JPEG",
                    quality=quality,
                    optimize=True
                )

                compressed = (
                    output.getvalue()
                )

                size_mb = (
                    len(compressed)
                    / 1024
                    / 1024
                )

                print(
                    f"Resize {new_width}x"
                    f"{new_height}, "
                    f"quality {quality}: "
                    f"{size_mb:.2f} MB"
                )

                if (
                    len(compressed)
                    <= TELEGRAM_IMAGE_LIMIT
                ):

                    print(
                        "Image resized and "
                        "compressed successfully."
                    )

                    print(
                        f"Final size: "
                        f"{size_mb:.2f} MB"
                    )

                    return (
                        compressed,
                        "jpg"
                    )

        print(
            "Could not compress image "
            "enough for Telegram.",
            file=sys.stderr
        )

        return None, ""

    except Exception as error:

        print(
            f"Image compression failed: "
            f"{error}",
            file=sys.stderr
        )

        return None, ""


# ============================================================
# MEDIA HASH
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

    print()
    print(
        "Checking subreddits:"
    )

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
                    "TelegramRedditMediaBot/3.0"
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

        except urllib.error.HTTPError as error:

            print(
                f"r/{subreddit}: "
                f"HTTP {error.code}",
                file=sys.stderr
            )

        except urllib.error.URLError as error:

            print(
                f"r/{subreddit}: "
                f"connection error: {error}",
                file=sys.stderr
            )

        except json.JSONDecodeError:

            print(
                f"r/{subreddit}: "
                f"invalid API response",
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

            print(
                "No Reddit posts returned."
            )

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

            # ------------------------------------------------
            # URL duplicate
            # ------------------------------------------------

            if url in seen_urls:

                print(
                    "Skipped: duplicate URL."
                )

                continue

            # ------------------------------------------------
            # Reddit duplicate
            # ------------------------------------------------

            if (
                post_id
                and post_id in seen_ids
            ):

                print(
                    "Skipped: duplicate Reddit post."
                )

                continue

            # ------------------------------------------------
            # DOWNLOAD
            # ------------------------------------------------

            media_data, content_type = (
                download_media(
                    url
                )
            )

            if media_data is None:

                print(
                    "Skipped: download failed."
                )

                continue

            # ------------------------------------------------
            # DETECT TYPE
            # ------------------------------------------------

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
                    "Skipped: unsupported "
                    "media format."
                )

                continue

            # ------------------------------------------------
            # HASH ORIGINAL MEDIA
            # ------------------------------------------------

            digest = media_hash(
                media_data
            )

            if digest in seen_hashes:

                print(
                    "Skipped: exact media "
                    "was already posted."
                )

                continue

            # ------------------------------------------------
            # NEW MEDIA
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
                f"Subreddit: "
                f"r/{post.get('subreddit', 'unknown')}"
            )

            print(
                "========================================"
            )

            # ------------------------------------------------
            # COMPRESS LARGE IMAGES
            # ------------------------------------------------

            if media_type in (
                "jpg",
                "png",
                "webp"
            ):

                compressed_data, compressed_type = (
                    compress_image_for_telegram(
                        media_data,
                        media_type
                    )
                )

                if (
                    compressed_data is None
                    or not compressed_type
                ):

                    print(
                        "Skipped: image could not "
                        "be prepared for Telegram."
                    )

                    continue

                media_data = (
                    compressed_data
                )

                media_type = (
                    compressed_type
                )

            # ------------------------------------------------
            # STORE
            # ------------------------------------------------

            post["_media_data"] = (
                media_data
            )

            post["_media_type"] = (
                media_type
            )

            post["_content_type"] = (
                content_type
            )

            post["_media_hash"] = (
                digest
            )

            return post

        print()
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
    ).encode(
        "utf-8"
    )


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
    ).encode(
        "utf-8"
    )

    return (
        header
        + data
        + b"\r\n"
    )


# ============================================================
# TELEGRAM PHOTO
# ============================================================

def send_photo(
    media_data,
    media_type
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

    if media_type == "png":

        filename = "image.png"

        content_type = "image/png"

    else:

        filename = "image.jpg"

        content_type = "image/jpeg"

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
            filename,
            content_type,
            media_data
        )
    )

    body.extend(
        f"--{boundary}--\r\n".encode(
            "utf-8"
        )
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
            response
            .read()
            .decode("utf-8")
        )


# ============================================================
# TELEGRAM GIF
# ============================================================

def send_gif(
    media_data
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
            "animation.gif",
            "image/gif",
            media_data
        )
    )

    body.extend(
        f"--{boundary}--\r\n".encode(
            "utf-8"
        )
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
        timeout=120
    ) as response:

        return json.loads(
            response
            .read()
            .decode("utf-8")
        )


# ============================================================
# TELEGRAM VIDEO
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
        f"--{boundary}--\r\n".encode(
            "utf-8"
        )
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
        timeout=120
    ) as response:

        return json.loads(
            response
            .read()
            .decode("utf-8")
        )


# ============================================================
# TELEGRAM SEND
# ============================================================

def send_to_telegram(post):

    if not BOT_TOKEN:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN "
            "is missing.",
            file=sys.stderr
        )

        return False

    if not CHAT_ID:

        print(
            "ERROR: TELEGRAM_CHAT_ID "
            "is missing.",
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

        # ----------------------------------------------------
        # GIF
        # ----------------------------------------------------

        if media_type == "gif":

            print(
                "Sending GIF with sendAnimation..."
            )

            result = send_gif(
                media_data
            )

        # ----------------------------------------------------
        # VIDEO
        # ----------------------------------------------------

        elif media_type == "video":

            print(
                "Sending video with sendVideo..."
            )

            result = send_video(
                media_data
            )

        # ----------------------------------------------------
        # IMAGE
        # ----------------------------------------------------

        elif media_type in (
            "jpg",
            "png"
        ):

            print(
                "Sending image with sendPhoto..."
            )

            result = send_photo(
                media_data,
                media_type
            )

        else:

            print(
                "Unsupported media type.",
                file=sys.stderr
            )

            return False

        # ----------------------------------------------------
        # TELEGRAM RESULT
        # ----------------------------------------------------

        if not result.get("ok"):

            print()
            print(
                "Telegram API returned an error:"
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
            "Caption: NONE"
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

        print()
        print(
            f"Telegram HTTP {error.code}:"
        )

        print(
            details,
            file=sys.stderr
        )

        return False

    except urllib.error.URLError as error:

        print(
            f"Telegram connection error: "
            f"{error}",
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

    # --------------------------------------------------------
    # CHECK TOKEN
    # --------------------------------------------------------

    if not BOT_TOKEN:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN "
            "is missing.",
            file=sys.stderr
        )

        sys.exit(1)

    # --------------------------------------------------------
    # CHECK CHAT
    # --------------------------------------------------------

    if not CHAT_ID:

        print(
            "ERROR: TELEGRAM_CHAT_ID "
            "is missing.",
            file=sys.stderr
        )

        sys.exit(1)

    # --------------------------------------------------------
    # CHECK SUBREDDITS
    # --------------------------------------------------------

    if not SUBREDDITS:

        print(
            "ERROR: SUBREDDITS is empty.",
            file=sys.stderr
        )

        sys.exit(1)

    # --------------------------------------------------------
    # HISTORY
    # --------------------------------------------------------

    history = load_history()

    print()
    print(
        "Duplicate history:"
    )

    print(
        f"  URLs: "
        f"{len(history['urls'])}"
    )

    print(
        f"  Reddit IDs: "
        f"{len(history['ids'])}"
    )

    print(
        f"  Media hashes: "
        f"{len(history['hashes'])}"
    )

    # --------------------------------------------------------
    # FIND
    # --------------------------------------------------------

    post = find_new_media(
        history
    )

    if not post:

        print()
        print(
            "========================================"
        )

        print(
            "NO NEW MEDIA FOUND"
        )

        print(
            "========================================"
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
            "posted.json was NOT changed."
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
