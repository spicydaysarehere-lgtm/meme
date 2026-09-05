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
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "RedditTelegramMediaBot/5.0"
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

        hashes = data.get(
            "hashes",
            []
        )

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
            f"Could not read state file: {e}"
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
# POST ORDER
# image -> image -> gif
# ============================================================

def needed_type(index):

    sequence = [
        "image",
        "image",
        "gif"
    ]

    return sequence[
        index % len(sequence)
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

            chunk = f.read(1024 * 1024)

            if not chunk:
                break

            h.update(chunk)

    return h.hexdigest()


# ============================================================
# DETECT FILE TYPE
# ============================================================

def detect(path):

    try:

        header = path.read_bytes()[:32]

        if header.startswith(b"GIF"):
            return "gif"

        if header.startswith(b"\xff\xd8"):
            return "image"

        if header.startswith(b"\x89PNG"):
            return "image"

        if (
            len(header) >= 12
            and header[:4] == b"RIFF"
            and header[8:12] == b"WEBP"
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

        response = session.get(
            url,
            timeout=60
        )

        if response.status_code != 200:

            print(
                f"Download failed: HTTP {response.status_code}"
            )

            return False

        if not response.content:

            print(
                "Download returned empty file"
            )

            return False

        path.write_bytes(
            response.content
        )

        return True

    except Exception as e:

        print(
            f"Download error: {e}"
        )

        return False


# ============================================================
# VIDEO TO GIF
# ============================================================

def make_gif(video):

    output = video.with_name(
        video.stem + "_converted.gif"
    )

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

    try:

        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=180
        )

    except Exception as e:

        print(
            f"FFmpeg error: {e}"
        )

        return None


    if (
        result.returncode == 0
        and output.exists()
        and output.stat().st_size > 0
    ):

        return output


    return None


# ============================================================
# FIND MEDIA
# ============================================================

def find_media(required, used):

    subs = SUBREDDITS[:]

    random.shuffle(subs)


    for sub in subs:

        print(
            f"\nChecking r/{sub}..."
        )

        try:

            response = session.get(
                API_URL.format(sub),
                timeout=40
            )

            if response.status_code != 200:

                print(
                    f"API error: HTTP {response.status_code}"
                )

                continue


            data = response.json()

            posts = data.get(
                "memes",
                []
            )

        except Exception as e:

            print(
                f"Could not get subreddit data: {e}"
            )

            continue


        random.shuffle(posts)


        for post in posts:

            # ==================================================
            # NSFW FILTER
            # ==================================================
            #
            # ONLY allow posts where:
            #
            #     "nsfw": true
            #
            # Everything else is rejected.
            #
            # ==================================================

            if post.get("nsfw") is not True:

                print(
                    "  SKIP: not marked NSFW"
                )

                continue


            print(
                "  NSFW: accepted"
            )


            # ==================================================
            # GET MEDIA URL
            # ==================================================

            url = post.get(
                "url",
                ""
            ).strip()


            if not url:

                print(
                    "  SKIP: no media URL"
                )

                continue


            # ==================================================
            # CREATE TEMP FILE
            # ==================================================

            temp = tempfile.NamedTemporaryFile(
                delete=False
            )

            temp.close()


            path = Path(
                temp.name
            )


            # ==================================================
            # DOWNLOAD
            # ==================================================

            if not download(
                url,
                path
            ):

                path.unlink(
                    missing_ok=True
                )

                continue


            # ==================================================
            # DETECT TYPE
            # ==================================================

            kind = detect(
                path
            )


            print(
                f"  Media type: {kind}"
            )


            # ==================================================
            # IMAGE
            # ==================================================

            if required == "image":

                if kind != "image":

                    print(
                        "  SKIP: not an image"
                    )

                    path.unlink(
                        missing_ok=True
                    )

                    continue


                h = file_hash(
                    path
                )


                if h in used:

                    print(
                        "  SKIP: duplicate image"
                    )

                    path.unlink(
                        missing_ok=True
                    )

                    continue


                return {
                    "type": "image",
                    "path": path,
                    "hash": h
                }


            # ==================================================
            # GIF
            # ==================================================

            if required == "gif":

                # ----------------------------------------------
                # Already a GIF
                # ----------------------------------------------

                if kind == "gif":

                    h = file_hash(
                        path
                    )


                    if h in used:

                        print(
                            "  SKIP: duplicate GIF"
                        )

                        path.unlink(
                            missing_ok=True
                        )

                        continue


                    return {
                        "type": "gif",
                        "path": path,
                        "hash": h
                    }


                # ----------------------------------------------
                # Video -> GIF
                # ----------------------------------------------

                if kind == "video":

                    print(
                        "  Converting video to GIF..."
                    )


                    gif = make_gif(
                        path
                    )


                    path.unlink(
                        missing_ok=True
                    )


                    if not gif:

                        print(
                            "  SKIP: GIF conversion failed"
                        )

                        continue


                    # Hash the final GIF
                    h = file_hash(
                        gif
                    )


                    if h in used:

                        print(
                            "  SKIP: duplicate converted GIF"
                        )

                        gif.unlink(
                            missing_ok=True
                        )

                        continue


                    return {
                        "type": "gif",
                        "path": gif,
                        "hash": h
                    }


                # ----------------------------------------------
                # Unsupported media
                # ----------------------------------------------

                print(
                    "  SKIP: cannot use for GIF"
                )

                path.unlink(
                    missing_ok=True
                )

                continue


            path.unlink(
                missing_ok=True
            )


    return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(item):

    file_handle = None


    try:

        if item["type"] == "image":

            url = (
                f"https://api.telegram.org/"
                f"bot{TOKEN}/sendPhoto"
            )


            file_handle = open(
                item["path"],
                "rb"
            )


            files = {
                "photo": (
                    "image.jpg",
                    file_handle,
                    "image/jpeg"
                )
            }


        else:

            url = (
                f"https://api.telegram.org/"
                f"bot{TOKEN}/sendAnimation"
            )


            file_handle = open(
                item["path"],
                "rb"
            )


            files = {
                "animation": (
                    "animation.gif",
                    file_handle,
                    "image/gif"
                )
            }


        response = session.post(
            url,
            data={
                "chat_id": CHAT_ID
            },
            files=files,
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
                "Telegram API error:",
                result
            )

            return False


        return True


    except Exception as e:

        print(
            f"Telegram error: {e}"
        )

        return False


    finally:

        if file_handle is not None:

            file_handle.close()


# ============================================================
# MAIN
# ============================================================

def main():

    state = load_state()


    required = needed_type(
        state["index"]
    )


    print(
        "=========================================="
    )

    print(
        "Reddit -> Telegram Bot"
    )

    print(
        "=========================================="
    )

    print(
        f"Post number: {state['index'] + 1}"
    )

    print(
        f"Required type: {required}"
    )

    print(
        "NSFW filter: ENABLED"
    )

    print(
        "=========================================="
    )


    media = find_media(
        required,
        set(
            state["hashes"]
        )
    )


    if not media:

        print(
            "\nNo suitable NSFW media found."
        )

        return 1


    print(
        f"\nSending {media['type']} to Telegram..."
    )


    if not send_telegram(
        media
    ):

        print(
            "Telegram upload failed."
        )

        media["path"].unlink(
            missing_ok=True
        )

        return 1


    # =========================================================
    # SAVE HISTORY ONLY AFTER SUCCESSFUL POST
    # =========================================================

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


    # Delete temporary media
    media["path"].unlink(
        missing_ok=True
    )


    print(
        "\n=========================================="
    )

    print(
        "POST SUCCESS"
    )

    print(
        f"Type: {media['type']}"
    )

    print(
        "NSFW: true"
    )

    print(
        "=========================================="
    )


    return 0


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    sys.exit(
        main()
    )
