```python
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


# ============================================================
# 1. SUBREDDITS
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


# ============================================================
# 2. CONFIGURATION
# ============================================================

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
# 3. HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "RedditTelegramMediaBot/5.0"
    }
)


# ============================================================
# 4. STATE
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

        old_hashes = data.get(
            "hashes",
            []
        )

        if not old_hashes:
            old_hashes = data.get(
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
            "hashes": old_hashes
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
# 5. POST ORDER
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
# 6. HASH
# ============================================================

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


# ============================================================
# 7. DETECT FILE TYPE
# ============================================================

def detect(path):

    try:

        header = path.read_bytes()[:32]

        # GIF
        if header.startswith(
            b"GIF"
        ):
            return "gif"

        # JPEG
        if header.startswith(
            b"\xff\xd8"
        ):
            return "image"

        # PNG
        if header.startswith(
            b"\x89PNG"
        ):
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
# 8. DOWNLOAD
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
# 9. VIDEO TO GIF
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
# 10. FIND MEDIA
# ============================================================

def find_media(required, used):

    subs = SUBREDDITS[:]

    random.shuffle(
        subs
    )


    for sub in subs:

        print(
            f"Checking r/{sub}..."
        )

        try:

            response = session.get(
                API_URL.format(sub),
                timeout=40
            )

            if response.status_code != 200:

                print(
                    f"  API returned HTTP {response.status_code}"
                )

                continue


            data = response.json()

            posts = data.get(
                "memes",
                []
            )

        except Exception as e:

            print(
                f"  Failed to get posts: {e}"
            )

            continue


        random.shuffle(
            posts
        )


        for post in posts:

            # ==================================================
            # NSFW FILTER
            # ==================================================
            #
            # ONLY allow posts explicitly marked NSFW.
            #
            # True  = allowed
            # False = rejected
            # Missing field = rejected
            #
            # ==================================================

            is_nsfw = post.get(
                "nsfw",
                False
            )

            if is_nsfw is not True:

                print(
                    "  Skipping non-NSFW post"
                )

                continue


            print(
                "  NSFW post accepted"
            )


            # ==================================================
            # GET URL
            # ==================================================

            url = post.get(
                "url",
                ""
            )

            if not url:

                continue


            # ==================================================
            # DOWNLOAD
            # ==================================================

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


            # ==================================================
            # HASH
            # ==================================================

            h = file_hash(
                path
            )


            if h in used:

                print(
                    "  Skipping duplicate"
                )

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
                f"  Detected media type: {kind}"
            )


            # ==================================================
            # IMAGE
            # ==================================================

            if required == "image":

                if kind == "image":

                    return {
                        "type": "image",
                        "path": path,
                        "hash": h
                    }


            # ==================================================
            # GIF
            # ==================================================

            if required == "gif":

                # Already a GIF
                if kind == "gif":

                    return {
                        "type": "gif",
                        "path": path,
                        "hash": h
                    }


                # Video -> GIF
                if kind == "video":

                    gif = make_gif(
                        path
                    )


                    path.unlink(
                        missing_ok=True
                    )


                    if gif:

                        return {
                            "type": "gif",
                            "path": gif,
                            "hash": h
                        }


            # ==================================================
            # NOT USABLE
            # ==================================================

            path.unlink(
                missing_ok=True
            )


    return None


# ============================================================
# 11. TELEGRAM
# ============================================================

def send_telegram(item):

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
                file_handle
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
                file_handle
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


        try:

            result = r.json()

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


        return True


    except Exception as e:

        print(
            "Telegram request failed:",
            e
        )

        return False


    finally:

        file_handle.close()


# ============================================================
# 12. MAIN
# ============================================================

def main():

    state = load_state()


    required = needed_type(
        state["index"]
    )


    print(
        "Required media type:",
        required
    )

    print(
        "NSFW filter: ENABLED"
    )


    media = find_media(
        required,
        set(
            state["hashes"]
        )
    )


    if not media:

        print(
            "No suitable NSFW media found"
        )

        return 1


    print(
        "Sending NSFW media to Telegram..."
    )


    if not send_telegram(
        media
    ):

        print(
            "Telegram failed"
        )

        media["path"].unlink(
            missing_ok=True
        )

        return 1


    # ==========================================================
    # SUCCESS
    # ==========================================================

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


    # Remove downloaded file after successful upload
    media["path"].unlink(
        missing_ok=True
    )


    print(
        "POST SUCCESS:",
        required,
        "| NSFW: true"
    )


    return 0


# ============================================================
# 13. RUN
# ============================================================

if __name__ == "__main__":

    sys.exit(
        main()
    )
```
