#!/usr/bin/env python3
"""
Posts a random, fresh meme to a Telegram channel.
Free meme source: https://meme-api.com (pulls from top meme subreddits, no API key needed)
Free Telegram posting: Telegram Bot API (no cost)

Duplicate protection: keeps a rolling history file (posted.json) of recently
posted image URLs/ids so the same meme isn't sent twice in a row.
"""

import os
import sys
import json
import time
import random
import urllib.request
import urllib.error
import urllib.parse

# ---------- Configuration (set these as environment variables / GitHub Secrets) ----------
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")  # e.g. @yourchannelusername or numeric chat id

# Subreddits to pull memes from — the most universally mainstream, broad-appeal ones
SUBREDDITS = ["memes"]

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posted.json")
HISTORY_LIMIT = 2000  # remember many more posted memes now that the pool is much bigger

# Fetch a much bigger batch per subreddit so the pool doesn't run dry at a
# post-every-10-minutes pace
MEME_API_URL = "https://meme-api.com/gimme/{subreddit}/50"

# Only post memes that already proved broadly popular on Reddit itself —
# a high upvote count is the closest free signal we have for "most people
# will find this relatable/funny", since it means thousands of people
# already reacted well to it.
MIN_UPVOTES = 5000


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history[-HISTORY_LIMIT:], f)


def fetch_candidate_memes():
    """Fetch a batch of memes from two random subreddits via meme-api.com"""
    chosen_subreddits = random.sample(SUBREDDITS, k=min(2, len(SUBREDDITS)))
    all_memes = []
    for subreddit in chosen_subreddits:
        url = MEME_API_URL.format(subreddit=subreddit)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        memes = data.get("memes", [])
        all_memes.extend(memes)
    # Filter out NSFW/spoiler posts and anything below the popularity bar
    all_memes = [
        m for m in all_memes
        if not m.get("spoiler") and m.get("ups", 0) >= MIN_UPVOTES
    ]
    return all_memes


def pick_new_meme(history, attempts=5):
    seen = set(history)
    for _ in range(attempts):
        try:
            candidates = fetch_candidate_memes()
        except Exception as e:
            print(f"Fetch attempt failed: {e}", file=sys.stderr)
            time.sleep(2)
            continue
        random.shuffle(candidates)
        for m in candidates:
            if m.get("url") and m["url"] not in seen:
                return m
    return None


def send_to_telegram(meme):
    if not BOT_TOKEN or not CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars must be set.", file=sys.stderr)
        sys.exit(1)

    image_url = meme["url"]

    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": CHAT_ID,
        "photo": image_url,
    }
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(api_url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if not result.get("ok"):
                print(f"Telegram API error: {result}", file=sys.stderr)
                sys.exit(1)
            print(f"Posted: {image_url}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"HTTP error posting to Telegram: {e.code} {body}", file=sys.stderr)
        sys.exit(1)


def main():
    history = load_history()
    meme = pick_new_meme(history)
    if not meme:
        print("Could not find a new meme this run (maybe API hiccup). Exiting quietly.")
        return
    send_to_telegram(meme)
    history.append(meme["url"])
    save_history(history)


if __name__ == "__main__":
    main()
