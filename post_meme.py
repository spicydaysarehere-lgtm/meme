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

# Number of subreddits checked per run.
SUBREDDITS_PER_RUN = 2

# Number of Reddit posts requested.
MEMES_PER_SUBREDDIT = 50

# Number of search batches.
FETCH_ATTEMPTS = 8

# History size.
HISTORY_LIMIT = 5000

# Maximum Reddit download size.
MAX_MEDIA_SIZE = 50 * 1024 * 1024

# Keep ordinary images safely below Telegram's photo limit.
TELEGRAM_IMAGE_LIMIT = 9 * 1024 * 1024

# Keep generated GIF safely below Telegram's animation limit.
TELEGRAM_GIF_LIMIT = 47 * 1024 * 1024

# GIF conversion defaults.
GIF_FPS = 15
GIF_MAX_WIDTH = 640

# Maximum duration used when converting a video-like GIF source.
# Set to 0 to keep the full duration.
GIF_MAX_DURATION = 0

# Reddit/Meme API.
MEME_API_URL = (
    "https://meme-api.com/gimme/{subreddit}/{count}"
)

REDDIT_JSON_URL = (
    "https://www.reddit.com/r/{subreddit}/new.json"
)

USER_AGENT = (
    "RedditTelegramMediaBot/7.0 "
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

        # 0 = image #1
        # 1 = image #2
        # 2 = GIF
        #
        # Then it goes back to 0.
        "sequence_index": 0,
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

        # ----------------------------------------------------
        # New history format
        # ----------------------------------------------------

        if isinstance(
            data,
            dict
        ):

            sequence_index = data.get(
                "sequence_index",
                0
            )

            try:
                sequence_index = int(
                    sequence_index
                )
            except Exception:
                sequence_index = 0

            sequence_index %= 3

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
                    sequence_index,
            }

        # ----------------------------------------------------
        # Old list format
        # ----------------------------------------------------

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


def save_history(history):

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

    sequence_index = history.get(
        "sequence_index",
        0
    )

    try:
        sequence_index = int(
            sequence_index
        )
    except Exception:
        sequence_index = 0

    history["sequence_index"] = (
        sequence_index % 3
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

            wait = min(
                2 ** attempt,
                15
            )

            print(
                last_error,
                file=sys.stderr
            )

            if attempt < attempts:

                time.sleep(
                    wait
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

                continue

    print(
        f"All requests failed: "
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

    for post in posts:

        if isinstance(
            post,
            dict
        ):

            post["_source"] = (
                "meme-api"
            )

    print(
        f"Meme API returned "
        f"{len(posts)} posts for "
        f"r/{subreddit}"
    )

    return posts


# ============================================================
# REDDIT FALLBACK
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
        f"Reddit fallback returned "
        f"{len(posts)} posts for "
        f"r/{subreddit}"
    )

    return posts


# ============================================================
# FETCH ALL CANDIDATES
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

        all_posts.extend(
            posts
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
                    USER_AGENT,
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
                "Skipped: source is over "
                "50 MB."
            )

            return None, ""

        if not data:

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
# DETECT MEDIA
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

    os.close(fd)

    with open(
        path,
        "wb"
    ) as file:

        file.write(data)

    return path


# ============================================================
# CONVERT ANY ANIMATION TO REAL GIF
# ============================================================

def convert_to_real_gif(
    data,
    source_is_gif=False
):

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

        # ----------------------------------------------------
        # GIF SETTINGS
        # ----------------------------------------------------

        scale_filter = (
            "scale="
            f"min({GIF_MAX_WIDTH},iw):"
            "min(ih,ih):"
            "force_original_aspect_ratio=decrease"
        )

        # Correct simple scaling.
        scale_filter = (
            f"scale={GIF_MAX_WIDTH}:-1:"
            "force_original_aspect_ratio=decrease"
        )

        # ----------------------------------------------------
        # Optional duration
        # ----------------------------------------------------

        duration_filter = []

        if GIF_MAX_DURATION > 0:

            duration_filter = [
                "-t",
                str(
                    GIF_MAX_DURATION
                )
            ]

        # ----------------------------------------------------
        # STEP 1 — CREATE PALETTE
        # ----------------------------------------------------

        palette_command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",

            "-i",
            source,

            *duration_filter,

            "-vf",
            (
                f"fps={GIF_FPS},"
                f"{scale_filter},"
                "format=rgb24,"
                "palettegen="
                "stats_mode=diff"
            ),

            palette,
        ]

        result = subprocess.run(
            palette_command,
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

            print(
                "GIF palette generation failed:"
            )

            print(
                result.stderr.decode(
                    "utf-8",
                    errors="ignore"
                )[-3000:],
                file=sys.stderr
            )

            return None

        # ----------------------------------------------------
        # STEP 2 — APPLY PALETTE AND CREATE GIF
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

            *duration_filter,

            "-filter_complex",
            (
                f"[0:v]"
                f"fps={GIF_FPS},"
                f"{scale_filter}"
                "[video];"
                "[video][1:v]"
                "paletteuse="
                "dither=sierra2_4a"
            ),

            "-loop",
            "0",

            output,
        ]

        result = subprocess.run(
            gif_command,
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

            print(
                "GIF creation failed:"
            )

            print(
                result.stderr.decode(
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

        if not gif_data.startswith(
            b"GIF"
        ):

            print(
                "FFmpeg did not create "
                "a valid GIF."
            )

            return None

        size_mb = (
            len(gif_data)
            / 1024
            / 1024
        )

        print(
            f"Generated REAL GIF: "
            f"{size_mb:.2f} MB"
        )

        # ----------------------------------------------------
        # If too large, try smaller GIF
        # ----------------------------------------------------

        if len(gif_data) > (
            TELEGRAM_GIF_LIMIT
        ):

            print(
                "GIF is too large."
            )

            print(
                "Trying stronger compression..."
            )

            return convert_large_gif(
                data
            )

        return gif_data

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
# STRONGER GIF COMPRESSION
# ============================================================

def convert_large_gif(
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
                            f"fps={fps},"
                            f"scale={width}:-1:"
                            "force_original_aspect_ratio=decrease,"
                            "palettegen="
                        ),

                        palette,
                    ],
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

                    continue

                # GIF.
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
                            f"fps={fps},"
                            f"scale={width}:-1:"
                            "force_original_aspect_ratio=decrease"
                            "[v];"
                            "[v][1:v]"
                            "paletteuse="
                            "dither=bayer:bayer_scale=2"
                        ),

                        "-loop",
                        "0",

                        output,
                    ],
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

                    continue

                with open(
                    output,
                    "rb"
                ) as file:

                    gif_data = file.read()

                if not gif_data.startswith(
                    b"GIF"
                ):

                    continue

                size_mb = (
                    len(gif_data)
                    / 1024
                    / 1024
                )

                print(
                    f"Compression "
                    f"{width}px / {fps}fps: "
                    f"{size_mb:.2f} MB"
                )

                if len(gif_data) <= (
                    TELEGRAM_GIF_LIMIT
                ):

                    print(
                        "GIF compressed successfully."
                    )

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

        print(
            "Unable to make the GIF small "
            "enough for Telegram."
        )

        return None

    finally:

        try:

            os.remove(
                source
            )

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
        "Large photo detected."
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

            output = (
                result.stdout
            )

            if not output:
                continue

            size_mb = (
                len(output)
                / 1024
                / 1024
            )

            print(
                f"Photo compression "
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
# SHA256
# ============================================================

def media_hash(
    data
):

    return hashlib.sha256(
        data
    ).hexdigest()


# ============================================================
# DETERMINE REQUIRED SEQUENCE TYPE
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

    if index in (
        0,
        1
    ):

        return "photo"

    return "gif"


def sequence_description(
    required_type
):

    if required_type == "photo":

        return "IMAGE"

    return "GIF"


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

    wanted = required_media_type(
        history
    )

    print()
    print(
        "========================================"
    )

    print(
        "SEQUENCE STATUS"
    )

    print(
        f"Next required media: "
        f"{sequence_description(wanted)}"
    )

    print(
        "Pattern: IMAGE → IMAGE → GIF"
    )

    print(
        "========================================"
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

            if attempt < FETCH_ATTEMPTS:

                time.sleep(3)

                continue

            break

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
                download_media(
                    url
                )
            )

            if media_data is None:
                continue

            original_type = (
                detect_media_type(
                    url,
                    media_data,
                    content_type
                )
            )

            print(
                f"Detected source type: "
                f"{original_type}"
            )

            if original_type == "unknown":

                print(
                    "Skipped unknown format."
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

            # =================================================
            # REQUIRED IMAGE
            # =================================================

            if wanted == "photo":

                if original_type != "photo":

                    print(
                        "Current sequence requires "
                        "an IMAGE."
                    )

                    print(
                        "Skipping animation."
                    )

                    continue

                prepared = compress_photo(
                    media_data
                )

                if prepared is None:

                    print(
                        "Photo could not be prepared."
                    )

                    continue

                upload_type = "photo"

            # =================================================
            # REQUIRED GIF
            # =================================================

            else:

                if original_type not in (
                    "gif",
                    "video"
                ):

                    print(
                        "Current sequence requires "
                        "a GIF."
                    )

                    print(
                        "Skipping photo."
                    )

                    continue

                print()
                print(
                    "Current sequence requires "
                    "a GIF."
                )

                print(
                    "Converting animation "
                    "to REAL GIF format..."
                )

                prepared = convert_to_real_gif(
                    media_data,
                    source_is_gif=(
                        original_type == "gif"
                    )
                )

                if prepared is None:

                    print(
                        "Could not create a valid "
                        "Telegram GIF."
                    )

                    continue

                upload_type = "gif"

            # =================================================
            # SUCCESSFUL CANDIDATE
            # =================================================

            post["_media_data"] = (
                prepared
            )

            post["_media_type"] = (
                upload_type
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
                "NEW MEDIA SELECTED"
            )

            print(
                f"Reddit subreddit: "
                f"r/{post.get('subreddit', '')}"
            )

            print(
                f"Original type: "
                f"{original_type}"
            )

            print(
                f"Telegram type: "
                f"{upload_type}"
            )

            print(
                "========================================"
            )

            return post

        print(
            "No suitable media found "
            f"for required type: {wanted}"
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
            response
            .read()
            .decode(
                "utf-8"
            )
        )


# ============================================================
# TELEGRAM SEND
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
        # PHOTO
        # ----------------------------------------------------

        if media_type == "photo":

            print(
                "Using sendPhoto..."
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

            # IMPORTANT:
            # Always send a real .gif file.
            print(
                "Using sendAnimation "
                "with REAL GIF..."
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
                "Unsupported Telegram type.",
                file=sys.stderr
            )

            return False

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

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
            f"Telegram type: "
            f"{media_type}"
        )

        print(
            f"Subreddit: "
            f"r/{post.get('subreddit', '')}"
        )

        print(
            f"URL: "
            f"{post.get('url', '')}"
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
        "GIFS ALWAYS CONVERTED TO REAL GIF"
    )

    print(
        "========================================"
    )

    # --------------------------------------------------------
    # ENVIRONMENT
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
        f"Reddit IDs: "
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
            "Sequence was NOT advanced."
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
    # SAVE DUPLICATE HISTORY
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
    # ADVANCE 2 IMAGE / 1 GIF CYCLE
    # --------------------------------------------------------

    advance_sequence(
        history
    )

    save_history(
        history
    )

    print()
    print(
        "Sequence advanced."
    )

    next_type = required_media_type(
        history
    )

    print(
        f"Next run requires: "
        f"{sequence_description(next_type)}"
    )

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
