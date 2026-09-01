#!/usr/bin/env python3

"""
Telegram Meme Bot

Fetches random images from Reddit through meme-api.com
and posts them to a Telegram channel.

Current subreddit:
    AnimeGirls

To add more subreddits later, simply edit SUBREDDITS below.

Required environment variables:
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
"""

import os
import sys
import json
import time
import random
import urllib.request
import urllib.error
import urllib.parse


# ============================================================
# CONFIGURATION
# ============================================================

# Add more subreddit names here in the future.
#
# Example:
# SUBREDDITS = [
#     "AnimeGirls",
#     "memes",
#     "funny",
#     "AnimeMemes",
# ]

SUBREDDITS = [
    "AnimeGirls",
]


# Number of different subreddits to use on each run.
# If you have only one subreddit, it automatically uses one.
SUBREDDITS_PER_RUN = 2


# Number of memes requested from each subreddit.
MEMES_PER_SUBREDDIT = 50


# Number of previously posted URLs to remember.
HISTORY_LIMIT = 2000


# How many times to try fetching memes if something fails.
FETCH_ATTEMPTS = 5


# Meme API
MEME_API_URL = "https://meme-api.com/gimme/{subreddit}/{count}"


# Telegram credentials
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# History file will be created beside this Python file.
HISTORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "posted.json"
)


# ============================================================
# HISTORY FUNCTIONS
# ============================================================

def load_history():
    """
    Load the list of previously posted meme URLs.
    """

    if not os.path.exists(HISTORY_FILE):
        return []

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as file:
            history = json.load(file)

        if isinstance(history, list):
            return history

    except Exception as error:
        print(
            f"Warning: Could not load posted.json: {error}",
            file=sys.stderr
        )

    return []


def save_history(history):
    """
    Save the most recent meme URLs.
    """

    try:
        history = history[-HISTORY_LIMIT:]

        with open(HISTORY_FILE, "w", encoding="utf-8") as file:
            json.dump(history, file, indent=2)

    except Exception as error:
        print(
            f"Warning: Could not save posted.json: {error}",
            file=sys.stderr
        )


# ============================================================
# REDDIT / MEME API
# ============================================================

def fetch_candidate_memes():
    """
    Fetch memes from randomly selected subreddits.

    The only thing you need to change in the future
    is the SUBREDDITS list at the top.
    """

    if not SUBREDDITS:
        print(
            "ERROR: SUBREDDITS list is empty.",
            file=sys.stderr
        )
        return []

    # Randomly choose subreddits.
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
        "Checking subreddits: "
        + ", ".join(
            f"r/{subreddit}"
            for subreddit in chosen_subreddits
        )
    )

    for subreddit in chosen_subreddits:

        url = MEME_API_URL.format(
            subreddit=urllib.parse.quote(subreddit),
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

                raw_data = response.read().decode("utf-8")

            data = json.loads(raw_data)

            memes = data.get("memes", [])

            if isinstance(memes, list):

                all_memes.extend(memes)

                print(
                    f"  r/{subreddit}: "
                    f"{len(memes)} memes received"
                )

        except urllib.error.HTTPError as error:

            print(
                f"  r/{subreddit}: HTTP error "
                f"{error.code}",
                file=sys.stderr
            )

        except urllib.error.URLError as error:

            print(
                f"  r/{subreddit}: connection error "
                f"{error}",
                file=sys.stderr
            )

        except json.JSONDecodeError:

            print(
                f"  r/{subreddit}: invalid API response",
                file=sys.stderr
            )

        except Exception as error:

            print(
                f"  r/{subreddit}: {error}",
                file=sys.stderr
            )

    # IMPORTANT:
    # Return the memes to the caller.
    return all_memes


# ============================================================
# CHOOSE A NEW MEME
# ============================================================

def pick_new_meme(history):
    """
    Choose a random meme that has not already been posted.
    """

    seen = set(history)

    for attempt in range(1, FETCH_ATTEMPTS + 1):

        print(
            f"\nFetching memes "
            f"(attempt {attempt}/{FETCH_ATTEMPTS})..."
        )

        try:
            candidates = fetch_candidate_memes()

        except Exception as error:

            print(
                f"Fetch failed: {error}",
                file=sys.stderr
            )

            time.sleep(2)
            continue

        if not candidates:

            print(
                "No memes were returned."
            )

            time.sleep(2)
            continue

        # Randomize the order.
        random.shuffle(candidates)

        # Find an unseen meme.
        for meme in candidates:

            image_url = meme.get("url")

            if not image_url:
                continue

            if image_url in seen:
                continue

            return meme

        print(
            "All fetched memes have already been posted."
        )

    return None


# ============================================================
# TELEGRAM
# ============================================================

def send_to_telegram(meme):
    """
    Send the selected meme to Telegram.
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

    image_url = meme.get("url")

    if not image_url:

        print(
            "ERROR: Meme has no image URL.",
            file=sys.stderr
        )

        return False

    telegram_url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendPhoto"
    )

    # --------------------------------------------------------
    # Caption
    # --------------------------------------------------------

    title = meme.get("title", "")
    subreddit = meme.get("subreddit", "")

    caption_parts = []

    if title:
        caption_parts.append(title)

    if subreddit:
        caption_parts.append(
            f"r/{subreddit}"
        )

    caption = "\n\n".join(caption_parts)

    # Telegram captions have a character limit.
    if len(caption) > 1000:
        caption = caption[:997] + "..."

    payload = {
        "chat_id": CHAT_ID,
        "photo": image_url,
    }

    # Only add caption if there is one.
    if caption:
        payload["caption"] = caption

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
                "Telegram API returned an error:",
                result,
                file=sys.stderr
            )

            return False

        print()
        print("========================================")
        print("        MEME POSTED SUCCESSFULLY")
        print("========================================")
        print(
            f"Title: {meme.get('title', 'Unknown')}"
        )
        print(
            f"Subreddit: "
            f"r/{meme.get('subreddit', 'Unknown')}"
        )
        print(
            f"Upvotes: {meme.get('ups', 0)}"
        )
        print(
            f"Image: {image_url}"
        )
        print("========================================")

        return True

    except urllib.error.HTTPError as error:

        body = error.read().decode(
            "utf-8",
            errors="ignore"
        )

        print(
            f"Telegram HTTP error {error.code}: {body}",
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
    print("          TELEGRAM MEME BOT")
    print("========================================")

    # Check configuration.
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
            "ERROR: No subreddits configured.",
            file=sys.stderr
        )
        sys.exit(1)

    # Load duplicate history.
    history = load_history()

    print(
        f"Previously posted: {len(history)}"
    )

    # Find a new meme.
    meme = pick_new_meme(history)

    if not meme:

        print()
        print(
            "Could not find a new meme."
        )
        print(
            "The API may be unavailable, or "
            "the fetched memes may already be in posted.json."
        )

        return

    # Send it.
    success = send_to_telegram(meme)

    if not success:

        print(
            "\nMeme was NOT posted."
        )

        # Don't save failed posts to history.
        return

    # Save successful post to history.
    image_url = meme.get("url")

    if image_url:
        history.append(image_url)
        save_history(history)

    print(
        "\nHistory saved successfully."
    )

    print("Bot finished.")


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
