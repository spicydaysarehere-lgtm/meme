#!/usr/bin/env python3
# post_meme.py
# Reddit -> Telegram media bot
# Sequence: image, image, gif

import os, sys, json, random, tempfile, subprocess
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

TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")
CHAT=os.getenv("TELEGRAM_CHAT_ID")

if not TOKEN or not CHAT:
    sys.exit("Missing Telegram secrets")

STATE=Path("posted.json")
API="https://meme-api.com/gimme/{}/50"

s=requests.Session()
s.headers["User-Agent"]="TelegramRedditBot"

def state():
    if STATE.exists():
        try:return json.loads(STATE.read_text())
        except:pass
    return {"index":0,"posted":[]}

def save(x):
    STATE.write_text(json.dumps(x,indent=2))

def typ(p):
    b=p.read_bytes()[:16]
    if b.startswith(b"GIF"): return "gif"
    if b.startswith(b"\xff\xd8") or b.startswith(b"\x89PNG"): return "image"
    if p.suffix.lower() in (".mp4",".webm",".mov"): return "video"
    return "unknown"

def get(url,p):
    try:
        r=s.get(url,timeout=30)
        if r.ok:
            p.write_bytes(r.content); return True
    except: pass
    return False

def makegif(src,out):
    return subprocess.run(["ffmpeg","-y","-i",str(src),"-vf","fps=10,scale=480:-1","-loop","0",str(out)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0

def find(req,old):
    subs=SUBREDDITS[:]; random.shuffle(subs)
    for sub in subs:
        try: posts=s.get(API.format(sub),timeout=30).json()["memes"]
        except: continue
        random.shuffle(posts)
        for x in posts:
            pid=x.get("postLink") or x.get("url")
            if pid in old: continue
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/"media"
                if not get(x.get("url",""),p): continue
                t=typ(p)
                if req=="photo" and t=="image":
                    return p.read_bytes(),"photo",sub,pid
                if req=="gif":
                    if t=="gif": return p.read_bytes(),"gif",sub,pid
                    if t=="video":
                        g=Path(d)/"a.gif"
                        if makegif(p,g): return g.read_bytes(),"gif",sub,pid
    return None

def send(method,field,data,name,mime,sub):
    r=s.post(f"https://api.telegram.org/bot{TOKEN}/{method}",
        data={"chat_id":CHAT,"caption":"r/"+sub},
        files={field:(name,data,mime)},timeout=180)
    return r.json().get("ok",False)

def main():
    st=state()
    req="gif" if st["index"]%3==2 else "photo"
    x=find(req,set(st["posted"]))
    if not x: return 1
    data,t,sub,pid=x
    ok=send("sendPhoto" if t=="photo" else "sendAnimation",
            "photo" if t=="photo" else "animation",
            data,"image.jpg" if t=="photo" else "animation.gif",
            "image/jpeg" if t=="photo" else "image/gif",sub)
    if ok:
        st["posted"].append(pid)
        st["index"]+=1
        save(st)
        print("POST SUCCESS")
        return 0
    return 1

if __name__=="__main__":
    sys.exit(main())
