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

# USE SFW SUBREDDITS ONLY.
# Replace these with the SFW subreddits you want.
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

# Posting order:
#
# IMAGE
# IMAGE
# GIF / ANIMATION
# IMAGE
# IMAGE
# GIF / ANIMATION
#
IMAGE_TARGET = 2

POSTS_PER_SUBREDDIT = 100

FETCH_ATTEMPTS = 6

HTTP_ATTEMPTS = 4

HISTORY_LIMIT = 5000


# ------------------------------------------------------------
# SIZE LIMITS
# ------------------------------------------------------------

MAX_MEDIA_SIZE = 49 * 1024 * 1024

TELEGRAM_IMAGE_LIMIT = 9 * 1024 * 1024

TELEGRAM_ANIMATION_LIMIT = 49 * 1024 * 1024


# ------------------------------------------------------------
# USER AGENT
# ------------------------------------------------------------

USER_AGENT = (
    "RedditTelegramMediaBot/10.0 "
    "(GitHub Actions)"
)


# ------------------------------------------------------------
# SOURCES
# ------------------------------------------------------------

MEME_API_URL = (
    "https://meme-api.com/gimme/"
    "{subreddit}/{count}"
)

REDDIT_JSON_URL = (
    "https://www.reddit.com/r/"
    "{subreddit}/new.json"
)


# ============================================================
# TELEGRAM
# ============================================================

BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()


CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ============================================================
# FILE LOCATIONS
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)


HISTORY_FILE = os.path.join(
    BASE_DIR,
    "posted.json"
)


STATE_FILE = os.path.join(
    BASE_DIR,
    "posting_state.json"
)


# ============================================================
# HISTORY
# ============================================================

def empty_history():

    return {
        "urls": [],
        "ids": [],
        "hashes": []
    }


def load_history():

    if not os.path.exists(
        HISTORY_FILE
    ):

        return empty_history()

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(
            data,
            dict
        ):

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

        if isinstance(
            data,
            list
        ):

            return {
                "urls": data,
                "ids": [],
                "hashes": []
            }

    except Exception as error:

        print(
            f"Could not load history: {error}",
            file=sys.stderr,
            flush=True
        )

    return empty_history()


def save_history(
    history
):

    history["urls"] = (
        history.get(
            "urls",
            []
        )[-HISTORY_LIMIT:]
    )

    history["ids"] = (
        history.get(
            "ids",
            []
        )[-HISTORY_LIMIT:]
    )

    history["hashes"] = (
        history.get(
            "hashes",
            []
        )[-HISTORY_LIMIT:]
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
            indent=2
        )

    os.replace(
        temp_file,
        HISTORY_FILE
    )


# ============================================================
# POSTING STATE
# ============================================================

def load_state():

    if not os.path.exists(
        STATE_FILE
    ):

        return {
            "images_since_animation": 0
        }

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        value = int(
            data.get(
                "images_since_animation",
                0
            )
        )

        value = max(
            0,
            min(
                value,
                IMAGE_TARGET
            )
        )

        return {
            "images_since_animation": value
        }

    except Exception:

        return {
            "images_since_animation": 0
        }


def save_state(
    state
):

    temp_file = (
        STATE_FILE
        + ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            state,
            file,
            indent=2
        )

    os.replace(
        temp_file,
        STATE_FILE
    )


def required_media_type(
    state
):

    if (
        state[
            "images_since_animation"
        ]
        < IMAGE_TARGET
    ):

        return "image"

    return "animation"


def advance_state(
    state,
    media_type
):

    if media_type == "image":

        state[
            "images_since_animation"
        ] += 1

        if (
            state[
                "images_since_animation"
            ]
            > IMAGE_TARGET
        ):

            state[
                "images_since_animation"
            ] = IMAGE_TARGET

    elif media_type in (
        "gif",
        "animation_mp4"
    ):

        state[
            "images_since_animation"
        ] = 0


# ============================================================
# HTTP JSON
# ============================================================

def get_json(
    url,
    attempts=HTTP_ATTEMPTS
):

    last_error = None

    for attempt in range(
        1,
        attempts + 1
    ):

        try:

            print(
                f"HTTP request "
                f"{attempt}/{attempts}",
                flush=True
            )

            print(
                url,
                flush=True
            )

            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Accept-Language": (
                        "en-US,en;q=0.9"
                    )
                }
            )

            with urllib.request.urlopen(
                request,
                timeout=30
            ) as response:

                status = (
                    response.getcode()
                )

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
                525,
                526,
                530
            ):

                wait = min(
                    2 ** attempt,
                    15
                )

                print(
                    f"Temporary error: "
                    f"{last_error}",
                    flush=True
                )

                print(
                    f"Waiting {wait}s...",
                    flush=True
                )

                time.sleep(
                    wait
                )

                continue

            print(
                last_error,
                file=sys.stderr,
                flush=True
            )

            return None

        except Exception as error:

            last_error = str(
                error
            )

            print(
                f"Request error: "
                f"{error}",
                file=sys.stderr,
                flush=True
            )

            if attempt < attempts:

                wait = min(
                    2 ** attempt,
                    15
                )

                print(
                    f"Waiting {wait}s...",
                    flush=True
                )

                time.sleep(
                    wait
                )

    print(
        f"All HTTP attempts failed: "
        f"{last_error}",
        file=sys.stderr,
        flush=True
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
            POSTS_PER_SUBREDDIT,
            50
        )
    )

    data = get_json(
        url
    )

    if not data:

        return []

    memes = data.get(
        "memes",
        []
    )

    if not isinstance(
        memes,
        list
    ):

        return []

    posts = []

    for meme in memes:

        if not isinstance(
            meme,
            dict
        ):

            continue

        media_url = meme.get(
            "url"
        )

        if not media_url:

            continue

        posts.append(
            {
                "id": str(
                    meme.get(
                        "postLink",
                        ""
                    )
                ),
                "postLink": str(
                    meme.get(
                        "postLink",
                        ""
                    )
                ),
                "subreddit": meme.get(
                    "subreddit",
                    subreddit
                ),
                "title": meme.get(
                    "title",
                    ""
                ),
                "url": media_url,
                "nsfw": bool(
                    meme.get(
                        "nsfw",
                        False
                    )
                ),
                "spoiler": bool(
                    meme.get(
                        "spoiler",
                        False
                    )
                ),
                "_source": "meme-api"
            }
        )

    print(
        f"meme-api returned "
        f"{len(posts)} posts for "
        f"r/{subreddit}",
        flush=True
    )

    return posts


# ============================================================
# REDDIT JSON
# ============================================================

def normalize_reddit_post(
    child,
    subreddit
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

    post_id = str(
        data.get(
            "id",
            ""
        )
    )

    permalink = data.get(
        "permalink",
        ""
    )

    if permalink:

        post_link = (
            "https://www.reddit.com"
            + permalink
        )

    elif post_id:

        post_link = (
            "https://redd.it/"
            + post_id
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
        "id": post_id,
        "postLink": post_link,
        "subreddit": data.get(
            "subreddit",
            subreddit
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
        "_source": "reddit-json"
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
                POSTS_PER_SUBREDDIT,
                100
            ),
            "raw_json": 1
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
        data
        .get(
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
            child,
            subreddit
        )

        if post:

            posts.append(
                post
            )

    print(
        f"Reddit returned "
        f"{len(posts)} posts for "
        f"r/{subreddit}",
        flush=True
    )

    return posts


# ============================================================
# FETCH ALL SUBREDDITS
# ============================================================

def fetch_candidate_posts():

    print()
    print(
        "========================================",
        flush=True
    )

    print(
        "CHECKING SUBREDDITS",
        flush=True
    )

    print(
        "========================================",
        flush=True
    )

    all_posts = []

    # Shuffle the subreddit order so the same
    # subreddit isn't always selected first.
    subreddits = list(
        SUBREDDITS
    )

    random.shuffle(
        subreddits
    )

    for subreddit in subreddits:

        print()
        print(
            f"Checking r/{subreddit}",
            flush=True
        )

        posts = fetch_from_meme_api(
            subreddit
        )

        if not posts:

            print(
                f"meme-api failed for "
                f"r/{subreddit}",
                flush=True
            )

            print(
                "Trying Reddit JSON...",
                flush=True
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
                f"No posts received from "
                f"r/{subreddit}",
                flush=True
            )

    random.shuffle(
        all_posts
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
        "Downloading media:",
        flush=True
    )

    print(
        url,
        flush=True
    )

    try:

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=90
        ) as response:

            content_type = (
                response
                .headers
                .get(
                    "Content-Type",
                    ""
                )
                .lower()
                .split(
                    ";"
                )[0]
                .strip()
            )

            data = response.read(
                MAX_MEDIA_SIZE + 1
            )

        if len(data) > (
            MAX_MEDIA_SIZE
        ):

            print(
                "Skipped: media is over "
                "49 MB.",
                flush=True
            )

            return None, ""

        if not data:

            print(
                "Skipped: empty media.",
                flush=True
            )

            return None, ""

        print(
            f"Downloaded: "
            f"{len(data) / 1024 / 1024:.2f} MB",
            flush=True
        )

        print(
            f"Content-Type: "
            f"{content_type}",
            flush=True
        )

        return (
            data,
            content_type
        )

    except Exception as error:

        print(
            f"Download failed: "
            f"{error}",
            file=sys.stderr,
            flush=True
        )

        return None, ""


# ============================================================
# MEDIA TYPE DETECTION
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
    #
    # Check the actual file bytes first.
    # This is extremely important.
    # --------------------------------------------------------

    if (
        data.startswith(
            b"GIF87a"
        )
        or data.startswith(
            b"GIF89a"
        )
    ):

        return "gif"

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
        b"\x89PNG\r\n\x1a\n"
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

    # --------------------------------------------------------
    # MP4 / MOV
    # --------------------------------------------------------

    if (
        len(data) >= 12
        and data[4:8] == b"ftyp"
    ):

        return "video"

    # --------------------------------------------------------
    # CONTENT TYPE
    # --------------------------------------------------------

    if content_type == "image/gif":

        return "gif"

    if content_type.startswith(
        "image/"
    ):

        return "image"

    if content_type.startswith(
        "video/"
    ):

        return "video"

    # --------------------------------------------------------
    # URL FALLBACK
    # --------------------------------------------------------

    if clean_url.endswith(
        ".gif"
    ):

        return "gif"

    if clean_url.endswith(
        (
            ".jpg",
            ".jpeg",
            ".png",
            ".webp"
        )
    ):

        return "image"

    if clean_url.endswith(
        (
            ".mp4",
            ".m4v",
            ".mov",
            ".webm"
        )
    ):

        return "video"

    return "unknown"


# ============================================================
# TEMP FILE
# ====================================================