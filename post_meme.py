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


# ============================================================
# SUBREDDITS
# ============================================================

# Add/remove subreddit names here.
#
# Example:
#
# SUBREDDITS = [
#     "AnimeGirls",
#     "AnimeMemes",
#     "anime",
# ]

SUBREDDITS = [
    "ecchi",
    "OverOppai",
    "CFNM_Hentai",
    "EcchiCurves"
]


# ============================================================
# SETTINGS
# ============================================================

# Number of subreddits checked on each run.
#
# If you have 5 subreddits and this is 2,
# 2 are randomly selected each run.
SUBREDDITS_PER_RUN = 2

# Number of Reddit posts requested from each subreddit.
MEMES_PER_SUBREDDIT = 50

# How many previous posts to remember.
HISTORY_LIMIT = 5000

# Number of times to request another batch if needed.
FETCH_ATTEMPTS = 8

# Maximum image size used for duplicate checking.
MAX_IMAGE_SIZE = 15 * 1024 * 1024

# Reddit API
MEME_API_URL = "https://meme-api.com/gimme/{subreddit}/{count}"


# ============================================================
# TELEGRAM
# ============================================================

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# ============================================================
# HISTORY
# ============================================================

HISTORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "posted.json"
)


def empty_history():
    return {
        "urls": [],
        "ids": [],
        "hashes": []
    }


def load_history():
    """Load duplicate history."""

    if not os.path.exists(HISTORY_FILE):
        return empty_history()

    try:
        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        # New format
        if isinstance(data, dict):
            return {
                "urls": data.get("urls", []),
                "ids": data.get("ids", []),
                "hashes": data.get("hashes", [])
            }

        # Old posted.json compatibility
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
    """Save duplicate history."""

    history["urls"] = history.get(
        "urls", []
    )[-HISTORY_LIMIT:]

    history["ids"] = history.get(
        "ids", []
    )[-HISTORY_LIMIT:]

    history["hashes"] = history.get(
        "hashes", []
    )[-HISTORY_LIMIT:]

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
# DOWNLOAD IMAGE
# ============================================================

def download_image(image_url):
    """
    Download the image so we can calculate its hash.

    If the image cannot be downloaded, return None.
    We deliberately do NOT post it in that case, because
    we cannot guarantee duplicate protection.
    """

    try:
        request = urllib.request.Request(
            image_url,
            headers={
                "User-Agent": "TelegramRedditImageBot/1.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=25
        ) as response:

            content_length = response.headers.get(
                "Content-Length"
            )

            if content_length:
                try:
                    if int(content_length) > MAX_IMAGE_SIZE:
                        print("Skipped: image is too large.")
                        return None
                except ValueError:
                    pass

            data = response.read(
                MAX_IMAGE_SIZE + 1
            )

            if len(data) > MAX_IMAGE_SIZE:
                print("Skipped: image is too large.")
                return None

            if not data:
                return None

            return data

    except Exception as error:
        print(
            f"Image download failed: {error}",
            file=sys.stderr
        )
        return None


# ============================================================
# IMAGE HASH
# ============================================================

def image_hash(image_data):
    """
    SHA-256 hash of the actual downloaded image.

    This means the same exact image can be detected even
    when it appears under a different URL.
    """

    return hashlib.sha256(
        image_data
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
                "User-Agent": "TelegramRedditImageBot/1.0"
            }
        )

        try:

            with urllib.request.urlopen(
                request,
                timeout=25
            ) as response:

                raw = response.read().decode(
                    "utf-8"
                )

            data = json.loads(raw)

            posts = data.get(
                "memes",
                []
            )

            if isinstance(posts, list):

                all_posts.extend(posts)

                print(
                    f"r/{subreddit}: "
                    f"{len(posts)} posts received"
                )

        except urllib.error.HTTPError as error:

            print(
                f"r/{subreddit}: HTTP {error.code}",
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
# FIND NEW IMAGE
# ============================================================

def find_new_image(history):

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
            f"Searching batch "
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

            # -----------------------------------------------
            # URL duplicate check
            # -----------------------------------------------

            if url in seen_urls:

                print("Skipped duplicate URL.")
                continue

            # -----------------------------------------------
            # Reddit post duplicate check
            # -----------------------------------------------

            if post_id and post_id in seen_ids:

                print("Skipped duplicate Reddit post.")
                continue

            # -----------------------------------------------
            # Download actual image
            # -----------------------------------------------

            print(
                f"Checking image: {url}"
            )

            image_data = download_image(url)

            # IMPORTANT:
            #
            # If we can't download it, don't post it.
            # Otherwise we can't guarantee duplicate protection.
            if image_data is None:

                print(
                    "Skipped because image could not "
                    "be downloaded."
                )

                continue

            # -----------------------------------------------
            # Hash actual image
            # -----------------------------------------------

            digest = image_hash(
                image_data
            )

            # -----------------------------------------------
            # Actual image duplicate check
            # -----------------------------------------------

            if digest in seen_hashes:

                print(
                    "Skipped: EXACT IMAGE was already posted."
                )

                continue

            # -----------------------------------------------
            # NEW IMAGE
            # -----------------------------------------------

            print(
                "NEW IMAGE FOUND!"
            )

            post["_image_hash"] = digest
            post["_image_data"] = image_data

            return post

        print(
            "No new image found in this batch."
        )

    return None


# ============================================================
# TELEGRAM SEND
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

    image_data = post.get(
        "_image_data"
    )

    if not image_data:
        print(
            "ERROR: Image data is missing.",
            file=sys.stderr
        )
        return False

    telegram_url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendPhoto"
    )

    # --------------------------------------------------------
    # Multipart upload.
    #
    # We upload the actual downloaded image instead of asking
    # Telegram to download the Reddit URL.
    #
    # NO CAPTION.
    # --------------------------------------------------------

    boundary = (
        "----TelegramRedditBot"
        + hashlib.md5(
            os.urandom(16)
        ).hexdigest()
    )

    body = bytearray()

    # chat_id
    body.extend(
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; '
            'name="chat_id"\r\n\r\n'
            f"{CHAT_ID}\r\n"
        ).encode()
    )

    # photo
    body.extend(
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; '
            'name="photo"; filename="image.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode()
    )

    body.extend(image_data)

    body.extend(
        f"\r\n--{boundary}--\r\n".encode()
    )

    request = urllib.request.Request(
        telegram_url,
        data=bytes(body),
        method="POST",
        headers={
            "Content-Type":
                f"multipart/form-data; boundary={boundary}"
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=40
        ) as response:

            result = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

        if not result.get("ok"):

            print(
                "Telegram error:",
                result,
                file=sys.stderr
            )

            return False

        print()
        print("========================================")
        print("       POSTED SUCCESSFULLY")
        print("========================================")
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
        print("========================================")

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
    print("========================================")
    print("       REDDIT → TELEGRAM BOT")
    print("       INTERVAL: ~15 MINUTES")
    print("========================================")

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
        f"Stored image hashes: "
        f"{len(history['hashes'])}"
    )

    post = find_new_image(
        history
    )

    if not post:

        print()
        print(
            "No new image was found this run."
        )

        return

    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

    success = send_to_telegram(
        post
    )

    if not success:

        print(
            "Posting failed. History was NOT changed."
        )

        return

    # --------------------------------------------------------
    # SAVE ONLY AFTER SUCCESSFUL POST
    # --------------------------------------------------------

    url = post.get(
        "url"
    )

    post_id = post.get(
        "postLink",
        ""
    )

    digest = post.get(
        "_image_hash"
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
        "Finished."
    )


if __name__ == "__main__":
    main()
