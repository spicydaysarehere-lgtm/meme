#!/usr/bin/env python3

import json
import os
import random
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests


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
]

MEME_API_URL = "https://meme-api.com/gimme/{subreddit}/{count}"

TELEGRAM_API = "https://api.telegram.org/bot{token}"

POSTED_FILE = Path("posted.json")

TELEGRAM_IMAGE_LIMIT = 9 * 1024 * 1024
TELEGRAM_ANIMATION_LIMIT = 49 * 1024 * 1024

MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024

REQUEST_TIMEOUT = 30

POSTS_PER_SUBREDDIT = 50

API_RETRIES = 3
DOWNLOAD_RETRIES = 3

GIF_FPS = 12
GIF_WIDTH = 480


# ============================================================
# ENVIRONMENT
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


if not TELEGRAM_BOT_TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN missing")
    sys.exit(1)


if not TELEGRAM_CHAT_ID:
    print("ERROR: TELEGRAM_CHAT_ID missing")
    sys.exit(1)


# ============================================================
# HTTP
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent":
        "RedditTelegramMediaBot/1.0"
    }
)


# ============================================================
# STATE
# ============================================================

def load_state():

    if not POSTED_FILE.exists():

        return {
            "sequence_index": 0,
            "posted": []
        }

    try:

        with POSTED_FILE.open(
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        return {
            "sequence_index":
                int(data.get("sequence_index",0)),
            "posted":
                data.get("posted",[])
        }

    except Exception:

        return {
            "sequence_index":0,
            "posted":[]
        }



def save_state(state):

    tmp = POSTED_FILE.with_suffix(".tmp")

    with tmp.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            indent=2
        )

    tmp.replace(
        POSTED_FILE
    )



def required_media_type(index):

    return (
        "gif"
        if index % 3 == 2
        else "photo"
    )


# ============================================================
# HELPERS
# ============================================================

def filename_from_url(url):

    try:

        name = Path(
            urlparse(url).path
        ).name

        if name:
            return name

    except Exception:
        pass

    return "media"



def is_gif_bytes(data):

    return (
        data.startswith(b"GIF87a")
        or
        data.startswith(b"GIF89a")
    )



def is_image_bytes(data):

    return (
        data.startswith(b"\xff\xd8\xff")
        or
        data.startswith(b"\x89PNG")
        or
        (
            len(data)>=12
            and data[:4]==b"RIFF"
            and data[8:12]==b"WEBP"
        )
    )



def safe_name(x):

    return (
        str(x)
        .replace("/","")
        .replace("\\","")
        .strip()
    )


# ============================================================
# FETCH REDDIT
# ============================================================

def get_posts(subreddit):

    subreddit = safe_name(
        subreddit
    )

    url = MEME_API_URL.format(
        subreddit=subreddit,
        count=POSTS_PER_SUBREDDIT
    )


    for attempt in range(
        1,
        API_RETRIES+1
    ):

        try:

            print(
                "Fetching:",
                subreddit
            )

            r = session.get(
                url,
                timeout=REQUEST_TIMEOUT
            )


            if r.status_code != 200:

                time.sleep(2)
                continue


            data = r.json()

            posts = data.get(
                "memes",
                []
            )


            random.shuffle(
                posts
            )


            return posts


        except Exception as e:

            print(
                e
            )


    return []


# ============================================================
# DOWNLOAD
# ============================================================

def download(url,path):

    for attempt in range(
        1,
        DOWNLOAD_RETRIES+1
    ):

        try:

            r = session.get(
                url,
                stream=True,
                timeout=REQUEST_TIMEOUT
            )


            if r.status_code != 200:
                continue


            size = 0


            with open(
                path,
                "wb"
            ) as f:


                for chunk in r.iter_content(
                    1024*1024
                ):

                    if not chunk:
                        continue


                    size += len(chunk)


                    if size > MAX_DOWNLOAD_SIZE:

                        return False


                    f.write(
                        chunk
                    )


            return True


        except Exception:

            time.sleep(2)


    return False


# ============================================================
# MEDIA DETECTION
# ============================================================

def detect_media_type(path):

    try:

        with open(
            path,
            "rb"
        ) as f:

            header = f.read(32)


        if is_gif_bytes(header):

            return "gif"


        if is_image_bytes(header):

            return "image"


    except Exception:

        pass


    suffix = path.suffix.lower()


    if suffix == ".gif":

        return "gif"


    if suffix in (
        ".jpg",
        ".jpeg",
        ".png",
        ".webp"
    ):

        return "image"


    if suffix in (
        ".mp4",
        ".webm",
        ".mov",
        ".m4v"
    ):

        return "video"


    return "unknown"



# ============================================================
# FFMPEG CHECK
# ============================================================

def check_ffmpeg():

    try:

        r = subprocess.run(
            [
                "ffmpeg",
                "-version"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )


        return r.returncode == 0


    except Exception:

        return False



# ============================================================
# VIDEO TO GIF
# ============================================================

def convert_video_to_gif(
    video,
    output
):

    command = [

        "ffmpeg",
        "-y",

        "-i",
        str(video),

        "-vf",

        (
            f"fps={GIF_FPS},"
            f"scale={GIF_WIDTH}:-1,"
            "split[s0][s1];"
            "[s0]palettegen[p];"
            "[s1][p]paletteuse"
        ),

        "-loop",
        "0",

        str(output)

    ]


    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )


    if result.returncode != 0:

        print(
            result.stderr.decode(
                errors="ignore"
            )
        )

        return False



    if not output.exists():

        return False



    return detect_media_type(
        output
    ) == "gif"



# ============================================================
# GIF SIZE CONTROL
# ============================================================

def compress_gif(
    gif
):

    if gif.stat().st_size <= TELEGRAM_ANIMATION_LIMIT:

        return gif



    output = gif.with_name(
        "compressed.gif"
    )


    command = [

        "ffmpeg",
        "-y",

        "-i",
        str(gif),

        "-vf",

        (
            "fps=8,"
            "scale=360:-1,"
            "split[s0][s1];"
            "[s0]palettegen[p];"
            "[s1][p]paletteuse"
        ),

        "-loop",
        "0",

        str(output)

    ]


    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )


    if result.returncode != 0:

        return None



    if not output.exists():

        return None



    if output.stat().st_size > TELEGRAM_ANIMATION_LIMIT:

        return None



    return output



# ============================================================
# IMAGE COMPRESSION
# ============================================================

def compress_image(
    image
):

    if image.stat().st_size <= TELEGRAM_IMAGE_LIMIT:

        return image



    output = image.with_name(
        "telegram.jpg"
    )


    command = [

        "ffmpeg",
        "-y",

        "-i",
        str(image),

        "-vf",
        "scale=1280:-2",

        "-q:v",
        "7",

        str(output)

    ]


    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )


    if result.returncode != 0:

        return None



    return output



# ============================================================
# FIND MEDIA
# ============================================================

def find_media(
    required,
    posted
):

    subs = list(
        SUBREDDITS
    )

    random.shuffle(
        subs
    )


    posted = set(
        posted
    )


    for subreddit in subs:


        print(
            "Checking r/" + subreddit
        )


        posts = get_posts(
            subreddit
        )


        for post in posts:


            post_id = str(
                post.get(
                    "postLink"
                    or
                    post.get("url")
                )
            )


            if post_id in posted:

                continue



            url = str(
                post.get(
                    "url",
                    ""
                )
            )


            if not url:

                continue



            title = str(
                post.get(
                    "title",
                    ""
                )
            )



            with tempfile.TemporaryDirectory() as tmp:


                tmp = Path(
                    tmp
                )


                source = tmp / filename_from_url(
                    url
                )


                if not download(
                    url,
                    source
                ):

                    continue



                media_type = detect_media_type(
                    source
                )



                # ----------------------------
                # PHOTO SLOT
                # ----------------------------

                if required == "photo":


                    if media_type != "image":

                        continue



                    return {

                        "type":"photo",

                        "path":source,

                        "subreddit":subreddit,

                        "id":post_id,

                        "title":title

                    }



                # ----------------------------
                # GIF SLOT
                # ----------------------------

                if required == "gif":


                    if media_type == "gif":


                        return {

                            "type":"gif",

                            "path":source,

                            "subreddit":subreddit,

                            "id":post_id,

                            "title":title

                        }



                    if media_type == "video":


                        gif = tmp / "animation.gif"


                        if convert_video_to_gif(
                            source,
                            gif
                        ):


                            return {

                                "type":"gif",

                                "path":gif,

                                "subreddit":subreddit,

                                "id":post_id,

                                "title":title

                            }


    return None


# ============================================================
# TELEGRAM UPLOAD
# ============================================================

def telegram_upload(
    method,
    field,
    file_path,
    filename,
    mime,
    caption
):

    boundary = (
        "----Bot"
        + uuid.uuid4().hex
    )

    body = bytearray()


    def add_text(
        name,
        value
    ):

        body.extend(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n'
                f"\r\n"
                f"{value}\r\n"
            ).encode()
        )



    def add_file(
        name,
        path
    ):

        body.extend(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; '
                f'name="{name}"; '
                f'filename="{filename}"\r\n'
                f"Content-Type: {mime}\r\n"
                f"\r\n"
            ).encode()
        )


        with open(
            path,
            "rb"
        ) as f:

            body.extend(
                f.read()
            )


        body.extend(
            b"\r\n"
        )



    add_text(
        "chat_id",
        TELEGRAM_CHAT_ID
    )


    if caption:

        add_text(
            "caption",
            caption
        )


    add_file(
        field,
        file_path
    )


    body.extend(
        f"--{boundary}--\r\n".encode()
    )


    url = (
        TELEGRAM_API.format(
            token=TELEGRAM_BOT_TOKEN
        )
        +
        "/"
        +
        method
    )


    try:

        r = session.post(
            url,
            data=bytes(body),
            headers={
                "Content-Type":
                f"multipart/form-data; boundary={boundary}"
            },
            timeout=180
        )


        data = r.json()


        if not data.get("ok"):

            print(
                data
            )

            return False


        return True



    except Exception as e:

        print(
            "Telegram error:",
            e
        )

        return False



# ============================================================
# SEND PHOTO
# ============================================================

def send_photo(
    path,
    subreddit
):

    path = compress_image(
        path
    )


    if not path:

        return False



    return telegram_upload(
        "sendPhoto",
        "photo",
        path,
        "image.jpg",
        "image/jpeg",
        f"r/{subreddit}"
    )



# ============================================================
# SEND GIF
# ============================================================

def send_gif(
    path,
    subreddit
):

    if detect_media_type(path) != "gif":

        print(
            "Not a real GIF"
        )

        return False



    path = compress_gif(
        path
    )


    if not path:

        return False



    return telegram_upload(
        "sendAnimation",
        "animation",
        path,
        "animation.gif",
        "image/gif",
        f"r/{subreddit}"
    )



# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "Reddit Telegram Media Bot"
    )


    if not check_ffmpeg():

        print(
            "FFmpeg missing"
        )

        return 1



    state = load_state()


    index = state.get(
        "sequence_index",
        0
    )


    required = required_media_type(
        index
    )


    print(
        "Required:",
        required
    )


    media = find_media(
        required,
        state.get(
            "posted",
            []
        )
    )


    if not media:

        print(
            "No media found"
        )

        return 1



    success = False



    if media["type"] == "photo":

        success = send_photo(
            media["path"],
            media["subreddit"]
        )



    elif media["type"] == "gif":

        success = send_gif(
            media["path"],
            media["subreddit"]
        )



    if not success:

        print(
            "Upload failed"
        )

        return 1



    state["posted"].append(
        media["id"]
    )


    if len(state["posted"]) > 1000:

        state["posted"] = (
            state["posted"][-1000:]
        )



    state["sequence_index"] = (
        index + 1
    )


    save_state(
        state
    )


    print(
        "POST SUCCESS"
    )


    return 0



if __name__ == "__main__":

    try:

        sys.exit(
            main()
        )

    except KeyboardInterrupt:

        sys.exit(130)

    except Exception as e:

        print(
            "Fatal:",
            e
        )

        sys.exit(1)
