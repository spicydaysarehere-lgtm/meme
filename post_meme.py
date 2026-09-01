#!/usr/bin/env python3

"""
Telegram Reddit Image Bot

Features:
    - Fetches images from configured subreddits
    - Posts ONE image to Telegram
    - No caption
    - No upvote filter
    - No NSFW filter
    - Prevents duplicate images
    - Detects duplicates even when the image URL changes
    - Saves image hashes in posted.json
    - Easy to add more subreddits later

Required environment variables:

    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
"""

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

# Add more subreddits here later.
#
# Example:
#
# SUBREDDITS = [
#     "AnimeGirls",
#     "AnimeMemes",
#     "funny",
#     "memes",
# ]

SUBREDDITS = [
    "AnimeGirls",
]


# ============================================================
# SETTINGS
# ============================================================

# Number of subreddits to check on each run.
#
# Currently there is only one.
# If you add more, the bot randomly chooses 2 each run.
SUBREDDITS_PER_RUN = 2


# Number of Reddit posts requested per subreddit.
MEMES_PER_SUBREDDIT = 50


# Maximum number of image hashes to remember.
HISTORY_LIMIT = 5000


# Number of attempts to find a new image.
FETCH_ATTEMPTS = 5


# Maximum size of an image we will download for duplicate checking.
# 15 MB is more than enough for normal Reddit images.
MAX_IMAGE_SIZE = 15 * 1024 * 1024


# Meme API
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
# HISTORY FILE
# ============================================================

HISTORY_FILE = os.path.join(
    os.path.dirname(
        os.path.abspath(__file__)
    ),
    "posted.json"
)


# ============================================================
# LOAD HISTORY
# ============================================================

def load_history():
    """
    Load duplicate history.

    The history format is:

    {
        "urls": [...],
        "ids": [...],
        "hashes": [...]
    }
    """

    if not os.path.exists(HISTORY_FILE):

        return {
            "urls": [],
            "ids": [],
            "hashes": []
        }


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

        if isinstance(data, dict):

            return {
                "urls": data.get("urls", []),
                "ids": data.get("ids", []),
                "hashes": data.get("hashes", [])
            }


        # ----------------------------------------------------
        # Compatibility with your old posted.json
        # ----------------------------------------------------

        if isinstance(data, list):

            return {
                "urls": data,
                "ids": [],
                "hashes": []
            }


    except Exception as error:

        print(
            f"Warning: Could not load history: {error}",
            file=sys.stderr
        )


    return {
        "urls": [],
        "ids": [],
        "hashes": []
    }


# ============================================================
# SAVE HISTORY
# ============================================================

def save_history(history):
    """
    Save duplicate history.
    """

    try:

        history["urls"] = history.get(
            "urls",
            []
        )[-HISTORY_LIMIT:]


        history["ids"] = history.get(
            "ids",
            []
        )[-HISTORY_LIMIT:]


        history["hashes"] = history.get(
            "hashes",
            []
        )[-HISTORY_LIMIT:]


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
            f"Warning: Could not save history: {error}",
            file=sys.stderr
        )


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(image_url):
    """
    Download an image and return its bytes.

    Used only to calculate the image hash.

    Returns:
        bytes or None
    """

    try:

        request = urllib.request.Request(
            image_url,
            headers={
                "User-Agent": "TelegramMemeBot/1.0"
            }
        )


        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            content_length = response.headers.get(
                "Content-Length"
            )


            # Avoid unexpectedly huge files.
            if content_length:

                try:

                    if int(content_length) > MAX_IMAGE_SIZE:

                        print(
                            "Image is too large to check."
                        )

                        return None

                except ValueError:

                    pass


            image_data = response.read(
                MAX_IMAGE_SIZE + 1
            )


            if len(image_data) > MAX_IMAGE_SIZE:

                print(
                    "Image is too large to check."
                )

                return None


            return image_data


    except Exception as error:

        print(
            f"Could not download image for duplicate "
            f"checking: {error}",
            file=sys.stderr
        )

        return None


# ============================================================
# IMAGE HASH
# ============================================================

def get_image_hash(image_data):
    """
    Generate SHA-256 hash of the actual image.

    Two identical image files produce the same hash.
    """

    return hashlib.sha256(
        image_data
    ).hexdigest()


# ============================================================
# FETCH REDDIT POSTS
# ============================================================

def fetch_candidate_memes():
    """
    Fetch posts from configured subreddits.

    There is deliberately:
        - no upvote filter
        - no NSFW filter
        - no title filter
        - no popularity filter
    """

    if not SUBREDDITS:

        print(
            "ERROR: SUBREDDITS list is empty.",
            file=sys.stderr
        )

        return []


    number_to_choose = min(
        SUBREDDITS_PER_RUN,
        len(SUBREDDITS)
    )


    chosen_subreddits = random.sample(
        SUBREDDITS,
        number_to_choose
    )


    all_memes = []


    print(
        "Checking: "
        + ", ".join(
            f"r/{subreddit}"
            for subreddit in chosen_subreddits
        )
    )


    for subreddit in chosen_subreddits:

        encoded_subreddit = urllib.parse.quote(
            subreddit
        )


        url = MEME_API_URL.format(
            subreddit=encoded_subreddit,
            count=MEMES_PER_SUBREDDIT
        )


        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "TelegramMemeBot/1.0"
            }
        )


        try:

            with urllib.request.urlopen(
                request,
                timeout=20
            ) as response:

                raw_data = response.read().decode(
                    "utf-8"
                )


            data = json.loads(
                raw_data
            )


            memes = data.get(
                "memes",
                []
            )


            if isinstance(memes, list):

                all_memes.extend(
                    memes
                )


                print(
                    f"r/{subreddit}: "
                    f"{len(memes)} posts received"
                )


        except urllib.error.HTTPError as error:

            print(
                f"r/{subreddit}: HTTP error "
                f"{error.code}",
                file=sys.stderr
            )


        except urllib.error.URLError as error:

            print(
                f"r/{subreddit}: connection error "
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


    return all_memes


# ============================================================
# FIND NEW IMAGE
# ============================================================

def pick_new_meme(history):
    """
    Find an image that has NEVER been posted before.

    Duplicate detection uses:

        1. Reddit post ID
        2. Image URL
        3. SHA-256 hash of the actual image

    The image hash is the strongest protection because
    the same picture can have different URLs.
    """

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
            f"Fetch attempt "
            f"{attempt}/{FETCH_ATTEMPTS}"
        )


        candidates = fetch_candidate_memes()


        if not candidates:

            print(
                "No posts were returned."
            )

            time.sleep(2)

            continue


        random.shuffle(
            candidates
        )


        for meme in candidates:

            image_url = meme.get(
                "url"
            )


            reddit_id = meme.get(
                "postLink",
                ""
            )


            # ------------------------------------------------
            # Basic URL check
            # ------------------------------------------------

            if not image_url:

                continue


            # ------------------------------------------------
            # Check URL
            # ------------------------------------------------

            if image_url in seen_urls:

                print(
                    "Skipped duplicate URL."
                )

                continue


            # ------------------------------------------------
            # Check Reddit post
            # ------------------------------------------------

            if reddit_id and reddit_id in seen_ids:

                print(
                    "Skipped duplicate Reddit post."
                )

                continue


            # ------------------------------------------------
            # Download image for hash comparison
            # ------------------------------------------------

            print(
                f"Checking image: {image_url}"
            )


            image_data = download_image(
                image_url
            )


            # If the image can't be downloaded,
            # we can still use URL/post-ID checking.
            if image_data is None:

                print(
                    "Could not calculate image hash. "
                    "Using URL/post ID only."
                )

                return meme


            # ------------------------------------------------
            # Calculate SHA-256 hash
            # ------------------------------------------------

            image_hash = get_image_hash(
                image_data
            )


            # ------------------------------------------------
            # Check actual image
            # ------------------------------------------------

            if image_hash in seen_hashes:

                print(
                    "SKIPPED: This exact image "
                    "was already posted."
                )

                continue


            # ------------------------------------------------
            # New image found
            # ------------------------------------------------

            print(
                "NEW IMAGE FOUND!"
            )


            # Store temporary hash so main()
            # can save it after Telegram succeeds.
            meme["_image_hash"] = image_hash


            return meme


        print(
            "No completely new images found "
            "in this batch."
        )


    return None


# ============================================================
# SEND TO TELEGRAM
# ============================================================

def send_to_telegram(meme):
    """
    Send ONLY the image.

    No caption.
    """

    if not BOT_TOKEN:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN is not set.",
            file=sys.stderr
        )

        return False


    if not CHAT_ID:

        print(
            "ERROR: TELEGRAM_CHAT_ID is not set.",
            file=sys.stderr
        )

        return False


    image_url = meme.get(
        "url"
    )


    if not image_url:

        print(
            "ERROR: Image URL is missing.",
            file=sys.stderr
        )

        return False


    telegram_url = (
        "https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendPhoto"
    )


    # ========================================================
    # ONLY image + chat ID.
    #
    # NO CAPTION.
    # ========================================================

    payload = {
        "chat_id": CHAT_ID,
        "photo": image_url,
    }


    data = urllib.parse.urlencode(
        payload
    ).encode("utf-8")


    request = urllib.request.Request(
        telegram_url,
        data=data,
        method="POST"
    )


    try:

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            result = json.loads(
                response.read().decode("utf-8")
            )


        if not result.get("ok"):

            print(
                "Telegram API error:",
                result,
                file=sys.stderr
            )

            return False


        print()
        print("========================================")
        print("       IMAGE POSTED SUCCESSFULLY")
        print("========================================")
        print(
            f"Subreddit: "
            f"r/{meme.get('subreddit', 'unknown')}"
        )
        print(
            f"Image: {image_url}"
        )
        print(
            "Caption: NONE"
        )
        print(
            "Duplicate protection: ACTIVE"
        )
        print("========================================")


        return True


    except urllib.error.HTTPError as error:

        body = error.read().decode(
            "utf-8",
            errors="ignore"
        )


        print(
            f"Telegram HTTP error "
            f"{error.code}: {body}",
            file=sys.stderr
        )


        return False


    except urllib.error.URLError as error:

        print(
            f"Telegram connection error: {error}",
            file=sys.stderr
        )


        return False


    except Exception as error:

        print(
            f"Unexpected Telegram error: {error}",
            file=sys.stderr
        )


        return False


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("========================================")
    print("        TELEGRAM IMAGE BOT")
    print("        RUN: EVERY ~5 MINUTES")
    print("========================================")


    # --------------------------------------------------------
    # Check Telegram credentials
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


    # --------------------------------------------------------
    # Check subreddit configuration
    # --------------------------------------------------------

    if not SUBREDDITS:

        print(
            "ERROR: No subreddits configured.",
            file=sys.stderr
        )

        sys.exit(1)


    # --------------------------------------------------------
    # Load history
    # --------------------------------------------------------

    history = load_history()


    print(
        f"Previously stored URLs: "
        f"{len(history['urls'])}"
    )


    print(
        f"Previously stored image hashes: "
        f"{len(history['hashes'])}"
    )


    # --------------------------------------------------------
    # Find a new image
    # --------------------------------------------------------

    meme = pick_new_meme(
        history
    )


    if not meme:

        print()
        print(
            "Could not find a completely new image."
        )

        return


    # --------------------------------------------------------
    # Post image
    # --------------------------------------------------------

    success = send_to_telegram(
        meme
    )


    if not success:

        print(
            "\nImage was NOT posted."
        )

        return


    # --------------------------------------------------------
    # Save duplicate information
    # ONLY after successful Telegram post.
    # --------------------------------------------------------

    image_url = meme.get(
        "url"
    )


    reddit_id = meme.get(
        "postLink",
        ""
    )


    image_hash = meme.get(
        "_image_hash"
    )


    if image_url:

        history["urls"].append(
            image_url
        )


    if reddit_id:

        history["ids"].append(
            reddit_id
        )


    if image_hash:

        history["hashes"].append(
            image_hash
        )


    save_history(
        history
    )


    print()
    print(
        "Duplicate history updated."
    )


    print(
        "Bot finished successfully."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
