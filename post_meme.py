#!/usr/bin/env python3

import os
import sys
import json
import random
import time
import uuid
import shutil
import tempfile
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests


# ================= CONFIG =================

SUBREDDITS = [
    "memes",
    "wholesomememes",
    "anime",
    "animememes",
    "funny",
]

MEME_API_URL = "https://meme-api.com/gimme/{}/{}"

TELEGRAM_API = "https://api.telegram.org/bot{}"

POSTED_FILE = Path("posted.json")

PHOTO_LIMIT = 9 * 1024 * 1024
GIF_LIMIT = 49 * 1024 * 1024

MAX_DOWNLOAD = 100 * 1024 * 1024

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)

session = requests.Session()

session.headers.update({
    "User-Agent": "RedditTelegramBot/1.0"
})


# ================= STATE =================

def load_state():
    if not POSTED_FILE.exists():
        return {
            "sequence": 0,
            "posted": []
        }

    try:
        with open(
            POSTED_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)

    except:
        return {
            "sequence": 0,
            "posted": []
        }


def save_state(data):
    with open(
        POSTED_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            indent=2
        )


def needed_type(index):
    return "gif" if index % 3 == 2 else "photo"


# ================= HELPERS =================

def filename(url):
    try:
        name = Path(
            urlparse(url).path
        ).name

        if name:
            return name

    except:
        pass

    return "media"


def media_type(path):

    with open(path,"rb") as f:
        head=f.read(32)

    if head.startswith(b"GIF"):
        return "gif"

    if (
        head.startswith(b"\xff\xd8")
        or head.startswith(b"\x89PNG")
        or (
            head[0:4]==b"RIFF"
            and head[8:12]==b"WEBP"
        )
    ):
        return "image"


    ext=path.suffix.lower()

    if ext in [
        ".mp4",
        ".webm",
        ".mov"
    ]:
        return "video"

    return "unknown"


# ================= REDDIT =================

def get_posts(sub):

    try:
        r=session.get(
            MEME_API_URL.format(
                sub,
                50
            ),
            timeout=30
        )

        if r.status_code != 200:
            return []

        data=r.json()

        posts=data.get(
            "memes",
            []
        )

        random.shuffle(posts)

        return posts

    except Exception as e:
        print(e)
        return []


# ================= DOWNLOAD =================

def download(url,path):

    try:
        r=session.get(
            url,
            stream=True,
            timeout=30
        )

        if r.status_code != 200:
            return False


        size=0

        with open(
            path,
            "wb"
        ) as f:

            for chunk in r.iter_content(
                1024*1024
            ):

                size+=len(chunk)

                if size > MAX_DOWNLOAD:
                    return False

                f.write(chunk)

        return True


    except Exception as e:
        print(e)
        return False


# ================= FFMPEG =================

def convert_to_gif(video, output):

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-vf",
        (
            "fps=12,"
            "scale=480:-1,"
            "split[s0][s1];"
            "[s0]palettegen[p];"
            "[s1][p]paletteuse"
        ),
        "-loop",
        "0",
        str(output)
    ]

    r = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    return (
        r.returncode == 0
        and output.exists()
        and media_type(output) == "gif"
    )


# ================= FIND MEDIA =================

def find_media(required, posted):

    posted=set(posted)

    for sub in SUBREDDITS:

        print(
            "Checking r/" + sub
        )

        for post in get_posts(sub):

            post_id=str(
                post.get("postLink")
                or post.get("url")
                or ""
            )

            if not post_id:
                continue

            if post_id in posted:
                continue


            url=str(
                post.get(
                    "url",
                    ""
                )
            )

            if not url:
                continue


            title=post.get(
                "title",
                ""
            )


            work=tempfile.mkdtemp()

            path=Path(work)/filename(url)


            if not download(
                url,
                path
            ):
                shutil.rmtree(
                    work,
                    ignore_errors=True
                )
                continue


            kind=media_type(path)


            # PHOTO

            if required=="photo":

                if kind=="image":

                    return {
                        "type":"photo",
                        "path":path,
                        "folder":work,
                        "sub":sub,
                        "id":post_id,
                        "title":title
                    }


            # GIF

            if required=="gif":

                if kind=="gif":

                    return {
                        "type":"gif",
                        "path":path,
                        "folder":work,
                        "sub":sub,
                        "id":post_id,
                        "title":title
                    }


                if kind=="video":

                    gif=Path(work)/"animation.gif"

                    if convert_to_gif(
                        path,
                        gif
                    ):

                        return {
                            "type":"gif",
                            "path":gif,
                            "folder":work,
                            "sub":sub,
                            "id":post_id,
                            "title":title
                        }


            shutil.rmtree(
                work,
                ignore_errors=True
            )


    return None



# ================= TELEGRAM =================

def upload(
    method,
    field,
    file,
    name,
    mime,
    caption
):

    url=(
        TELEGRAM_API.format(
            TELEGRAM_BOT_TOKEN
        )
        +
        "/"
        +
        method
    )


    try:

        with open(
            file,
            "rb"
        ) as f:

            files={
                field:(
                    name,
                    f,
                    mime
                )
            }

            data={
                "chat_id":
                    TELEGRAM_CHAT_ID,
                "caption":
                    caption
            }


            r=session.post(
                url,
                data=data,
                files=files,
                timeout=180
            )


        result=r.json()

        print(result)

        return result.get(
            "ok",
            False
        )


    except Exception as e:

        print(
            "Telegram error:",
            e
        )

        return False



def send_photo(path,sub):

    return upload(
        "sendPhoto",
        "photo",
        path,
        "image.jpg",
        "image/jpeg",
        "r/"+sub
    )



def send_gif(path,sub):

    return upload(
        "sendAnimation",
        "animation",
        path,
        "animation.gif",
        "image/gif",
        "r/"+sub
    )


