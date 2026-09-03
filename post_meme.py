# PART 1/2
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

API = "https://meme-api.com/gimme/{}/50"
STATE = Path("posted.json")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN","")
CHAT = os.getenv("TELEGRAM_CHAT_ID","")

if not TOKEN or not CHAT:
    print("Missing telegram settings")
    sys.exit(1)

s = requests.Session()
s.headers["User-Agent"] = "TelegramRedditBot/1.0"


def load():
    if not STATE.exists():
        return {"index":0,"posted":[]}
    try:
        return json.loads(STATE.read_text())
    except:
        return {"index":0,"posted":[]}


def save(x):
    STATE.write_text(json.dumps(x,indent=2))


def need(i):
    return "gif" if i % 3 == 2 else "image"


def kind(p):
    try:
        h=p.read_bytes()[:32]

        if h.startswith(b"GIF"):
            return "gif"

        if (
            h.startswith(b"\xff\xd8")
            or h.startswith(b"\x89PNG")
            or (
                h[:4]==b"RIFF"
                and h[8:12]==b"WEBP"
            )
        ):
            return "image"

    except:
        pass

    e=p.suffix.lower()

    if e==".gif":
        return "gif"

    if e in [".jpg",".jpeg",".png",".webp"]:
        return "image"

    if e in [".mp4",".webm",".mov",".m4v"]:
        return "video"

    return "unknown"


def get_posts(sub):
    try:
        r=s.get(
            API.format(sub),
            timeout=30
        )

        if r.status_code==200:
            a=r.json().get("memes",[])
            random.shuffle(a)
            return a

    except:
        pass

    return []


def download(url,p):
    try:
        r=s.get(
            url,
            timeout=40
        )

        if r.status_code!=200:
            return False

        p.write_bytes(r.content)
        return True

    except:
        return False


def video_gif(src,out):

    cmd=[
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        "fps=10,scale=480:-1:flags=lanczos",
        "-loop",
        "0",
        str(out)
    ]

    r=subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return (
        r.returncode==0
        and out.exists()
        and kind(out)=="gif"
    )


def find(required,posted):

    subs=SUBREDDITS[:]
    random.shuffle(subs)

    for sub in subs:

        for post in get_posts(sub):

            pid=(
                post.get("postLink")
                or post.get("url")
            )

            if not pid or pid in posted:
                continue

            url=post.get("url","")

            if not url:
                continue

            with tempfile.TemporaryDirectory() as d:

                src=Path(d)/"file"

                if not download(url,src):
                    continue

                t=kind(src)

                if required=="image" and t=="image":
                    return {
                        "type":"image",
                        "path":src,
                        "sub":sub,
                        "id":pid,
                        "temp":d
                    }

                if required=="gif":

                    if t=="gif":
                        return {
                            "type":"gif",
                            "path":src,
                            "sub":sub,
                            "id":pid,
                            "temp":d
                        }

                    if t=="video":

                        out=Path(d)/"animation.gif"

                        if video_gif(src,out):
                            return {
                                "type":"gif",
                                "path":out,
                                "sub":sub,
                                "id":pid,
                                "temp":d
                            }

    return None
    # PART 2/2

def telegram(method,field,path,name,mime,caption=""):

    url=f"https://api.telegram.org/bot{TOKEN}/{method}"

    with open(path,"rb") as f:

        files={
            field:(
                name,
                f,
                mime
            )
        }

        data={
            "chat_id":CHAT
        }

        # NO IMAGE CAPTION
        if method=="sendAnimation":
            data["caption"]=caption

        try:
            r=s.post(
                url,
                data=data,
                files=files,
                timeout=180
            )

            j=r.json()

            return j.get("ok",False)

        except Exception as e:
            print(e)
            return False



def send_image(path):

    # remove any possible caption
    return telegram(
        "sendPhoto",
        "photo",
        path,
        "image.jpg",
        "image/jpeg"
    )



def send_gif(path,sub):

    return telegram(
        "sendAnimation",
        "animation",
        path,
        "animation.gif",
        "image/gif",
        f"r/{sub}"
    )



def main():

    state=load()

    idx=state.get(
        "index",
        0
    )

    posted=set(
        state.get(
            "posted",
            []
        )
    )

    required=need(idx)

    print(
        "Looking for",
        required
    )

    media=find(
        required,
        posted
    )

    if not media:

        print(
            "No media found"
        )

        return 1


    ok=False


    if media["type"]=="image":

        ok=send_image(
            media["path"]
        )


    elif media["type"]=="gif":

        ok=send_gif(
            media["path"],
            media["sub"]
        )


    if not ok:

        print(
            "Telegram failed"
        )

        return 1


    state["posted"].append(
        media["id"]
    )


    if len(state["posted"])>1000:

        state["posted"]=(
            state["posted"][-1000:]
        )


    state["index"]=idx+1


    save(state)


    print(
        "POST SUCCESS"
    )

    return 0



if __name__=="__main__":

    try:

        sys.exit(
            main()
        )

    except KeyboardInterrupt:

        sys.exit(130)

    except Exception as e:

        print(
            "ERROR:",
            e
        )

        sys.exit(1)
