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

MAX_HISTORY = 5000

TELEGRAM_MAX_PHOTO_SIZE = 10 * 1024 * 1024

SAFE_IMAGE_SIZE = 9 * 1024 * 1024


# ============================================================
# TELEGRAM SECRETS
# ============================================================

TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


if not TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN is missing")
    sys.exit(1)


if not CHAT_ID:
    print("ERROR: TELEGRAM_CHAT_ID is missing")
    sys.exit(1)


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "RedditTelegramMediaBot/1.0"
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

        print("No posted.json found. Starting fresh.")

        return default

    try:

        data = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

        hashes = data.get(
            "hashes",
            []
        )

        # Support old state files
        if not hashes:

            hashes = data.get(
                "posted",
                []
            )

        return {
            "index": int(
                data.get(
                    "index",
                    0
                )
            ),
            "hashes": hashes
        }

    except Exception as e:

        print(
            f"WARNING: Could not read posted.json: {e}"
        )

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
# POST ROTATION
#
# 1 = IMAGE
# 2 = IMAGE
# 3 = GIF
#
# Then repeats.
# ============================================================

def get_required_type(index):

    sequence = [
        "image",
        "image",
        "gif"
    ]

    return sequence[
        index % len(sequence)
    ]


# ============================================================
# HASH FILE
# ============================================================

def get_file_hash(path):

    sha = hashlib.sha256()

    with open(
        path,
        "rb"
    ) as file:

        while True:

            chunk = file.read(
                1024 * 1024
            )

            if not chunk:
                break

            sha.update(
                chunk
            )

    return sha.hexdigest()


# ============================================================
# DETECT MEDIA TYPE
# ============================================================

def detect_media_type(path):

    try:

        header = path.read_bytes()[:32]

        # GIF
        if header.startswith(b"GIF"):

            return "gif"

        # JPEG
        if header.startswith(b"\xff\xd8"):

            return "image"

        # PNG
        if header.startswith(b"\x89PNG"):

            return "image"

        # WEBP
        if (
            len(header) >= 12
            and header[:4] == b"RIFF"
            and header[8:12] == b"WEBP"
        ):

            return "image"

    except Exception:

        pass


    extension = path.suffix.lower()


    if extension in [
        ".jpg",
        ".jpeg",
        ".png",
        ".webp"
    ]:

        return "image"


    if extension == ".gif":

        return "gif"


    if extension in [
        ".mp4",
        ".webm",
        ".mov",
        ".m4v"
    ]:

        return "video"


    return "unknown"


# ============================================================
# DOWNLOAD MEDIA
# ============================================================

def download_media(url, path):

    try:

        response = session.get(
            url,
            timeout=60
        )

        if response.status_code != 200:

            print(
                f"      Download failed: HTTP {response.status_code}"
            )

            return False

        if not response.content:

            print(
                "      Download returned empty file"
            )

            return False

        path.write_bytes(
            response.content
        )

        return True

    except Exception as e:

        print(
            f"      Download error: {e}"
        )

        return False


# ============================================================
# CONVERT VIDEO TO GIF
# ============================================================

def convert_video_to_gif(video_path):

    output_path = video_path.with_name(
        video_path.stem + "_converted.gif"
    )

    command = [

        "ffmpeg",

        "-y",

        "-i",
        str(video_path),

        "-vf",
        "fps=10,scale=480:-1:flags=lanczos",

        "-loop",
        "0",

        str(output_path)

    ]

    try:

        result = subprocess.run(

            command,

            stdout=subprocess.DEVNULL,

            stderr=subprocess.DEVNULL,

            timeout=180

        )

    except Exception as e:

        print(
            f"      FFmpeg error: {e}"
        )

        return None


    if (

        result.returncode == 0

        and output_path.exists()

        and output_path.stat().st_size > 0

    ):

        return output_path


    return None


# ============================================================
# COMPRESS LARGE IMAGE
# ============================================================

def compress_image(image_path):

    print(
        "      Image is over Telegram's limit."
    )

    print(
        "      Compressing image..."
    )

    try:

        image = Image.open(
            image_path
        )


        # Convert transparency to RGB
        if image.mode in [
            "RGBA",
            "LA",
            "P"
        ]:

            background = Image.new(
                "RGB",
                image.size,
                "white"
            )

            if image.mode == "P":

                image = image.convert(
                    "RGBA"
                )

            background.paste(
                image,
                mask=image.getchannel("A")
                if image.mode == "RGBA"
                else None
            )

            image = background

        else:

            image = image.convert(
                "RGB"
            )


        # Start with a reasonable maximum dimension
        max_dimension = 2400

        image.thumbnail(
            (
                max_dimension,
                max_dimension
            ),
            Image.Resampling.LANCZOS
        )


        output_path = image_path.with_name(
            image_path.stem + "_compressed.jpg"
        )


        quality = 85


        while quality >= 25:

            image.save(

                output_path,

                format="JPEG",

                quality=quality,

                optimize=True,

                progressive=True

            )


            size = output_path.stat().st_size


            print(
                f"      JPEG quality {quality}: "
                f"{size / 1024 / 1024:.2f} MB"
            )


            if size <= SAFE_IMAGE_SIZE:

                print(
                    "      Compression successful."
                )

                return output_path


            quality -= 10


        # If quality alone wasn't enough, resize further
        print(
            "      Reducing image dimensions..."
        )


        for dimension in [
            1800,
            1500,
            1200,
            1000
        ]:

            image.thumbnail(
                (
                    dimension,
                    dimension
                ),
                Image.Resampling.LANCZOS
            )


            image.save(

                output_path,

                format="JPEG",

                quality=70,

                optimize=True

            )


            if (
                output_path.exists()
                and output_path.stat().st_size <= SAFE_IMAGE_SIZE
            ):

                print(
                    "      Compression successful."
                )

                return output_path


        if (
            output_path.exists()
            and output_path.stat().st_size < TELEGRAM_MAX_PHOTO_SIZE
        ):

            return output_path


        print(
            "      Could not compress image enough."
        )

        output_path.unlink(
            missing_ok=True
        )

        return None


    except Exception as e:

        print(
            f"      Image compression error: {e}"
        )

        return None


# ============================================================
# FIND NSFW MEDIA
# ============================================================

def find_media(required_type, posted_hashes):

    subreddits = SUBREDDITS[:]

    random.shuffle(
        subreddits
    )


    print(
        f"Looking for: {required_type}"
    )

    print(
        "NSFW filter: ONLY nsfw=true posts allowed"
    )


    for subreddit in subreddits:

        print(
            f"\nChecking r/{subreddit}"
        )


        try:

            response = session.get(

                API_URL.format(
                    subreddit
                ),

                timeout=40

            )


            if response.status_code != 200:

                print(
                    f"  API error: HTTP {response.status_code}"
                )

                continue


            data = response.json()


            posts = data.get(
                "memes",
                []
            )


        except Exception as e:

            print(
                f"  Could not retrieve subreddit: {e}"
            )

            continue


        random.shuffle(
            posts
        )


        for post in posts:

            # =================================================
            # STRICT NSFW FILTER
            # =================================================

            if post.get("nsfw") is not True:

                print(
                    "  SKIP: not explicitly marked NSFW"
                )

                continue


            print(
                "  NSFW: ACCEPTED"
            )


            # =================================================
            # MEDIA URL
            # =================================================

            url = post.get(
                "url",
                ""
            )


            if not url:

                print(
                    "  SKIP: no URL"
                )

                continue


            # =================================================
            # DOWNLOAD
            # =================================================

            temp_file = tempfile.NamedTemporaryFile(
                delete=False
            )

            temp_file.close()


            path = Path(
                temp_file.name
            )


            if not download_media(
                url,
                path
            ):

                path.unlink(
                    missing_ok=True
                )

                continue


            # =================================================
            # DETECT MEDIA
            # =================================================

            media_type = detect_media_type(
                path
            )


            print(
                f"      Media type: {media_type}"
            )


            # =================================================
            # IMAGE REQUIRED
            # =================================================

            if required_type == "image":

                if media_type != "image":

                    print(
                        "      SKIP: not an image"
                    )

                    path.unlink(
                        missing_ok=True
                    )

                    continue


                file_hash = get_file_hash(
                    path
                )


                if file_hash in posted_hashes:

                    print(
                        "      SKIP: duplicate"
                    )

                    path.unlink(
                        missing_ok=True
                    )

                    continue


                return {

                    "type": "image",

                    "path": path,

                    "hash": file_hash

                }


            # =================================================
            # GIF REQUIRED
            # =================================================

            if required_type == "gif":

                # ------------------------------------------------
                # Existing GIF
                # ------------------------------------------------

                if media_type == "gif":

                    file_hash = get_file_hash(
                        path
                    )


                    if file_hash in posted_hashes:

                        print(
                            "      SKIP: duplicate GIF"
                        )

                        path.unlink(
                            missing_ok=True
                        )

                        continue


                    return {

                        "type": "gif",

                        "path": path,

                        "hash": file_hash

                    }


                # ------------------------------------------------
                # Video -> GIF
                # ------------------------------------------------

                if media_type == "video":

                    print(
                        "      Converting video to GIF..."
                    )


                    gif_path = convert_video_to_gif(
                        path
                    )


                    path.unlink(
                        missing_ok=True
                    )


                    if not gif_path:

                        print(
                            "      SKIP: conversion failed"
                        )

                        continue


                    file_hash = get_file_hash(
                        gif_path
                    )


                    if file_hash in posted_hashes:

                        print(
                            "      SKIP: duplicate GIF"
                        )

                        gif_path.unlink(
                            missing_ok=True
                        )

                        continue


                    return {

                        "type": "gif",

                        "path": gif_path,

                        "hash": file_hash

                    }


                print(
                    "      SKIP: unsupported media"
                )


                path.unlink(
                    missing_ok=True
                )


    return None


# ============================================================
# SEND PHOTO TO TELEGRAM
# ============================================================

def send_photo(path):

    upload_path = path


    try:

        size = path.stat().st_size


        print(
            f"Image size: {size / 1024 / 1024:.2f} MB"
        )


        # Compress before hitting Telegram's limit
        if size >= SAFE_IMAGE_SIZE:

            upload_path = compress_image(
                path
            )


            if not upload_path:

                return False


        url = (
            f"https://api.telegram.org/"
            f"bot{TOKEN}/sendPhoto"
        )


        with open(
            upload_path,
            "rb"
        ) as file:

            response = session.post(

                url,

                data={
                    "chat_id": CHAT_ID
                },

                files={
                    "photo": (
                        "image.jpg",
                        file,
                        "image/jpeg"
                    )
                },

                timeout=180

            )


        try:

            result = response.json()

        except Exception:

            result = {}


        if not result.get(
            "ok",
            False
        ):

            print(
                "Telegram error:",
                result
            )

            return False


        print(
            "Telegram image sent successfully."
        )

        return True


    except Exception as e:

        print(
            f"Telegram photo error: {e}"
        )

        return False


    finally:

        if (
            upload_path != path
            and upload_path.exists()
        ):

            upload_path.unlink(
                missing_ok=True
            )


# ============================================================
# SEND GIF TO TELEGRAM
# ============================================================

def send_gif(path):

    url = (
        f"https://api.telegram.org/"
        f"bot{TOKEN}/sendAnimation"
    )


    try:

        size = path.stat().st_size


        print(
            f"GIF size: {size / 1024 / 1024:.2f} MB"
        )


        with open(
            path,
            "rb"
        ) as file:

            response = session.post(

                url,

                data={
                    "chat_id": CHAT_ID
                },

                files={
                    "animation": (
                        "animation.gif",
                        file,
                        "image/gif"
                    )
                },

                timeout=180

            )


        try:

            result = response.json()

        except Exception:

            result = {}


        if not result.get(
            "ok",
            False
        ):

            print(
                "Telegram error:",
                result
            )

            return False


        print(
            "Telegram GIF sent successfully."
        )

        return True


    except Exception as e:

        print(
            f"Telegram GIF error: {e}"
        )

        return False


# ============================================================
# SEND MEDIA
# ============================================================

def send_to_telegram(item):

    if item["type"] == "image":

        return send_photo(
            item["path"]
        )


    if item["type"] == "gif":

        return send_gif(
            item["path"]
        )


    return False


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print("REDDIT -> TELEGRAM BOT")
    print("=" * 60)


    state = load_state()


    index = state.get(
        "index",
        0
    )


    posted_hashes = set(
        state.get(
            "hashes",
            []
        )
    )


    required_type = get_required_type(
        index
    )


    print(
        f"Post number: {index + 1}"
    )

    print(
        f"Required type: {required_type}"
    )

    print(
        "NSFW-only mode: ENABLED"
    )

    print(
        f"Known hashes: {len(posted_hashes)}"
    )

    print("=" * 60)


    item = find_media(

        required_type,

        posted_hashes

    )


    if not item:

        print()
        print(
            "NO SUITABLE NSFW MEDIA FOUND."
        )

        return 1


    print()
    print(
        f"Selected: {item['type']}"
    )


    print(
        "Sending to Telegram..."
    )


    if not send_to_telegram(
        item
    ):

        print(
            "Telegram upload FAILED."
        )

        item["path"].unlink(
            missing_ok=True
        )

        return 1


    # =========================================================
    # ONLY SAVE HISTORY AFTER SUCCESSFUL POST
    # =========================================================

    posted_hashes.add(
        item["hash"]
    )


    state["hashes"] = list(
        posted_hashes
    )[-MAX_HISTORY:]


    state["index"] = index + 1


    save_state(
        state
    )


    item["path"].unlink(
        missing_ok=True
    )


    print()
    print("=" * 60)
    print("POST SUCCESS")
    print("=" * 60)
    print(
        f"Type: {item['type']}"
    )
    print(
        "NSFW: true"
    )
    print(
        f"Next post type: "
        f"{get_required_type(index + 1)}"
    )
    print("=" * 60)


    return 0


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    sys.exit(
        main()
    )
