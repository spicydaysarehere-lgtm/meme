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
    "EcchiCurves",
    "animeplot",
]


# ============================================================
# SETTINGS
# ============================================================

# Number of different subreddits checked in one search.
SUBREDDITS_PER_RUN = 2

# Number of Reddit posts requested from each subreddit.
MEMES_PER_SUBREDDIT = 50

# Number of times the bot searches before giving up.
FETCH_ATTEMPTS = 8

# History size.
HISTORY_LIMIT = 5000

# Maximum download size.
MAX_MEDIA_SIZE = 50 * 1024 * 1024

# Telegram photo limit target.
TELEGRAM_IMAGE_LIMIT = 9 * 1024 * 1024

# Telegram animation limit.
TELEGRAM_ANIMATION_LIMIT = 49 * 1024 * 1024

# Telegram animation dimensions.
MAX_ANIMATION_WIDTH = 720
MAX_ANIMATION_HEIGHT = 720

MEME_API_URL = (
    "https://meme-api.com/gimme/{subreddit}/{count}"
)

REDDIT_JSON_URL = (
    "https://www.reddit.com/r/{subreddit}/new.json"
)

USER_AGENT = (
    "RedditTelegramMediaBot/8.0 "
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
# HTTP JSON
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

            if status != 200:

                raise RuntimeError(
                    f"HTTP {status}"
                )

            return json.loads(
                raw.decode(
                    "utf-8",
                    errors="replace"
                )
            )

        except urllib.error.HTTPError as error:

            last_error = (
                f"HTTP {error.code}: "
                f"{error.reason}"
            )

            if error.code in (
                429,
                500,
                502,
                503,
                504,
                520,
                521,
                522,
                523,
                524,
                530,
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
                last_error,
                file=sys.stderr
            )

            return None

        except urllib.error.URLError as error:

            last_error = (
                f"Connection error: {error}"
            )

            print(
                last_error,
                file=sys.stderr
            )

            if attempt < attempts:

                wait = min(
                    2 ** attempt,
                    15
                )

                print(
                    f"Waiting {wait} seconds..."
                )

                time.sleep(
                    wait
                )

        except json.JSONDecodeError as error:

            print(
                f"Invalid JSON: {error}",
                file=sys.stderr
            )

            return None

        except Exception as error:

            last_error = str(
                error
            )

            print(
                f"Request error: {error}",
                file=sys.stderr
            )

            if attempt < attempts:

                wait = min(
                    2 ** attempt,
                    15
                )

                time.sleep(
                    wait
                )

    print(
        f"All HTTP attempts failed: "
        f"{last_error}",
        file=sys.stderr
    )

    return None


# ============================================================
# MEME API
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

    for post in posts:

        if isinstance(
            post,
            dict
        ):

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
        "id",
        ""
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
        attempts=4
    )

    if not data:
        return []

    children = (
        data
        .get("data", {})
        .get("children", [])
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

        posts = fetch_from_meme_api(
            subreddit
        )

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
# DOWNLOAD
# ============================================================

def download_media(
    url
):

    print()
    print(
        "Downloading media:"
    )

    print(url)

    try:

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=90
        ) as response:

            content_type = (
                response.headers
                .get(
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
# MEDIA DETECTION
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
    # TRUE GIF
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
    # MP4 / MOV / WEBM
    # --------------------------------------------------------

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
            ".webm",
        )
    ):

        return "animated_video"

    # --------------------------------------------------------
    # WEBP
    #
    # Important:
    # A Reddit animated WebP can look like an image based
    # only on the extension/header.
    #
    # We use ffprobe to determine whether it has multiple
    # frames.
    # --------------------------------------------------------

    if (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):

        if is_animated_webp(data):

            return "animated_webp"

        return "photo"

    # --------------------------------------------------------
    # JPEG
    # --------------------------------------------------------

    if data.startswith(
        b"\xff\xd8\xff"
    ):

        return "photo"

    # --------------------------------------------------------
    # PNG
    # --------------------------------------------------------

    if data.startswith(
        b"\x89PNG"
    ):

        return "photo"

    # --------------------------------------------------------
    # CONTENT TYPE
    # --------------------------------------------------------

    if content_type.startswith(
        "image/"
    ):

        return "photo"

    # --------------------------------------------------------
    # URL EXTENSION
    # --------------------------------------------------------

    if clean_url.endswith(
        (
            ".jpg",
            ".jpeg",
            ".png",
        )
    ):

        return "photo"

    return "unknown"


# ============================================================
# FFPROBE
# ============================================================

def run_ffprobe(
    path
):

    try:

        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name,codec_type,width,height,nb_frames",
                "-of",
                "json",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )

        if result.returncode != 0:
            return None

        return json.loads(
            result.stdout.decode(
                "utf-8",
                errors="ignore"
            )
        )

    except Exception:

        return None


def is_animated_webp(
    data
):

    source = save_temp_file(
        data,
        ".webp"
    )

    try:

        info = run_ffprobe(
            source
        )

        if not info:
            return False

        streams = info.get(
            "streams",
            []
        )

        for stream in streams:

            if stream.get(
                "codec_type"
            ) == "video":

                frames = stream.get(
                    "nb_frames"
                )

                if frames:

                    try:

                        return int(
                            frames
                        ) > 1

                    except Exception:
                        pass

        # If ffprobe cannot provide nb_frames,
        # ask ffprobe for packet count.

        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-count_packets",
                "-show_entries",
                "stream=nb_read_packets",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                source,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )

        if result.returncode == 0:

            text = (
                result.stdout
                .decode(
                    "utf-8",
                    errors="ignore"
                )
                .strip()
            )

            try:

                return int(text) > 1

            except Exception:
                pass

        return False

    finally:

        try:
            os.remove(source)
        except Exception:
            pass


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
# VALIDATE GIF
# ============================================================

def validate_gif(
    data
):

    source = save_temp_file(
        data,
        ".gif"
    )

    try:

        info = run_ffprobe(
            source
        )

        if not info:
            return False

        streams = info.get(
            "streams",
            []
        )

        for stream in streams:

            if stream.get(
                "codec_type"
            ) == "video":

                codec = (
                    stream.get(
                        "codec_name"
                    )
                    or ""
                ).lower()

                if codec == "gif":

                    return True

        return False

    finally:

        try:
            os.remove(source)
        except Exception:
            pass


# ======================================