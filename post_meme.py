#!/usr/bin/env python3

import os
import sys
import json
import random
import tempfile
import subprocess
from pathlib import Path

import requests


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

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

if not TOKEN or not CHAT_ID:
    print("Missing Telegram secrets")
    sys.exit(1)


session = requests.Session()
session.headers.update(
    {
        "User-Agent": "RedditTelegramMediaBot/1.0"
    }
)


def load_state():

    if not STATE_FILE.exists():
        return {
            "index": 0,
            "posted": []
        }

    try:

        data = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

        return {
            "index": int(
                data.get(
                    "index",
                    data.get(
                        "sequence_index",
                        0
                    )
                )
            ),
            "posted": data.get(
                "posted",
                []
            )
        }

    except Exception:

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



def needed_type(index):

    return "gif" if index % 3 == 2 else "image"



def detect(path):

    try:

        header = path.read_bytes()[:32]

        if header.startswith(b"GIF"):
            return "gif"

        if (
            header.startswith(b"\xff\xd8")
            or header.startswith(b"\x89PNG")
            or (
                len(header) >= 12
                and header[:4] == b"RIFF"
                and header[8:12] == b"WEBP"
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

    except:

        return False



def make_gif(video, output):

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



def find_media(required, posted):

    subs = SUBREDDITS[:]

    random.shuffle(subs)

    for sub in subs:

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


            temp = tempfile.NamedTemporaryFile(
                delete=False
            )

            temp.close()


            path = Path(
                temp.name
            )


            if not download(
                url,
                path
            ):

                path.unlink(
                    missing_ok=True
                )

                continue


            kind = detect(path)


            if required == "image":

                if kind == "image":

                    return {
                        "type": "image",
                        "path": path,
                        "subreddit": sub,
                        "id": post_id
                    }



            if required == "gif":

                if kind == "gif":

                    return {
                        "type": "gif",
                        "path": path,
                        "subreddit": sub,
                        "id": post_id
                    }


                if kind == "video":

                    gif = path.with_suffix(
                        ".gif"
                    )


                    if make_gif(
                        path,
                        gif
                    ):

                        path.unlink(
                            missing_ok=True
                        )


                        return {
                            "type": "gif",
                            "path": gif,
                            "subreddit": sub,
                            "id": post_id
                        }


            path.unlink(
                missing_ok=True
            )


    return None



def send_telegram(item):

    if item["type"] == "image":

        url = (
            f"https://api.telegram.org/"
            f"bot{TOKEN}/sendPhoto"
        )

        files = {
            "photo": (
                "image.jpg",
                open(
                    item["path"],
                    "rb"
                ),
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
                open(
                    item["path"],
                    "rb"
                ),
                "image/gif"
            )
        }


    try:

        r = session.post(
            url,
            data={
                "chat_id": CHAT_ID
            },
            files=files,
            timeout=180
        )


        return r.json().get(
            "ok",
            False
        )


    except:

        return False


    finally:

        for f in files.values():

            f[1].close()



def main():

    state = load_state()


    required = needed_type(
        state["index"]
    )


    media = find_media(
        required,
        set(
            state["posted"]
        )
    )


    if not media:

        print(
            "No media found"
        )

        return 1



    if not send_telegram(
        media
    ):

        print(
            "Telegram failed"
        )

        return 1



    state["posted"].append(
        media["id"]
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
