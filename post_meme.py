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
import re
import xml.etree.ElementTree as ET


# ============================================================
# SUBREDDITS
# ============================================================

# ONLY these subreddits are searched.
#
# Add/remove subreddit names here.
#
SUBREDDITS = [
    "nsfwanimegifs",
    "ecchi",
    "OverOppai",
    "CFNM_Hentai",
    "EcchiCurves",
    "animeplot",
]


# ============================================================
# SETTINGS
# ============================================================

# Number of subreddits checked during one search cycle.
SUBREDDITS_PER_SEARCH = 3

# Number of recent RSS posts requested from each subreddit.
POSTS_PER_SUBREDDIT = 25

# Number of times the bot searches again if it cannot find
# the required media type.
SEARCH_ATTEMPTS = 10

# Maximum downloaded media size.
MAX_MEDIA_SIZE = 50 * 1024 * 1024

# Telegram image target.
TELEGRAM_IMAGE_LIMIT = 9 * 1024 * 1024

# Telegram animation target.
TELEGRAM_ANIMATION_LIMIT = 49 * 1024 * 1024

# Delay between failed searches.
SEARCH_DELAY = 3

# Reddit RSS.
#
# Reddit's public RSS feed is used instead of the old
# unauthenticated .json endpoint.
REDDIT_RSS_URL = (
    "https://www.reddit.com/r/{subreddit}/new/.rss"
)

USER_AGENT = (
    "Mozilla/5.0 "
    "(Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36"
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
# HISTORY FILE
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

HISTORY_FILE = os.path.join(
    BASE_DIR,
    "posted.json"
)


# ============================================================
# HISTORY
# ============================================================

def empty_history():

    return {
        "urls": [],
        "ids": [],
        "hashes": [],

        # 0 = image
        # 1 = image
        # 2 = gif
        "next_type": 0
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

        if not isinstance(data, dict):

            return empty_history()

        history = {
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
            ),

            "next_type": data.get(
                "next_type",
                0
            )
        }

        # Make sure next_type is valid.
        if history["next_type"] not in (
            0,
            1,
            2
        ):

            history["next_type"] = 0

        return history

    except Exception as error:

        print(
            f"Could not load posted.json: {error}",
            file=sys.stderr
        )

        return empty_history()


def save_history(history):

    history["urls"] = (
        history.get(
            "urls",
            []
        )[-5000:]
    )

    history["ids"] = (
        history.get(
            "ids",
            []
        )[-5000:]
    )

    history["hashes"] = (
        history.get(
            "hashes",
            []
        )[-5000:]
    )

    temp_file = (
        HISTORY_FILE
        + ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            history,
            file,
            indent=2,
            ensure_ascii=False
        )

    os.replace(
        temp_file,
        HISTORY_FILE
    )


# ============================================================
# HTTP
# ============================================================

def http_get(
    url,
    attempts=4
):

    last_error = None

    for attempt in range(
        1,
        attempts + 1
    ):

        try:

            print()
            print(
                f"HTTP {attempt}/{attempts}"
            )

            print(url)

            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": (
                        "application/rss+xml, "
                        "application/xml, "
                        "text/xml, "
                        "*/*"
                    ),
                    "Accept-Language":
                        "en-US,en;q=0.9",
                    "Cache-Control":
                        "no-cache",
                }
            )

            with urllib.request.urlopen(
                request,
                timeout=45
            ) as response:

                status = response.getcode()

                data = response.read(
                    MAX_MEDIA_SIZE + 1
                )

            if status != 200:

                raise RuntimeError(
                    f"HTTP {status}"
                )

            if len(data) > (
                MAX_MEDIA_SIZE
            ):

                raise RuntimeError(
                    "Response exceeds size limit"
                )

            return data

        except urllib.error.HTTPError as error:

            last_error = (
                f"HTTP {error.code}: "
                f"{error.reason}"
            )

            print(
                last_error,
                file=sys.stderr
            )

            if error.code in (
                429,
                500,
                502,
                503,
                504
            ):

                wait = min(
                    attempt * 5,
                    30
                )

                print(
                    f"Waiting {wait} seconds..."
                )

                time.sleep(
                    wait
                )

                continue

            return None

        except Exception as error:

            last_error = str(
                error
            )

            print(
                f"Request failed: "
                f"{error}",
                file=sys.stderr
            )

            if attempt < attempts:

                wait = min(
                    attempt * 4,
                    20
                )

                time.sleep(
                    wait
                )

    print(
        f"All requests failed: {last_error}",
        file=sys.stderr
    )

    return None


# ============================================================
# RSS HELPERS
# ============================================================

def strip_namespace(
    tag
):

    if "}" in tag:

        return tag.rsplit(
            "}",
            1
        )[1]

    return tag


def element_text(
    element
):

    if element is None:

        return ""

    return (
        "".join(
            element.itertext()
        )
        .strip()
    )


def find_child(
    element,
    wanted
):

    for child in element.iter():

        if (
            strip_namespace(
                child.tag
            ).lower()
            == wanted.lower()
        ):

            return child

    return None


# ============================================================
# EXTRACT URLS FROM RSS HTML
# ============================================================

def extract_urls(
    text
):

    if not text:

        return []

    found = []

    # --------------------------------------------------------
    # Normal URLs
    # --------------------------------------------------------

    matches = re.findall(
        r'https?://[^\s<>"\']+',
        text
    )

    for url in matches:

        url = (
            url
            .replace(
                "&amp;",
                "&"
            )
            .rstrip(
                ".,);]>\"'"
            )
        )

        if url not in found:

            found.append(
                url
            )

    return found


# ============================================================
# NORMALIZE POST
# ============================================================

def normalize_rss_entry(
    entry
):

    title = ""

    post_url = ""

    post_id = ""

    content = ""

    author = ""

    # --------------------------------------------------------
    # Read XML children
    # --------------------------------------------------------

    for child in entry.iter():

        name = (
            strip_namespace(
                child.tag
            ).lower()
        )

        text = element_text(
            child
        )

        if name == "title":

            if text:

                title = text

        elif name == "id":

            if text:

                post_id = text

        elif name == "author":

            if text:

                author = text

        elif name in (
            "content",
            "description"
        ):

            if text:

                content += "\n" + text

        elif name == "link":

            href = child.attrib.get(
                "href",
                ""
            )

            if href:

                post_url = href

            elif text:

                post_url = text

    # --------------------------------------------------------
    # Extract every URL from RSS content.
    # --------------------------------------------------------

    urls = extract_urls(
        content
    )

    # Also include the post link.
    if post_url:

        urls.insert(
            0,
            post_url
        )

    # --------------------------------------------------------
    # Clean URLs.
    # --------------------------------------------------------

    clean_urls = []

    for url in urls:

        if not url:

            continue

        url = (
            url
            .replace(
                "&amp;",
                "&"
            )
            .strip()
        )

        if url not in clean_urls:

            clean_urls.append(
                url
            )

    return {
        "id": post_id,
        "post_url": post_url,
        "title": title,
        "author": author,
        "content": content,
        "urls": clean_urls,
    }


# ============================================================
# FETCH REDDIT RSS
# ============================================================

def fetch_subreddit(
    subreddit
):

    encoded = urllib.parse.quote(
        subreddit,
        safe=""
    )

    url = REDDIT_RSS_URL.format(
        subreddit=encoded
    )

    data = http_get(
        url,
        attempts=3
    )

    if not data:

        print(
            f"r/{subreddit}: RSS request failed."
        )

        return []

    try:

        root = ET.fromstring(
            data
        )

    except ET.ParseError as error:

        print(
            f"r/{subreddit}: "
            f"RSS XML parse error: {error}",
            file=sys.stderr
        )

        return []

    entries = []

    for element in root.iter():

        name = (
            strip_namespace(
                element.tag
            ).lower()
        )

        if name not in (
            "entry",
            "item"
        ):

            continue

        post = normalize_rss_entry(
            element
        )

        if post:

            entries.append(
                post
            )

    # Limit the amount processed.
    entries = entries[
        :POSTS_PER_SUBREDDIT
    ]

    print(
        f"r/{subreddit}: "
        f"{len(entries)} RSS posts received."
    )

    return entries


# ============================================================
# MEDIA URL DETECTION
# ============================================================

IMAGE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp"
)

GIF_EXTENSIONS = (
    ".gif",
)

VIDEO_EXTENSIONS = (
    ".mp4",
    ".m4v",
    ".mov",
    ".webm",
)


def clean_media_url(
    url
):

    if not url:

        return ""

    url = (
        url
        .replace(
            "&amp;",
            "&"
        )
        .strip()
    )

    # Remove surrounding HTML.
    url = url.strip(
        "<>\"'"
    )

    return url


def url_extension(
    url
):

    clean = (
        url
        .lower()
        .split("?")[0]
        .split("#")[0]
    )

    return os.path.splitext(
        clean
    )[1]


def looks_like_image(
    url
):

    lower = (
        url
        .lower()
    )

    return (
        url_extension(url)
        in IMAGE_EXTENSIONS
        or "i.redd.it/" in lower
    )


def looks_like_gif(
    url
):

    lower = (
        url
        .lower()
    )

    return (
        url_extension(url)
        in GIF_EXTENSIONS
        or "giphy.com/media/" in lower
        or "media.giphy.com/" in lower
        or "i.redd.it/" in lower
        and lower.endswith(".gif")
    )


def looks_like_video(
    url
):

    lower = (
        url
        .lower()
    )

    return (
        url_extension(url)
        in VIDEO_EXTENSIONS
        or "v.redd.it/" in lower
    )


# ============================================================
# REDDIT VIDEO URL
# ============================================================

def reddit_video_urls(
    url
):

    lower = (
        url
        .lower()
        .split("?")[0]
        .rstrip("/")
    )

    if "v.redd.it/" not in lower:

        return []

    # Example:
    #
    # https://v.redd.it/abc123
    #
    # Try Reddit's normal MP4 representations.
    base = url.split(
        "?",
        1
    )[0].rstrip("/")

    video_id = base.rsplit(
        "/",
        1
    )[-1]

    if not video_id:

        return []

    return [
        f"https://v.redd.it/{video_id}/DASH_1080.mp4",
        f"https://v.redd.it/{video_id}/DASH_720.mp4",
        f"https://v.redd.it/{video_id}/DASH_480.mp4",
        f"https://v.redd.it/{video_id}/DASH_360.mp4",
    ]


# ============================================================
# DOWNLOAD MEDIA
# ============================================================

def download_media(
    url
):

    url = clean_media_url(
        url
    )

    if not url:

        return None, ""

    print()
    print(
        "Downloading:"
    )
    print(url)

    try:

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent":
                    USER_AGENT,
                "Accept":
                    "*/*"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=90
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

        if len(data) > (
            MAX_MEDIA_SIZE
        ):

            print(
                "Skipped: media exceeds 50 MB."
            )

            return None, ""

        if not data:

            print(
                "Skipped: empty media."
            )

            return None, ""

        print(
            f"Downloaded "
            f"{len(data) / 1024 / 1024:.2f} MB"
        )

        print(
            f"Content-Type: "
            f"{content_type}"
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
        url
        .lower()
        .split("?")[0]
        .split("#")[0]
    )

    content_type = (
        content_type or ""
    ).lower()

    # --------------------------------------------------------
    # GIF
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # MP4
    # --------------------------------------------------------

    if (
        len(data) >= 12
        and data[4:8] == b"ftyp"
    ):

        return "video"

    if content_type.startswith(
        "video/"
    ):

        return "video"

    if clean_url.endswith(
        VIDEO_EXTENSIONS
    ):

        return "video"

    # --------------------------------------------------------
    # JPEG
    # --------------------------------------------------------

    if data.startswith(
        b"\xff\xd8\xff"
    ):

        return "image"

    # --------------------------------------------------------
    # PNG
    # --------------------------------------------------------

    if data.startswith(
        b"\x89PNG"
    ):

        return "image"

    # --------------------------------------------------------
    # WEBP
    # --------------------------------------------------------

    if (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):

        return "image"

    if content_type.startswith(
        "image/"
    ):

        return "image"

    if clean_url.endswith(
        IMAGE_EXTENSIONS
    ):

        return "image"

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
# PREPARE IMAGE
# ============================================================

def prepare_image(
    data
):

    # Already small enough.
    if len(data) <= (
        TELEGRAM_IMAGE_LIMIT
    ):

        return data

    print(
        "Image is larger than Telegram target."
    )

    source = save_temp_file(
        data,
        ".source"
    )

    try:

        attempts = [
            ("92", "1920:-2"),
            ("85", "1600:-2"),
            ("78", "1400:-2"),
            ("70", "1200:-2"),
            ("60", "1000:-2"),
            ("50", "900:-2"),
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
                timeout=90
            )

            output = result.stdout

            if not output:

                continue

            print(
                f"Image quality {quality}: "
                f"{len(output) / 1024 / 1024:.2f} MB"
            )

            if len(output) <= (
                TELEGRAM_IMAGE_LIMIT
            ):

                return output

        return None

    finally:

        try:
            os.remove(
                source
            )
        except Exception:
            pass


# ============================================================
# PREPARE VIDEO FOR TELEGRAM ANIMATION
# ============================================================

def prepare_video(
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

            # Keep the entire video.
            # No trimming.
            "-map",
            "0:v:0",

            "-an",

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

            error = (
                result.stderr.decode(
                    "utf-8",
                    errors="ignore"
                )
            )

            print(
                "FFmpeg failed:",
                file=sys.stderr
            )

            print(
                error[-3000:],
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

        print(
            f"Animation MP4: "
            f"{len(converted) / 1024 / 1024:.2f} MB"
        )

        if len(converted) > (
            TELEGRAM_ANIMATION_LIMIT
        ):

            print(
                "Animation is too large."
            )

            return None

        return converted

    finally:

        try:
            os.remove(
                source
            )
        except Exception:
            pass

        try:
            os.remove(
                output
            )
        except Exception:
            pass


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
        f'filename="{filename}"\r\n"
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
                "multipart/form-data; "
                f"boundary={boundary}"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=240
    ) as response:

        raw = response.read().decode(
            "utf-8",
            errors="replace"
        )

    return json.loads(
        raw
    )


# ============================================================
# SEND IMAGE
# ============================================================

def send_image(
    data
):

    print()
    print(
        "Sending Telegram IMAGE..."
    )

    result = telegram_upload(
        "sendPhoto",
        "photo",
        "image.jpg",
        "image/jpeg",
        data
    )

    if not result.get(
        "ok"
    ):

        print(
            "Telegram image error:"
        )

        print(
            json.dumps(
                result,
                indent=2
            )
        )

        return False

    print(
        "Telegram image sent successfully."
    )

    return True


# ============================================================
# SEND GIF
# ============================================================

def send_gif(
    data,
    original_type
):

    print()
    print(
        "Sending Telegram ANIMATION..."
    )

    print(
        f"Original type: {original_type}"
    )

    # --------------------------------------------------------
    # REAL GIF
    #
    # IMPORTANT:
    # The original GIF bytes are sent directly.
    #
    # We DO NOT convert GIF -> image.
    # We DO NOT take only one frame.
    # --------------------------------------------------------

    if original_type == "gif":

        if len(data) > (
            TELEGRAM_ANIMATION_LIMIT
        ):

            print(
                "GIF is too large."
            )

            return False

        result = telegram_upload(
            "sendAnimation",
            "animation",
            "animation.gif",
            "image/gif",
            data
        )

    # --------------------------------------------------------
    # VIDEO
    #
    # Telegram's animation endpoint accepts MP4.
    # --------------------------------------------------------

    else:

        result = telegram_upload(
            "sendAnimation",
            "animation",
            "animation.mp4",
            "video/mp4",
            data
        )

    if not result.get(
        "ok"
    ):

        print(
            "Telegram animation error:"
        )

        print(
            json.dumps(
                result,
                indent=2
            )
        )

        return False

    print(
        "Telegram animation sent successfully."
    )

    return True


# ============================================================
# DETERMINE REQUIRED FORMAT
# ============================================================

def required_media_type(
    next_type
):

    if next_type in (
        0,
        1
    ):

        return "image"

    return "gif"


def advance_next_type(
    current
):

    # Sequence:
    #
    # 0 = image
    # 1 = image
    # 2 = gif
    #
    if current == 0:

        return 1

    if current == 1:

        return 2

    return 0


# ============================================================
# GET MEDIA CANDIDATES FROM RSS POST
# ============================================================

def candidate_media_urls(
    post
):

    urls = post.get(
        "urls",
        []
    )

    candidates = []

    for url in urls:

        url = clean_media_url(
            url
        )

        if not url:

            continue

        # ----------------------------------------------------
        # Direct media
        # ----------------------------------------------------

        if (
            looks_like_image(url)
            or looks_like_gif(url)
            or looks_like_video(url)
        ):

            if url not in candidates:

                candidates.append(
                    url
                )

        # ----------------------------------------------------
        # Reddit video
        # ----------------------------------------------------

        if "v.redd.it/" in (
            url.lower()
        ):

            for video_url in reddit_video_urls(
                url
            ):

                if video_url not in candidates:

                    candidates.append(
                        video_url
                    )

    return candidates


# ============================================================
# TRY POST
# ============================================================

def prepare_candidate(
    post,
    wanted_type
):

    urls = candidate_media_urls(
        post
    )

    if not urls:

        return None

    for url in urls:

        # ----------------------------------------------------
        # If we specifically need an image, don't download
        # obvious video/GIF URLs.
        # ----------------------------------------------------

        if wanted_type == "image":

            if (
                looks_like_gif(url)
                or looks_like_video(url)
            ):

                continue

        # ----------------------------------------------------
        # If we need GIF/animation, skip obvious photos.
        # ----------------------------------------------------

        if wanted_type == "gif":

            if looks_like_image(
                url
            ) and not looks_like_gif(
                url
            ):

                continue

        data, content_type = download_media(
            url
        )

        if data is None:

            continue

        media_type = detect_media_type(
            url,
            data,
            content_type
        )

        print(
            f"Detected media type: "
            f"{media_type}"
        )

        # ----------------------------------------------------
        # IMAGE
        # ----------------------------------------------------

        if wanted_type == "image":

            if media_type != "image":

                continue

            prepared = prepare_image(
                data
            )

            if prepared is None:

                continue

            return {
                "data": prepared,
                "telegram_type": "image",
                "original_url": url,
                "original_type": media_type,
            }

        # ----------------------------------------------------
        # GIF
        # ----------------------------------------------------

        if wanted_type == "gif":

            # ------------------------------------------------
            # REAL GIF:
            #
            # Send the ORIGINAL GIF.
            # ------------------------------------------------

            if media_type == "gif":

                if len(data) > (
                    TELEGRAM_ANIMATION_LIMIT
                ):

                    continue

                return {
                    "data": data,
                    "telegram_type": "gif",
                    "original_url": url,
                    "original_type": "gif",
                }

            # ------------------------------------------------
            # VIDEO:
            #
            # Convert video to MP4 animation.
            # The whole video is retained.
            # ------------------------------------------------

            if media_type == "video":

                prepared = prepare_video(
                    data
                )

                if prepared is None:

                    continue

                return {
                    "data": prepared,
                    "telegram_type": "gif",
                    "original_url": url,
                    "original_type": "video",
                }

    return None


# ============================================================
# FETCH CANDIDATES
# ============================================================

def find_media(
    history,
    wanted_type
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

    # --------------------------------------------------------
    # Search all configured subreddits in random order.
    #
    # This is important:
    #
    # If subreddit A doesn't have the required format,
    # we automatically try subreddit B, C, etc.
    # --------------------------------------------------------

    subreddit_pool = list(
        SUBREDDITS
    )

    random.shuffle(
        subreddit_pool
    )

    print()
    print(
        "Required media type:"
    )
    print(
        wanted_type
    )

    for attempt in range(
        1,
        SEARCH_ATTEMPTS + 1
    ):

        print()
        print(
            "========================================"
        )

        print(
            f"SEARCH ATTEMPT "
            f"{attempt}/{SEARCH_ATTEMPTS}"
        )

        print(
            "========================================"
        )

        # Rotate the starting subreddit so repeated runs
        # don't always begin with the same one.
        start = (
            (attempt - 1)
            * SUBREDDITS_PER_SEARCH
        ) % len(
            subreddit_pool
        )

        selected = []

        for offset in range(
            len(subreddit_pool)
        ):

            index = (
                start + offset
            ) % len(
                subreddit_pool
            )

            selected.append(
                subreddit_pool[index]
            )

            if len(selected) >= (
                SUBREDDITS_PER_SEARCH
            ):

                break

        for subreddit in selected:

            print()
            print(
                "Checking:"
            )
            print(
                f"r/{subreddit}"
            )

            posts = fetch_subreddit(
                subreddit
            )

            if not posts:

                print(
                    f"No RSS posts from "
                    f"r/{subreddit}."
                )

                continue

            random.shuffle(
                posts
            )

            for post in posts:

                post_url = post.get(
                    "post_url",
                    ""
                )

                post_id = post.get(
                    "id",
                    ""
                )

                # ------------------------------------------------
                # Duplicate URL
                # ------------------------------------------------

                if (
                    post_url
                    and post_url in seen_urls
                ):

                    print(
                        "Skipped previously posted URL."
                    )

                    continue

                # ------------------------------------------------
                # Duplicate Reddit ID
                # ------------------------------------------------

                if (
                    post_id
                    and post_id in seen_ids
                ):

                    print(
                        "Skipped previously posted Reddit post."
                    )

                    continue

                prepared = prepare_candidate(
                    post,
                    wanted_type
                )

                if prepared is None:

                    continue

                post["_prepared"] = prepared

                post["_post_id"] = post_id

                post["_subreddit"] = subreddit

                return post

        print()
        print(
            "No matching media found in this search."
        )

        if attempt < SEARCH_ATTEMPTS:

            print(
                f"Waiting {SEARCH_DELAY} seconds..."
            )

            time.sleep(
                SEARCH_DELAY
            )

    return None


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
        "========================================"
    )

    print(
        "Posting sequence:"
    )

    print(
        "IMAGE → IMAGE → GIF → repeat"
    )

    print(
        "========================================"
    )

    # --------------------------------------------------------
    # Environment
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # History
    # --------------------------------------------------------

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

    next_type = history.get(
        "next_type",
        0
    )

    wanted_type = required_media_type(
        next_type
    )

    print()
    print(
        f"Next required type: "
        f"{wanted_type}"
    )

    # --------------------------------------------------------
    # Find media
    # --------------------------------------------------------

    post = find_media(
        history,
        wanted_type
    )

    if not post:

        print()
        print(
            "========================================"
        )

        print(
            "NO MEDIA FOUND"
        )

        print(
            f"Required type: {wanted_type}"
        )

        print(
            "The bot checked the configured "
            "subreddits."
        )

        print(
            "Nothing was posted."
        )

        print(
            "========================================"
        )

        # IMPORTANT:
        # Exit with an error so GitHub Actions doesn't falsely
        # report a successful posting run.
        sys.exit(2)

    prepared = post.get(
        "_prepared"
    )

    if not prepared:

        print(
            "ERROR: Prepared media missing.",
            file=sys.stderr
        )

        sys.exit(1)

    data = prepared.get(
        "data"
    )

    telegram_type = prepared.get(
        "telegram_type"
    )

    original_url = prepared.get(
        "original_url",
        ""
    )

    original_type = prepared.get(
        "original_type",
        ""
    )

    if not data:

        print(
            "ERROR: Empty prepared media.",
            file=sys.stderr
        )

        sys.exit(1)

    print()
    print(
        "========================================"
    )

    print(
        "MEDIA SELECTED"
    )

    print(
        f"Subreddit: "
        f"r/{post.get('_subreddit', '')}"
    )

    print(
        f"Telegram type: "
        f"{telegram_type}"
    )

    print(
        f"Original type: "
        f"{original_type}"
    )

    print(
        f"Size: "
        f"{len(data) / 1024 / 1024:.2f} MB"
    )

    print(
        f"URL: "
        f"{original_url}"
    )

    print(
        "========================================"
    )

    # --------------------------------------------------------
    # Send
    # --------------------------------------------------------

    if telegram_type == "image":

        success = send_image(
            data
        )

    elif telegram_type == "gif":

        success = send_gif(
            data,
            original_type
        )

    else:

        print(
            "ERROR: Unknown Telegram type.",
            file=sys.stderr
        )

        sys.exit(1)

    # --------------------------------------------------------
    # Telegram failed
    # --------------------------------------------------------

    if not success:

        print()
        print(
            "Telegram posting FAILED."
        )

        print(
            "History was NOT changed."
        )

        sys.exit(1)

    # --------------------------------------------------------
    # Save duplicate history
    # --------------------------------------------------------

    post_url = post.get(
        "post_url",
        ""
    )

    post_id = post.get(
        "_post_id",
        ""
    )

    digest = hashlib.sha256(
        data
    ).hexdigest()

    if post_url:

        history["urls"].append(
            post_url
        )

    if post_id:

        history["ids"].append(
            post_id
        )

    history["hashes"].append(
        digest
    )

    # --------------------------------------------------------
    # Advance sequence ONLY after successful Telegram post.
    # --------------------------------------------------------

    history["next_type"] = (
        advance_next_type(
            next_type
        )
    )

    save_history(
        history
    )

    print()
    print(
        "========================================"
    )

    print(
        "POST SUCCESSFUL"
    )

    print(
        "========================================"
    )

    print(
        f"Subreddit: "
        f"r/{post.get('_subreddit', '')}"
    )

    print(
        f"Posted as: "
        f"{telegram_type}"
    )

    print(
        f"Next posting type: "
        f"{required_media_type(history['next_type'])}"
    )

    print(
        "posted.json updated."
    )

    print(
        "Finished successfully."
    )

    print(
        "========================================"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()
