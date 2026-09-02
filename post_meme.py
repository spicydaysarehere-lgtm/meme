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

# How many posts to request from each subreddit.
MEMES_PER_SUBREDDIT = 50

# Maximum number of times the bot retries its search.
FETCH_ATTEMPTS = 5

# Number of entries kept in posted.json.
HISTORY_LIMIT = 5000

# Maximum source media size.
MAX_MEDIA_SIZE = 50 * 1024 * 1024

# Stay safely under Telegram's image upload limit.
TELEGRAM_IMAGE_LIMIT = 9 * 1024 * 1024

# Stay safely under Telegram's animation upload limit.
TELEGRAM_GIF_LIMIT = 47 * 1024 * 1024

# GIF conversion.
GIF_FPS = 15
GIF_MAX_WIDTH = 640

# 0 = keep complete animation.
GIF_MAX_DURATION = 0


# ============================================================
# API SOURCES
# ============================================================

MEME_API_URL = (
    "https://meme-api.com/gimme/{subreddit}/{count}"
)

REDDIT_JSON_URL = (
    "https://www.reddit.com/r/{subreddit}/new.json"
)

USER_AGENT = (
    "RedditTelegramMediaBot/8.0 "
    "(GitHub Actions)"
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
        "hashes": [],

        # 0 = image 1
        # 1 = image 2
        # 2 = GIF
        "sequence_index": 0,
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

            data = json.load(
                file
            )

        if isinstance(
            data,
            dict
        ):

            try:

                sequence_index = int(
                    data.get(
                        "sequence_index",
                        0
                    )
                )

            except Exception:

                sequence_index = 0

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
                ),

                "sequence_index":
                    sequence_index % 3,
            }

        # Compatibility with old list format.
        if isinstance(
            data,
            list
        ):

            return {
                "urls": data,
                "ids": [],
                "hashes": [],
                "sequence_index": 0,
            }

    except Exception as error:

        print(
            f"Could not load posted.json: "
            f"{error}",
            file=sys.stderr
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

    history["sequence_index"] = (
        int(
            history.get(
                "sequence_index",
                0
            )
        ) % 3
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
# JSON REQUEST
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
                f"HTTP "
                f"{attempt}/{attempts}: "
                f"{url}"
            )

            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent":
                        USER_AGENT,
                    "Accept":
                        "application/json",
                    "Accept-Language":
                        "en-US,en;q=0.9",
                }
            )

            with urllib.request.urlopen(
                request,
                timeout=30
            ) as response:

                raw = response.read()

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
                530,
            ):

                wait = min(
                    2 ** attempt,
                    15
                )

                print(
                    f"Temporary error: "
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
                f"Connection error: "
                f"{error}"
            )

            print(
                last_error,
                file=sys.stderr
            )

            if attempt < attempts:

                time.sleep(
                    min(
                        2 ** attempt,
                        15
                    )
                )

                continue

        except json.JSONDecodeError as error:

            print(
                f"Invalid JSON: "
                f"{error}",
                file=sys.stderr
            )

            return None

        except Exception as error:

            last_error = str(
                error
            )

            print(
                f"Request error: "
                f"{error}",
                file=sys.stderr
            )

            if attempt < attempts:

                time.sleep(
                    min(
                        2 ** attempt,
                        15
                    )
                )

    print(
        f"All attempts failed: "
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
        count=MEMES_PER_SUBREDDIT
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

    for post in posts:

        if isinstance(
            post,
            dict
        ):

            post["_source"] = (
                "meme-api"
            )

            # Make sure subreddit exists.
            if not post.get(
                "subreddit"
            ):

                post["subreddit"] = (
                    subreddit
                )

    print(
        f"Meme API: "
        f"{len(posts)} posts from "
        f"r/{subreddit}"
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

        "_source": "reddit-json",
    }


def fetch_from_reddit(
    subreddit
):

    encoded = urllib.parse.quote(
        subreddit
    )

    params = urllib.parse.urlencode(
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
        + params
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
        f"Reddit fallback: "
        f"{len(posts)} posts from "
        f"r/{subreddit}"
    )

    return posts


# ============================================================
# FETCH ALL SUBREDDITS
# ============================================================

def fetch_candidate_posts():

    if not SUBREDDITS:

        print(
            "ERROR: No subreddits configured.",
            file=sys.stderr
        )

        return []

    # IMPORTANT:
    #
    # We check ALL configured subreddits.
    #
    # This allows the bot to say:
    #
    # "This subreddit doesn't contain the
    # required format, try another one."
    #
    subreddit_order = list(
        SUBREDDITS
    )

    random.shuffle(
        subreddit_order
    )

    all_posts = []

    print()
    print(
        "Subreddit search order:"
    )

    for subreddit in subreddit_order:

        print(
            f"  r/{subreddit}"
        )

    for subreddit in subreddit_order:

        print()
        print(
            f"Checking "
            f"r/{subreddit}..."
        )

        posts = fetch_from_meme_api(
            subreddit
        )

        # ----------------------------------------------------
        # Fallback
        # ----------------------------------------------------

        if not posts:

            print(
                f"Meme API failed for "
                f"r/{subreddit}."
            )

            print(
                "Trying Reddit fallback..."
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
                f"No usable posts found "
                f"from r/{subreddit}."
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
        "Downloading:"
    )

    print(
        url
    )

    try:

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent":
                    USER_AGENT
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

        if len(data) > (
            MAX_MEDIA_SIZE
        ):

            print(
                "Skipped: source is larger "
                "than 50 MB."
            )

            return None, ""

        if not data:

            print(
                "Skipped: empty file."
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
# MEDIA TYPE
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
    # REAL GIF
    # --------------------------------------------------------

    if data.startswith(
        b"GIF87a"
    ):

        return "gif"

    if data.startswith(
        b"GIF89a"
    ):

        return "gif"

    if "image/gif" in (
        content_type
    ):

        return "gif"

    if clean_url.endswith(
        ".gif"
    ):

        return "gif"

    # --------------------------------------------------------
    # VIDEO
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
        (
            ".mp4",
            ".m4v",
            ".mov",
            ".webm"
        )
    ):

        return "video"

    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

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

    os.close(
        fd
    )

    with open(
        path,
        "wb"
    ) as file:

        file.write(
            data
        )

    return path


# ============================================================
# COMPRESS PHOTO
# ============================================================

def compress_photo(
    data
):

    if len(data) <= (
        TELEGRAM_IMAGE_LIMIT
    ):

        # IMPORTANT:
        # This remains an image.
        return data

    print()
    print(
        "Large image detected."
    )

    print(
        "Compressing image..."
    )

    source = save_temp_file(
        data,
        ".source"
    )

    try:

        attempts = [
            ("90", 1920),
            ("80", 1600),
            ("70", 1400),
            ("60", 1200),
            ("50", 1000),
            ("40", 900),
            ("35", 800),
        ]

        for quality, width in attempts:

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
                f"Image "
                f"{width}px / q{quality}: "
                f"{size_mb:.2f} MB"
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
# GIF CONVERSION
# ============================================================

def convert_to_real_gif(
    data
):

    print()
    print(
        "Preparing REAL GIF..."
    )

    source = save_temp_file(
        data,
        ".source"
    )

    palette = tempfile.mktemp(
        suffix=".png"
    )

    output = tempfile.mktemp(
        suffix=".gif"
    )

    try:

        duration_args = []

        if GIF_MAX_DURATION > 0:

            duration_args = [
                "-t",
                str(
                    GIF_MAX_DURATION
                )
            ]

        # ----------------------------------------------------
        # GENERATE PALETTE
        # ----------------------------------------------------

        palette_command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",

            "-i",
            source,

            *duration_args,

            "-vf",
            (
                f"fps={GIF_FPS},"
                f"scale={GIF_MAX_WIDTH}:-1:"
                "force_original_aspect_ratio=decrease,"
                "palettegen="
                "stats_mode=diff"
            ),

            palette
        ]

        palette_result = subprocess.run(
            palette_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180
        )

        if (
            palette_result.returncode != 0
            or not os.path.exists(
                palette
            )
        ):

            print(
                "Failed to generate GIF palette."
            )

            print(
                palette_result.stderr.decode(
                    "utf-8",
                    errors="ignore"
                )[-3000:],
                file=sys.stderr
            )

            return None

        # ----------------------------------------------------
        # CREATE ACTUAL GIF
        # ----------------------------------------------------

        gif_command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",

            "-i",
            source,

            "-i",
            palette,

            *duration_args,

            "-filter_complex",
            (
                f"[0:v]"
                f"fps={GIF_FPS},"
                f"scale={GIF_MAX_WIDTH}:-1:"
                "force_original_aspect_ratio=decrease"
                "[video];"
                "[video][1:v]"
                "paletteuse="
                "dither=sierra2_4a"
            ),

            "-loop",
            "0",

            output
        ]

        gif_result = subprocess.run(
            gif_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=240
        )

        if (
            gif_result.returncode != 0
            or not os.path.exists(
                output
            )
        ):

            print(
                "GIF creation failed."
            )

            print(
                gif_result.stderr.decode(
                    "utf-8",
                    errors="ignore"
                )[-3000:],
                file=sys.stderr
            )

            return None

        with open(
            output,
            "rb"
        ) as file:

            gif_data = file.read()

        # ----------------------------------------------------
        # VERIFY IT REALLY IS A GIF
        # ----------------------------------------------------

        if not gif_data.startswith(
            b"GIF87a"
        ) and not gif_data.startswith(
            b"GIF89a"
        ):

            print(
                "ERROR: Generated file is "
                "not a real GIF."
            )

            return None

        size_mb = (
            len(gif_data)
            / 1024
            / 1024
        )

        print(
            f"REAL GIF created: "
            f"{size_mb:.2f} MB"
        )

        if len(gif_data) <= (
            TELEGRAM_GIF_LIMIT
        ):

            return gif_data

        # ----------------------------------------------------
        # STRONGER COMPRESSION
        # ----------------------------------------------------

        print(
            "GIF is too large."
        )

        print(
            "Trying smaller GIF..."
        )

        return compress_large_gif(
            data
        )

    except Exception as error:

        print(
            f"GIF conversion failed: "
            f"{error}",
            file=sys.stderr
        )

        return None

    finally:

        for path in (
            source,
            palette,
            output
        ):

            try:

                if os.path.exists(
                    path
                ):

                    os.remove(
                        path
                    )

            except Exception:

                pass


# ============================================================
# LARGE GIF COMPRESSION
# ============================================================

def compress_large_gif(
    data
):

    source = save_temp_file(
        data,
        ".source"
    )

    attempts = [
        (12, 540),
        (10, 480),
        (8, 420),
        (6, 360),
    ]

    try:

        for fps, width in attempts:

            palette = tempfile.mktemp(
                suffix=".png"
            )

            output = tempfile.mktemp(
                suffix=".gif"
            )

            try:

                # Palette.
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
                            f"fps={fps},"
                            f"scale={width}:-1:"
                            "force_original_aspect_ratio=decrease,"
                            "palettegen="
                        ),

                        palette
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=180
                )

                if (
                    result.returncode != 0
                    or not os.path.exists(
                        palette
                    )
                ):

                    continue

                # GIF.
                result = subprocess.run(
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
                            f"fps={fps},"
                            f"scale={width}:-1:"
                            "force_original_aspect_ratio=decrease"
                            "[video];"
                            "[video][1:v]"
                            "paletteuse="
                            "dither=bayer:bayer_scale=2"
                        ),

                        "-loop",
                        "0",

                        output
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=240
                )

                if (
                    result.returncode != 0
                    or not os.path.exists(
                        output
                    )
                ):

                    continue

                with open(
                    output,
                    "rb"
                ) as file:

                    gif_data = file.read()

                if not (
                    gif_data.startswith(
                        b"GIF87a"
                    )
                    or gif_data.startswith(
                        b"GIF89a"
                    )
                ):

                    continue

                size_mb = (
                    len(gif_data)
                    / 1024
                    / 1024
                )

                print(
                    f"GIF compression "
                    f"{width}px / {fps}fps: "
                    f"{size_mb:.2f} MB"
                )

                if len(gif_data) <= (
                    TELEGRAM_GIF_LIMIT
                ):

                    return gif_data

            finally:

                for path in (
                    palette,
                    output
                ):

                    try:

                        if os.path.exists(
                            path
                        ):

                            os.remove(
                                path
                            )

                    except Exception:

                        pass

        return None

    finally:

        try:
            os.remove(
                source
            )
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
# REQUIRED TYPE
# ============================================================

def required_media_type(
    history
):

    index = history.get(
        "sequence_index",
        0
    )

    try:

        index = int(
            index
        )

    except Exception:

        index = 0

    index %= 3

    if index == 2:

        return "gif"

    return "photo"


def sequence_text(
    media_type
):

    if media_type == "photo":

        return "IMAGE"

    return "GIF"


# ============================================================
# FIND REQUIRED MEDIA
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

    wanted = required_media_type(
        history
    )

    print()
    print(
        "========================================"
    )

    print(
        "CURRENT SEQUENCE"
    )

    print(
        "2 IMAGES → 1 GIF"
    )

    print(
        f"Next required: "
        f"{sequence_text(wanted)}"
    )

    print(
        "========================================"
    )

    # --------------------------------------------------------
    # Fetch all configured subreddits.
    # Then inspect each post until the required format
    # is found.
    # --------------------------------------------------------

    for batch in range(
        1,
        FETCH_ATTEMPTS + 1
    ):

        print()
        print(
            "========================================"
        )

        print(
            f"SEARCH ROUND "
            f"{batch}/{FETCH_ATTEMPTS}"
        )

        print(
            "========================================"
        )

        posts = fetch_candidate_posts()

        if not posts:

            print(
                "No posts returned."
            )

            time.sleep(3)

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

            subreddit = post.get(
                "subreddit",
                "unknown"
            )

            if not url:

                continue

            # ------------------------------------------------
            # URL DUPLICATE
            # ------------------------------------------------

            if url in seen_urls:

                print(
                    f"Skip r/{subreddit}: "
                    f"duplicate URL."
                )

                continue

            # ------------------------------------------------
            # REDDIT POST DUPLICATE
            # ------------------------------------------------

            if (
                post_id
                and post_id in seen_ids
            ):

                print(
                    f"Skip r/{subreddit}: "
                    f"duplicate post."
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

                continue

            # ------------------------------------------------
            # DETECT ORIGINAL TYPE
            # ------------------------------------------------

            original_type = detect_media_type(
                url,
                media_data,
                content_type
            )

            print(
                f"r/{subreddit}: "
                f"source type = "
                f"{original_type}"
            )

            if original_type == "unknown":

                print(
                    "Skipped: unknown media."
                )

                continue

            # ------------------------------------------------
            # HASH ORIGINAL
            # ------------------------------------------------

            digest = media_hash(
                media_data
            )

            if digest in seen_hashes:

                print(
                    "Skipped: exact duplicate."
                )

                continue

            # =================================================
            # IMAGE SLOT
            # =================================================

            if wanted == "photo":

                # IMPORTANT:
                # We ONLY accept an actual image.
                #
                # GIF -> NOT converted to image.
                # Video -> NOT converted to image.

                if original_type != "photo":

                    print(
                        f"r/{subreddit}: "
                        f"not an image. "
                        f"Need IMAGE."
                    )

                    continue

                print(
                    f"r/{subreddit}: "
                    f"IMAGE MATCH."
                )

                prepared = compress_photo(
                    media_data
                )

                if prepared is None:

                    print(
                        "Image could not be "
                        "prepared."
                    )

                    continue

                telegram_type = "photo"

            # =================================================
            # GIF SLOT
            # =================================================

            else:

                # IMPORTANT:
                # A normal image can NEVER be
                # converted just to fill the GIF slot.

                if original_type == "photo":

                    print(
                        f"r/{subreddit}: "
                        f"normal IMAGE. "
                        f"Need GIF."
                    )

                    continue

                if original_type not in (
                    "gif",
                    "video"
                ):

                    print(
                        f"r/{subreddit}: "
                        f"unsupported GIF source."
                    )

                    continue

                print(
                    f"r/{subreddit}: "
                    f"animation source found."
                )

                # ------------------------------------------------
                # Literal GIF
                # ------------------------------------------------

                if original_type == "gif":

                    prepared = (
                        media_data
                    )

                    print(
                        "Keeping original GIF."
                    )

                # ------------------------------------------------
                # MP4/WebM representing an animated post
                # ------------------------------------------------

                else:

                    print(
                        "Source is video."
                    )

                    print(
                        "Converting it to "
                        "REAL GIF format."
                    )

                    prepared = (
                        convert_to_real_gif(
                            media_data
                        )
                    )

                    if prepared is None:

                        print(
                            "Could not create "
                            "a real GIF."
                        )

                        continue

                # ------------------------------------------------
                # VERIFY FINAL GIF
                # ------------------------------------------------

                if not (
                    prepared.startswith(
                        b"GIF87a"
                    )
                    or prepared.startswith(
                        b"GIF89a"
                    )
                ):

                    print(
                        "ERROR: Final file is "
                        "not a real GIF."
                    )

                    continue

                telegram_type = "gif"

            # =================================================
            # ACCEPT
            # =================================================

            post["_media_data"] = (
                prepared
            )

            post["_media_type"] = (
                telegram_type
            )

            post["_media_hash"] = (
                digest
            )

            post["_original_type"] = (
                original_type
            )

            print()
            print(
                "========================================"
            )

            print(
                "MEDIA SELECTED"
            )

            print(
                f"Subreddit: "
                f"r/{subreddit}"
            )

            print(
                f"Original: "
                f"{original_type}"
            )

            print(
                f"Telegram: "
                f"{telegram_type}"
            )

            print(
                "========================================"
            )

            return post

        print()
        print(
            f"No {sequence_text(wanted)} "
            f"found in this search round."
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
        timeout=240
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

    if not data:

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
        # IMAGE
        # ----------------------------------------------------

        if media_type == "photo":

            print(
                "Sending as PHOTO."
            )

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
                "Sending as REAL GIF "
                "using sendAnimation."
            )

            result = telegram_upload(
                "sendAnimation",
                "animation",
                "animation.gif",
                "image/gif",
                data
            )

        else:

            print(
                "Unknown Telegram media type.",
                file=sys.stderr
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

        print(
            f"Type: {media_type}"
        )

        print(
            f"Subreddit: "
            f"r/{post.get('subreddit', '')}"
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
# ADVANCE SEQUENCE
# ============================================================

def advance_sequence(
    history
):

    current = history.get(
        "sequence_index",
        0
    )

    try:

        current = int(
            current
        )

    except Exception:

        current = 0

    history["sequence_index"] = (
        (current + 1) % 3
    )


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

    # --------------------------------------------------------
    # CHECK TELEGRAM
    # --------------------------------------------------------

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
        "History:"
    )

    print(
        f"URLs: "
        f"{len(history['urls'])}"
    )

    print(
        f"IDs: "
        f"{len(history['ids'])}"
    )

    print(
        f"Hashes: "
        f"{len(history['hashes'])}"
    )

    print(
        f"Sequence index: "
        f"{history['sequence_index']}"
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
            "NO SUITABLE MEDIA FOUND"
        )

        print(
            "The sequence was NOT advanced."
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
            "History was NOT changed."
        )

        print(
            "Sequence was NOT advanced."
        )

        return

    # --------------------------------------------------------
    # SAVE HISTORY
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

    # --------------------------------------------------------
    # ADVANCE ONLY AFTER SUCCESS
    # --------------------------------------------------------

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
        "Sequence advanced."
    )

    print(
        f"Next required: "
        f"{sequence_text(required_media_type(history))}"
    )

    print(
        "posted.json updated."
    )

    print(
        "========================================"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
