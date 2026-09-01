#!/usr/bin/env python3

"""
Telegram Reddit Image Bot

- Fetches images from configured subreddits using meme-api.com
- Posts ONE image to Telegram
- NO caption
- NO upvote filter
- NO NSFW filter
- Prevents reposting the same image URL
- Saves posted URLs in posted.json
- Easy to add more subreddits later

Required GitHub Actions environment variables:

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
# SUBREDDITS
# ============================================================

# Add more subreddits here whenever you want.
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

# How many subreddits to check per run.
#
# You currently have only one, so AnimeGirls is checked.
# If you add more, this will randomly choose 2 of them.
SUBREDDITS_PER_RUN = 2


# Number of posts requested from each subreddit.
MEMES_PER_SUBREDDIT = 50


# Number of previously posted URLs to remember.
HISTORY_LIMIT = 2000


# Number of attempts to fetch a new image.
FETCH_ATTEMPTS = 5


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
    """Load previously posted image URLs."""

    if not os.path.exists(HISTORY_FILE):
        return []

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            history = json.load(file)

        if isinstance(history, list):
            return history

    except Exception as error:

        print(
            f"Warning: Could not load posted.json: {error}",
            file=sys.stderr
        )

    return []


# ============================================================
# SAVE HISTORY
# ============================================================

def save_history(history):
    """Save recently posted image URLs."""

    try:

        history = history[-HISTORY_LIMIT:]

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
            f"Warning: Could not save posted.json: {error}",
            file=sys.stderr
        )


# ============================================================
# FETCH POSTS
# ============================================================

def fetch_candidate_memes():
    """
    Fetch posts from the configured subreddits.

    There is deliberately no content/NSFW/upvote filtering
    performed by this script.
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


            data = json.loads(raw_data)


            memes = data.get(
                "memes",
                []
            )


            if isinstance(memes, list):

                all_memes.extend(memes)

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
# PICK NEW IMAGE
# ============================================================

def pick_new_meme(history):
    """
    Pick a random image that hasn't been posted before.

    No upvote filtering.
    No NSFW filtering.
    No title filtering.
    No subreddit filtering.

    The only selection requirement is that the post
    contains a URL and hasn't already been posted.
    """

    seen = set(history)


    for attempt in range(
        1,
        FETCH_ATTEMPTS + 1
    ):

        print(
            f"\nFetch attempt "
            f"{attempt}/{FETCH_ATTEMPTS}"
        )


        candidates = fetch_candidate_memes()


        if not candidates:

            print(
                "No posts were returned."
            )

            time.sleep(2)

            continue


        # Completely randomize the results.
        random.shuffle(candidates)


        for meme in candidates:

            image_url = meme.get(
                "url"
            )


            # No URL = cannot send it.
            if not image_url:
                continue


            # Skip previously posted images.
            if image_url in seen:
                continue


            return meme


        print(
            "All returned images were already posted."
        )


    return None


# ============================================================
# SEND TO TELEGRAM
# ============================================================

def send_to_telegram(meme):
    """
    Send ONLY the image to Telegram.

    No caption is sent.
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
    # IMPORTANT:
    #
    # ONLY chat_id and photo are sent.
    #
    # There is NO caption.
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
            f"Image URL: {image_url}"
        )
        print(
            "Caption: NONE"
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
    print("        RUNNING EVERY 5 MINUTES")
    print("========================================")


    # --------------------------------------------------------
    # Check credentials
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
        f"Previously posted: {len(history)}"
    )


    # --------------------------------------------------------
    # Find image
    # --------------------------------------------------------

    meme = pick_new_meme(history)


    if not meme:

        print()
        print(
            "Could not find a new image."
        )

        return


    # --------------------------------------------------------
    # Send image
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
    # Save successful post
    # --------------------------------------------------------

    image_url = meme.get(
        "url"
    )


    if image_url:

        history.append(
            image_url
        )

        save_history(
            history
        )


    print()
    print(
        "History saved."
    )

    print(
        "Finished successfully."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
