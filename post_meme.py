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

# Keep this list to SFW subreddits.
SUBREDDITS = [
    "nsfwanimegifs",
    "ecchi",
    "OverOppai",
    "CFNM_Hentai",
    "EcchiCurves",
]


# ============================================================
# SETTINGS
# ============================================================

SUBREDDITS_PER_RUN = 2
MEMES_PER_SUBREDDIT = 50
HISTORY_LIMIT = 5000
FETCH_ATTEMPTS = 8

MAX_MEDIA_SIZE = 50 * 1024 * 1024

# Telegram multipart photo uploads support up to 10 MB.
# We deliberately target below that limit.
TELEGRAM_IMAGE_LIMIT = 9 * 1024 * 1024

# Telegram animation uploads support up to 50 MB.
TELEGRAM_ANIMATION_LIMIT = 49 * 1024 * 1024

MEME_API_URL = (
    "https://meme-api.com/gimme/{subreddit}/{count}"
)

REDDIT_JSON_URL = (
    "https://www.reddit.com/r/{subreddit}/new.json"
)

USER_AGENT = (
    "SFWRedditTelegramBot/6.0 "
    "(GitHub Actions automation)"
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

    temp_file = (
        HISTORY_FILE + ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            history,
            file,
            indent=2
        )

    os.replace(
        temp_file,
        HISTORY_FILE
    )


# ============================================================
# HTTP GET JSON WITH RETRIES
# ============================================================

def get_json(
    url,
    attempts=4
):

    last_error = None

    for attempt in range(
        1,
        attempts + 1
    ):

        try:

            print(
                f"HTTP request "
                f"{attempt}/{attempts}: "
                f"{url}"
            )

            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Accept-Language": "en-US,en;q=0.9",
                }
            )

            with urllib.request.urlopen(
                request,
                timeout=30
            ) as response:

                status = response.getcode()

                raw = response.read()

                content = raw.decode(
                    "utf-8",
                    errors="replace"
                )

            if status != 200:

                raise RuntimeError(
                    f"HTTP {status}"
                )

            return json.loads(
                content
            )

        except urllib.error.HTTPError as error:

            last_error = (
                f"HTTP {error.code}: "
                f"{error.reason}"
            )

            # Retry common temporary gateway errors.
            if error.code in (
                429,
                500,
                502,
                503,
                504,
                530
            ):

                wait = min(
                    2 ** attempt,
                    15
                )

                print(
                    f"Temporary server error: "
                    f"{last_error}"
                )

                print(
                    f"Waiting {wait} seconds..."
                )

                time.sleep(
                    wait
                )

                continue

            print(
                f"Request failed: "
                f"{last_error}",
                file=sys.stderr
            )

            return None

        except urllib.error.URLError as error:

            last_error = (
                f"Connection error: {error}"
            )

            wait = min(
                2 ** attempt,
                15
            )

            print(
                last_error,
                file=sys.stderr
            )

            if attempt < attempts:

                print(
                    f"Waiting {wait} seconds..."
                )

                time.sleep(
                    wait
                )

                continue

        except json.JSONDecodeError as error:

            last_error = (
                f"Invalid JSON: {error}"
            )

            print(
                last_error,
                file=sys.stderr
            )

            return None

        except Exception as error:

            last_error = str(
                error
            )

            wait = min(
                2 ** attempt,
                15
            )

            print(
                f"Request error: "
                f"{error}",
                file=sys.stderr
            )

            if attempt < attempts:

                time.sleep(
                    wait
                )

                continue

    print(
        f"All HTTP attempts failed: "
        f"{last_error}",
        file=sys.stderr
    )

    return None


# ============================================================
# MEME API SOURCE
# ============================================================

def fetch_from_meme_api(
    subreddit
):

    encoded = urllib.parse.quote(
        subreddit
    )

    url = MEME_API_URL.format(
        subreddit=encoded,
        count=min(
            MEMES_PER_SUBREDDIT,
            50
        )
    )

    data = get_json(
        url,
        attempts=4
    )

    if not data:

        return []

    posts = data.get(
        "memes",
        []
    )

    if not isinstance(
        posts,
        list
    ):

        return []

    print(
        f"Meme API returned "
        f"{len(posts)} posts for "
        f"r/{subreddit}"
    )

    # Normalize "nsfw" spelling used by Meme API.
    for post in posts:

        if isinstance(post, dict):

            post["_source"] = (
                "meme-api"
            )

    return posts


# ============================================================
# REDDIT JSON FALLBACK
# ============================================================

def normalize_reddit_post(
    child
):

    if not isinstance(
        child,
        dict
    ):

        return None

    data = child.get(
        "data",
        {}
    )

    if not isinstance(
        data,
        dict
    ):

        return None

    post_id = data.get(
        "id"
    )

    permalink = data.get(
        "permalink"
    )

    if permalink:

        post_link = (
            "https://www.reddit.com"
            + permalink
        )

    elif post_id:

        post_link = (
            "https://redd.it/"
            + str(post_id)
        )

    else:

        post_link = ""

    url = (
        data.get(
            "url_overridden_by_dest"
        )
        or data.get(
            "url"
        )
        or ""
    )

    if not url:

        return None

    return {
        "postLink": post_link,
        "subreddit": data.get(
            "subreddit",
            ""
        ),
        "title": data.get(
            "title",
            ""
        ),
        "url": url,
        "nsfw": bool(
            data.get(
                "over_18",
                False
            )
        ),
        "spoiler": bool(
            data.get(
                "spoiler",
                False
            )
        ),
        "author": data.get(
            "author",
            ""
        ),
        "ups": data.get(
            "ups",
            0
        ),
        "_source": "reddit-json",
    }


def fetch_from_reddit(
    subreddit
):

    encoded = urllib.parse.quote(
        subreddit
    )

    query = urllib.parse.urlencode(
        {
            "limit": min(
                MEMES_PER_SUBREDDIT,
                100
            ),
            "raw_json": 1,
        }
    )

    url = (
        REDDIT_JSON_URL.format(
            subreddit=encoded
        )
        + "?"
        + query
    )

    data = get_json(
        url,
        attempts=3
    )

    if not data:

        return []

    children = (
        data.get(
            "data",
            {}
        )
        .get(
            "children",
            []
        )
    )

    posts = []

    for child in children:

        post = normalize_reddit_post(
            child
        )

        if post:

            posts.append(
                post
            )

    print(
        f"Reddit fallback returned "
        f"{len(posts)} posts for "
        f"r/{subreddit}"
    )

    return posts


# ============================================================
# FETCH CANDIDATES
# ============================================================

def fetch_candidate_posts():

    if not SUBREDDITS:

        print(
            "ERROR: SUBREDDITS is empty.",
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
    print(
        "Checking subreddits:"
    )

    for subreddit in chosen:

        print(
            f"  r/{subreddit}"
        )

    all_posts = []

    for subreddit in chosen:

        print()
        print(
            f"Getting posts from "
            f"r/{subreddit}..."
        )

        # ----------------------------------------------------
        # Primary source
        # ----------------------------------------------------

        posts = fetch_from_meme_api(
            subreddit
        )

        # ----------------------------------------------------
        # Fallback source
        # ----------------------------------------------------

        if not posts:

            print(
                "Meme API unavailable."
            )

            print(
                "Trying Reddit JSON fallback..."
            )

            posts = fetch_from_reddit(
                subreddit
            )

        if posts:

            all_posts.extend(
                posts
            )

        else:

            print(
                f"Could not retrieve "
                f"r/{subreddit}."
            )

    return all_posts


# ============================================================
# DOWNLOAD MEDIA
# ============================================================

def download_media(
    url
):

    print()
    print(
        "Downloading media:"
    )

    print(
        url
    )

    try:

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=60
        ) as response:

            content_type = (
                response
                .headers
                .get(
                    "Content-Type",
                    ""
                )
                .lower()
            )

            data = response.read(
                MAX_MEDIA_SIZE + 1
            )

        if len(data) > (
            MAX_MEDIA_SIZE
        ):

            print(
                "Skipped: media exceeds "
                "50 MB."
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
            f"Content-Type: "
            f"{content_type}"
        )

        return data, content_type

    except Exception as error:

        print(
            f"Download failed: "
            f"{error}",
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
        content_type or ""
    ).lower()

    # GIF
    if data.startswith(
        b"GIF87a"
    ):

        return "gif"

    if data.startswith(
        b"GIF89a"
    ):

        return "gif"

    if "image/gif" in content_type:

        return "gif"

    if clean_url.endswith(
        ".gif"
    ):

        return "gif"

    # MP4 / MOV
    if (
        len(data) >= 12
        and data[4:8] == b"ftyp"
    ):

        return "animated_video"

    if content_type.startswith(
        "video/"
    ):

        return "animated_video"

    if clean_url.endswith(
        (
            ".mp4",
            ".m4v",
            ".mov",
            ".webm"
        )
    ):

        return "animated_video"

    # JPEG / PNG / WEBP
    if data.startswith(
        b"\xff\xd8\xff"
    ):

        return "photo"

    if data.startswith(
        b"\x89PNG"
    ):

        return "photo"

    if (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):

        return "photo"

    if content_type.startswith(
        "image/"
    ):

        return "photo"

    if clean_url.endswith(
        (
            ".jpg",
            ".jpeg",
            ".png",
            ".webp"
        )
    ):

        return "photo"

    return "unknown"


# ============================================================
# TEMP FILE
# ============================================================

def save_temp_file(
    data,
    suffix
):

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
# CONVERT ANIMATION TO MP4
# ============================================================

def convert_to_animation_mp4(
    data
):

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

            # No audio for Telegram animation.
            "-an",

            # Keep dimensions reasonable.
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

            error_text = (
                result.stderr.decode(
                    "utf-8",
                    errors="ignore"
                )
            )

            print(
                "FFmpeg animation conversion failed:"
            )

            print(
                error_text[-3000:],
                file=sys.stderr
            )

            return None

        if not os.path.exists(
            output
        ):

            return None

        with open(
            output,
            "rb"
        ) as file:

            converted = file.read()

        size_mb = (
            len(converted)
            / 1024
            / 1024
        )

        print(
            f"Animation MP4: "
            f"{size_mb:.2f} MB"
        )

        if len(converted) > (
            TELEGRAM_ANIMATION_LIMIT
        ):

            print(
                "Animation exceeds "
                "Telegram limit."
            )

            return None

        return converted

    except Exception as error:

        print(
            f"Animation conversion "
            f"failed: {error}",
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

def compress_photo(
    data
):

    if len(data) <= (
        TELEGRAM_IMAGE_LIMIT
    ):

        return data

    print()
    print(
        "Large image detected."
    )

    print(
        "Compressing with FFmpeg..."
    )

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
            ("35", "800:-2"),
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
                f"Quality {quality}: "
                f"{size_mb:.2f} MB"
            )

            if len(output) <= (
                TELEGRAM_IMAGE_LIMIT
            ):

                print(
                    "Image compressed."
                )

                return output

        print(
            "Could not compress "
            "image enough.",
            file=sys.stderr
        )

        return None

    finally:

        try:
            os.remove(source)
        except Exception:
            pass


# ============================================================
# HASH
# ============================================================

def media_hash(
    data
):

    return hashlib.sha256(
        data
    ).hexdigest()


# ============================================================
# FIND NEW MEDIA
# ============================================================

def find_new_media(
    history
):

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
                "No posts received."
            )

            if attempt < FETCH_ATTEMPTS:

                time.sleep(3)

                continue

            break

        random.shuffle(
            posts
        )

        for post in posts:

            if not is_sfw_post(
                post
            ):

                continue

            url = post.get(
                "url"
            )

            post_id = post.get(
                "postLink",
                ""
            )

            if not url:
                continue

            # URL duplicate.
            if url in seen_urls:

                print(
                    "Skipped duplicate URL."
                )

                continue

            # Reddit duplicate.
            if (
                post_id
                and post_id in seen_ids
            ):

                print(
                    "Skipped duplicate Reddit post."
                )

                continue

            media_data, content_type = (
                download_media(
                    url
                )
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
            # PHOTO
            # ------------------------------------------------

            if media_type == "photo":

                prepared = compress_photo(
                    media_data
                )

                if prepared is None:

                    continue

                telegram_type = "photo"

            # ------------------------------------------------
            # REAL GIF
            # ------------------------------------------------

            elif media_type == "gif":

                prepared = media_data

                telegram_type = "gif"

            # ------------------------------------------------
            # MP4/WEBM ANIMATION
            # ------------------------------------------------

            elif media_type == "animated_video":

                prepared = (
                    convert_to_animation_mp4(
                        media_data
                    )
                )

                if prepared is None:

                    continue

                telegram_type = (
                    "animation_mp4"
                )

            else:

                continue

            post["_media_data"] = (
                prepared
            )

            post["_media_type"] = (
                telegram_type
            )

            post["_media_hash"] = (
                digest
            )

            print()
            print(
                "========================================"
            )

            print(
                "NEW MEDIA FOUND"
            )

            print(
                f"Subreddit: "
                f"r/{post.get('subreddit', '')}"
            )

            print(
                f"Original type: "
                f"{media_type}"
            )

            print(
                f"Telegram type: "
                f"{telegram_type}"
            )

            print(
                "========================================"
            )

            return post

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
# SEND TO TELEGRAM
# ============================================================

def send_to_telegram(
    post
):

    data = post.get(
        "_media_data"
    )

    media_type = post.get(
        "_media_type"
    )

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

        # ----------------------------------------------------
        # PHOTO
        # ----------------------------------------------------

        if media_type == "photo":

            result = telegram_upload(
                "sendPhoto",
                "photo",
                "image.jpg",
                "image/jpeg",
                data
            )

        # ----------------------------------------------------
        # REAL GIF
        # ----------------------------------------------------

        elif media_type == "gif":

            print(
                "Using Telegram sendAnimation "
                "for GIF."
            )

            result = telegram_upload(
                "sendAnimation",
                "animation",
                "animation.gif",
                "image/gif",
                data
            )

        # ----------------------------------------------------
        # MP4 ANIMATION
        # ----------------------------------------------------

        elif media_type == "animation_mp4":

            print(
                "Using Telegram sendAnimation "
                "for MP4 animation."
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
                "Unsupported Telegram type."
            )

            return False

        if not result.get(
            "ok"
        ):

            print()
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
        "SFW PHOTO + GIF + ANIMATION"
    )

    print(
        "========================================"
    )

    if not BOT_TOKEN:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN "
            "is missing.",
            file=sys.stderr
        )

        sys.exit(1)

    if not CHAT_ID:

        print(
            "ERROR: TELEGRAM_CHAT_ID "
            "is missing.",
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

    if not send_to_telegram(
        post
    ):

        print()
        print(
            "Posting failed."
        )

        print(
            "posted.json was NOT changed."
        )

        return

    # --------------------------------------------------------
    # SAVE HISTORY ONLY AFTER TELEGRAM SUCCESS
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
