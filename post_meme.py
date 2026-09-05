#!/usr/bin/env python3

import os
import sys
import json
import random
import hashlib
import tempfile
import subprocess
from pathlib import Path

import requests
from PIL import Image


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
    "UnderOppai",
    "SideOppai",
    "DarkSkinnedAnimeBabes",
    "AnimeLingerie",
    "SFWWaifu"
]


API_URL = "https://meme-api.com/gimme/{}/50"

STATE_FILE = Path("posted.json")


TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()


CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


if not TOKEN or not CHAT_ID:
    print("Missing Telegram secrets")
    sys.exit(1)



# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "RedditTelegramMediaBot/6.0"
})



# ============================================================
# STATE
# ============================================================

def load_state():

    default = {
        "index": 0,
        "hashes": []
    }


    if not STATE_FILE.exists():

        return default


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
                    0
                )
            ),

            "hashes": data.get(
                "hashes",
                []
            )

        }


    except Exception:

        return default



def save_state(state):

    STATE_FILE.write_text(

        json.dumps(
            state,
            indent=2
        ),

        encoding="utf-8"

    )



# ============================================================
# POST ORDER
# ============================================================

def needed_type(index):

    sequence = [
        "image",
        "image",
        "gif"
    ]


    return sequence[
        index % 3
    ]



# ============================================================
# HASH
# ============================================================

def file_hash(path):

    h = hashlib.sha256()


    with open(
        path,
        "rb"
    ) as f:


        while True:


            data = f.read(
                1024 * 1024
            )


            if not data:

                break


            h.update(
                data
            )


    return h.hexdigest()



# ============================================================
# DETECT TYPE
# ============================================================

def detect(path):

    try:

        header = path.read_bytes()[:32]


        if header.startswith(
            b"GIF"
        ):

            return "gif"


        if header.startswith(
            b"\xff\xd8"
        ):

            return "image"


        if header.startswith(
            b"\x89PNG"
        ):

            return "image"


    except Exception:

        pass



    ext = path.suffix.lower()


    if ext in [
        ".jpg",
        ".jpeg",
        ".png",
        ".webp"
    ]:

        return "image"



    if ext == ".gif":

        return "gif"



    if ext in [
        ".mp4",
        ".webm",
        ".mov",
        ".m4v"
    ]:

        return "video"



    return "unknown"



# ============================================================
# DOWNLOAD
# ============================================================

def download(url, path):

    try:

        r = session.get(
            url,
            timeout=60
        )


        if r.status_code != 200:

            return False



        path.write_bytes(
            r.content
        )


        return True



    except Exception:

        return False



# ============================================================
# VIDEO TO GIF
# ============================================================

def make_gif(video):

    output = video.with_suffix(
        ".gif"
    )


    cmd = [

        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-vf",
        "fps=10,scale=480:-1",
        "-loop",
        "0",
        str(output)

    ]


    result = subprocess.run(

        cmd,

        stdout=subprocess.DEVNULL,

        stderr=subprocess.DEVNULL

    )


    if (

        result.returncode == 0

        and output.exists()

    ):

        return output



    return None



# ============================================================
# IMAGE COMPRESSION
# ============================================================

def compress_image(path):

    try:

        img = Image.open(
            path
        )


        if img.mode in (
            "RGBA",
            "P"
        ):

            img = img.convert(
                "RGB"
            )



        img.thumbnail(
            (
                2000,
                2000
            )
        )


        output = path.with_name(
            path.stem + "_compressed.jpg"
        )


        quality = 85



        while True:


            img.save(

                output,

                "JPEG",

                quality=quality,

                optimize=True

            )


            if output.stat().st_size < 9000000:

                break



            quality -= 10



            if quality <= 30:

                break



        return output



    except Exception as e:

        print(
            "Compression error:",
            e
        )

        return path
