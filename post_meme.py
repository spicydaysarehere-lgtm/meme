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
# CONFIGURATION
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

    "User-Agent":
    "RedditTelegramMediaBot/7.0"

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

            "index":
                int(data.get("index", 0)),

            "hashes":
                data.get("hashes", [])

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
# MEDIA ORDER
# ============================================================

def needed_type(index):

    order = [

        "image",

        "image",

        "gif"

    ]


    return order[
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


            chunk = f.read(
                1024 * 1024
            )


            if not chunk:

                break


            h.update(chunk)


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
