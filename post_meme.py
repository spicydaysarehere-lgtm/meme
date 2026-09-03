#!/usr/bin/env python3

import os
import sys
import json
import random
import tempfile
import subprocess
from pathlib import Path

import requests


# ============================================================
# CONFIG
# ============================================================

SUBREDDITS = [
    "nsfwanimegifs",
    "ecchi",
    "OverOppai",
    "CFNM_Hentai",
    "EcchiCurves",
    "animeplot",
]

API_URL = "https://meme-api.com/gimme/{}/50"

STATE_FILE = Path("posted.json")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

if not TOKEN or not CHAT_ID:
    print("Missing Telegram secrets")
    sys.exit(1)


session = requests.Session()
session.headers.update({
    "User-Agent": "RedditTelegramBot/1.0"
})


# ============================================================
# STATE
# ============================================================

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(
                STATE_FILE.read_text(
                    encoding="utf-8"
                )
            )
        except:
            pass

    return {
        "index": 0,
        "posted": []
    }


def save_state(data):
    STATE_FILE.write_text(
        json.dumps(
            data,
            indent=2
        ),
        encoding="utf-8"
    )


def required_type(index):
    if index % 3 == 2:
        return "gif"

    return "image"


# ============================================================
# MEDIA
# ============================================================

def detect(path):

    try:
        data = path.read_bytes()[:32]

        if data.startswith(b"GIF"):
            return "gif"

        if (
            data.startswith(b"\xff\xd8")
            or data.startswith(b"\x89PNG")
            or (
                len(data) >= 12
                and data[:4] == b"RIFF"
                and data[8:12] == b"WEBP"
            )
        ):
            return "image"

    except:
        pass


    ext = path.suffix.lower()

    if ext == ".gif":
        return "gif"

    if ext in (
        ".jpg",
        ".jpeg",
        ".png",
        ".webp"
    ):
        return "image"

    if ext in (
        ".mp4",
        ".webm",
        ".mov",
        ".m4v"
    ):
        return "video"

    return "unknown"


def download(url, path):

    try:

        r = session.get(
            url,
            timeout=40
        )

        if r.status_code != 200:
            return False

        path.write_bytes(
            r.content
        )

        return True

    except Exception as e:

        print(e)
        return False


# ============================================================
# VIDEO TO GIF
# ============================================================

def convert_to_gif(video, output):

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-vf",
        "fps=10,scale=480:-1:flags=lanczos",
        "-loop",
        "0",
        str(output)
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return (
        result.returncode == 0
        and output.exists()
        and detect(output) == "gif"
    )


# ============================================================
# FIND MEDIA
# ============================================================

def find_media(wanted, posted):

    subs = SUBREDDITS[:]
    random.shuffle(subs)

    for sub in subs:

        print(
            "Checking:",
            sub
        )

        try:

            data = session.get(
                API_URL.format(sub),
                timeout=40
            ).json()

            posts = data.get(
                "memes",
                []
            )

        except:

            continue


        random.shuffle(posts)


        for post in posts:

            post_id = (
                post.get("postLink")
                or post.get("url")
            )

            if not post_id:
                continue

            if post_id in posted:
                continue


            url = post.get(
                "url",
                ""
            )

            if not url:
                continue


            with tempfile.TemporaryDirectory() as folder:

                folder = Path(folder)

                source = folder / "media"

                if not download(
                    url,
                    source
                ):
                    continue


                kind = detect(
                    source
                )


                if wanted == "image":

                    if kind != "image":
                        continue

                    return {
                        "type": "image",
                        "data": source.read_bytes(),
                        "subreddit": sub,
                        "id": post_id
                    }


                if wanted == "gif":

                    if kind == "gif":

                        return {
                            "type": "gif",
                            "data": source.read_bytes(),
                            "subreddit": sub,
                            "id": post_id
                        }


                    if kind == "video":

                        gif = folder / "animation.gif"

                        if convert_to_gif(
                            source,
                            gif
                        ):

                            return {
                                "type": "gif",
                                "data": gif.read_bytes(),
                                "subreddit": sub,
                                "id": post_id
                            }

    return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(item):

    if item["type"] == "image":

        url = (
            f"https://api.telegram.org/"
            f"bot{TOKEN}/sendPhoto"
        )

        files = {
            "photo": (
                "image.jpg",
                item["data"],
                "image/jpeg"
            )
        }


    else:

        url = (
            f"https://api.telegram.org/"
            f"bot{TOKEN}/sendAnimation"
        )

        files = {
            "animation": (
                "animation.gif",
                item["data"],
                "image/gif"
            )
        }


    r = session.post(
        url,
        data={
            "chat_id": CHAT,
            "caption":
                f"r/{item['subreddit']}"
        },
        files=files,
        timeout=180
    )


    try:
        return r.json().get(
            "ok",
            False
        )

    except:

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    state = load_state()

    wanted = required_type(
        state["index"]
    )


    print(
        "Need:",
        wanted
    )


    item = find_media(
        wanted,
        set(
            state["posted"]
        )
    )


    if not item:

        print(
            "No media found"
        )

        return 1


    if not send_telegram(
        item
    ):

        print(
            "Telegram failed"
        )

        return 1


    state["posted"].append(
        item["id"]
    )


    if len(
        state["posted"]
    ) > 1000:

        state["posted"] = (
            state["posted"][-1000:]
        )


    state["index"] += 1


    save_state(
        state
    )


    print(
        "POST SUCCESS"
    )

    return 0



if __name__ == "__main__":

    sys.exit(
        main()
    )
