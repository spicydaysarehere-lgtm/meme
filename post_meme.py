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



session = requests.Session()

session.headers.update(
    {
        "User-Agent":
        "RedditMediaBot/2.0"
    }
)



# -------------------------
# STATE
# -------------------------

def load_state():

    if not STATE_FILE.exists():

        return {
            "index": 0,
            "hashes": []
        }


    try:

        return json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )


    except:

        return {
            "index": 0,
            "hashes": []
        }



def save_state(state):

    STATE_FILE.write_text(
        json.dumps(
            state,
            indent=2
        ),
        encoding="utf-8"
    )



# -------------------------
# ROTATION
# -------------------------

def required_type(index):

    pattern = [
        "image",
        "image",
        "gif"
    ]

    return pattern[
        index % 3
    ]



# -------------------------
# FILE CHECK
# -------------------------

def file_hash(path):

    h = hashlib.sha256()

    with open(
        path,
        "rb"
    ) as f:

        while True:

            chunk = f.read(8192)

            if not chunk:
                break

            h.update(chunk)


    return h.hexdigest()



def detect(path):

    data = path.read_bytes()[:32]


    if data.startswith(
        b"GIF"
    ):
        return "gif"


    if (
        data.startswith(b"\xff\xd8")
        or data.startswith(b"\x89PNG")
    ):
        return "image"


    ext = path.suffix.lower()


    if ext in (
        ".jpg",
        ".jpeg",
        ".png",
        ".webp"
    ):
        return "image"


    if ext in (
        ".gif",
    ):
        return "gif"


    if ext in (
        ".mp4",
        ".webm",
        ".mov"
    ):
        return "video"


    return "unknown"




# -------------------------
# DOWNLOAD
# -------------------------

def download(url,path):

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


    except:

        return False




# -------------------------
# VIDEO -> GIF
# -------------------------

def convert_gif(video):

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


    if result.returncode == 0:

        return output


    return None




# -------------------------
# FIND MEDIA
# -------------------------

def find_media(
    wanted,
    used
):

    subs = SUBREDDITS[:]

    random.shuffle(
        subs
    )


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



        random.shuffle(
            posts
        )


        for post in posts:


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



            media_hash = file_hash(
                path
            )


            if media_hash in used:

                path.unlink(
                    missing_ok=True
                )

                continue



            kind = detect(
                path
            )



            if wanted == "image":

                if kind == "image":

                    return {
                        "type":"image",
                        "path":path,
                        "hash":media_hash
                    }



            if wanted == "gif":


                if kind == "gif":

                    return {
                        "type":"gif",
                        "path":path,
                        "hash":media_hash
                    }



                if kind == "video":


                    gif = convert_gif(
                        path
                    )


                    path.unlink(
                        missing_ok=True
                    )


                    if gif:

                        return {
                            "type":"gif",
                            "path":gif,
                            "hash":media_hash
                        }



            path.unlink(
                missing_ok=True
            )


    return None




# -------------------------
# TELEGRAM
# -------------------------

def send_telegram(item):


    if item["type"] == "image":

        endpoint = (
            f"https://api.telegram.org/"
            f"bot{TOKEN}/sendPhoto"
        )


        files = {

            "photo":
            (
                "image.jpg",
                open(
                    item["path"],
                    "rb"
                )
            )

        }



    else:

        endpoint = (
            f"https://api.telegram.org/"
            f"bot{TOKEN}/sendAnimation"
        )


        files = {

            "animation":
            (
                "animation.gif",
                open(
                    item["path"],
                    "rb"
                )
            )

        }




    try:

        r = session.post(
            endpoint,
            data={
                "chat_id":CHAT_ID
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




# -------------------------
# MAIN
# -------------------------

def main():

    state = load_state()


    wanted = required_type(
        state["index"]
    )


    media = find_media(
        wanted,
        set(
            state.get(
                "hashes",
                []
            )
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



    state["hashes"].append(
        media["hash"]
    )


    if len(
        state["hashes"]
    ) > 5000:

        state["hashes"] = (
            state["hashes"][-5000:]
        )


    state["index"] += 1


    save_state(
        state
    )


    print(
        "POST SUCCESS:",
        wanted
    )


    return 0



if __name__ == "__main__":

    sys.exit(
        main()
    )
