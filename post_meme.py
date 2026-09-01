#!/usr/bin/env python3

"""
Posts a random, fresh meme to a Telegram channel.

Meme source:
    https://meme-api.com

Telegram:
    Telegram Bot API

Environment variables required:
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

Example:
    TELEGRAM_BOT_TOKEN="123456:ABC..." \
    TELEGRAM_CHAT_ID="@mychannel" \
    python meme_bot.py
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

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SUBREDDITS = [
    "funny",
    "wholesomememes",
    "AdviceAnimals",
    "memes",
]

HISTORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "posted.json"
)

HISTORY_LIMIT = 2000

MEME_API_URL = "https://meme-api.com/gimme/{subreddit}/50"

MIN_UPVOTES = 5000


# ============================================================
# HISTORY
# ============================================================

def load_history():
    """Load previously posted meme URLs."""

    if not os.path.exists(HISTORY_FILE):
        return []

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Could not read history: {e}", file=sys.stderr)

    return []


def save_history(history):
    """Save only the most recent HISTORY_LIMIT URLs."""

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(
                history[-HISTORY_LIMIT:],
                f,
                indent=2
            )

    except OSError as e:
        print(f"Warning: Could not save history: {e}", file=sys.stderr)


# ============================================================
# MEME API
# ============================================================

def fetch_candidate_memes():
    """
    Fetch memes from two random subreddits.

    Returns:
        list: A list of meme dictionaries.
    """

    chosen_subreddits = random.sample(
        SUBREDDITS,
        k=min(2, len(SUBREDDITS))
    )

    all_memes = []

    for subreddit in chosen_subreddits:

        url = MEME_API_URL.format(subreddit=subreddit)

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "TelegramMemeBot/1.0"
            }
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=15
            ) as response:

                data = json.loads(
                    response.read().decode("utf-8")
                )

            memes = data.get("memes", [])

            if isinstance(memes, list):
                all_memes.extend(memes)

        except Exception as e:
            print(
                f"Failed to fetch r/{subreddit}: {e}",
                file=sys.stderr
            )

    # IMPORTANT: this was missing in your original code
    return all_memes


# ============================================================
# PICK MEME
# ============================================================

def pick_new_meme(history, attempts=5):
    """
    Find a meme that has not already been posted.

    Prefer memes with at least MIN_UPVOTES.
    """

    seen = set(history)

    for attempt in range(attempts):

        try:
            candidates = fetch_candidate_memes()

        except Exception as e:
            print(
                f"Fetch attempt {attempt + 1} failed: {e}",
                file=sys.stderr
            )

            time.sleep(2)
            continue

        random.shuffle(candidates)

        # First try popular memes
        popular_candidates = [
            meme
            for meme in candidates
            if (
                meme.get("url")
                and meme.get("ups", 0) >= MIN_UPVOTES
                and meme["url"] not in seen
            )
        ]

        if popular_candidates:
            return random.choice(popular_candidates)

        # Fallback: any unseen meme
        for meme in candidates:

            image_url = meme.get("url")

            if image_url and image_url not in seen:
                return meme

    return None


# ============================================================
# TELEGRAM
# ============================================================

def send_to_telegram(meme):
    """Send the meme image to the Telegram channel."""

    if not BOT_TOKEN:
        print(
            "ERROR: TELEGRAM_BOT_TOKEN is not set.",
            file=sys.stderr
        )
        sys.exit(1)

    if not CHAT_ID:
        print(
            "ERROR: TELEGRAM_CHAT_ID is not set.",
            file=sys.stderr
        )
        sys.exit(1)

    image_url = meme.get("url")

    if not image_url:
        print(
            "ERROR: Meme does not contain an image URL.",
            file=sys.stderr
        )
        return False

    api_url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendPhoto"
    )

    payload = {
        "chat_id": CHAT_ID,
        "photo": image_url,
    }

    data = urllib.parse.urlencode(payload).encode("utf-8")

    request = urllib.request.Request(
        api_url,
        data=data,
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            result = json.loads(
                response.read().decode("utf-8")
            )

        if not result.get("ok"):

            print(
                f"Telegram API error: {result}",
                file=sys.stderr
            )

            return False

        print()
        print("========================================")
        print("Meme posted successfully!")
        print("========================================")
        print(f"Title: {meme.get('title', 'Unknown')}")
        print(f"Subreddit: r/{meme.get('subreddit', 'unknown')}")
        print(f"Upvotes: {meme.get('ups', 0)}")
        print(f"URL: {image_url}")
        print("========================================")

        return True

    except urllib.error.HTTPError as e:

        body = e.read().decode(
            "utf-8",
            errors="ignore"
        )

        print(
            f"Telegram HTTP error {e.code}: {body}",
            file=sys.stderr
        )

        return False

    except urllib.error.URLError as e:

        print(
            f"Telegram connection error: {e}",
            file=sys.stderr
        )

        return False

    except Exception as e:

        print(
            f"Unexpected Telegram error: {e}",
            file=sys.stderr
        )

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    print("Starting meme bot...")

    history = load_history()

    print(f"Previously posted memes: {len(history)}")

    meme = pick_new_meme(history)

    if not meme:
        print(
            "Could not find a new meme this run."
        )
        return

    success = send_to_telegram(meme)

    if success:

        image_url = meme.get("url")

        if image_url:
            history.append(image_url)
            save_history(history)

        print("Done.")

    else:
        print(
            "Meme was not posted, so it was not added "
            "to the history."
        )


if __name__ == "__main__":
    main()
