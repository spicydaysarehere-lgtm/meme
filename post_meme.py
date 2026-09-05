#!/usr/bin/env python3
"""Fully automatic anime Reel pipeline.

Flow:
  AniList -> matching anime -> automatic rights-filtered public video discovery
  -> download -> best-moment analysis -> vertical Reel -> GitHub Release URL
  -> Instagram -> posted.json

The source layer only accepts Internet Archive records carrying recognizable
Creative Commons/public-domain license markers. It does not bypass DRM,
login/paywalls, anti-bot systems, or protected streaming services.
"""

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

from anilist import get_matching_anime
from anime_source import find_video_url, download_video
from best_moment import find_best_moment, render_reel
from instagram import publish_reel

ANIME_GENRES = [x.strip() for x in os.getenv("ANIME_GENRES", "Action,Fantasy").split(",") if x.strip()]
MIN_SCORE = int(os.getenv("MIN_SCORE", "70"))
ANIME_RESULTS = min(50, max(1, int(os.getenv("ANIME_RESULTS", "30"))))
CLIP_MIN_SECONDS = max(3, int(os.getenv("CLIP_MIN_SECONDS", "15")))
CLIP_MAX_SECONDS = max(CLIP_MIN_SECONDS, int(os.getenv("CLIP_MAX_SECONDS", "45")))
POST_ONE_PER_RUN = os.getenv("POST_ONE_PER_RUN", "true").lower() == "true"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "").strip()
GITHUB_RELEASE_TAG = os.getenv("GITHUB_RELEASE_TAG", "anime-reel-host").strip()

INSTAGRAM_CAPTION = os.getenv(
    "INSTAGRAM_CAPTION",
    "#anime #animeclips #animeedit #reels #animereels",
).strip()

POSTED_FILE = Path("posted.json")


def log(message):
    print(f"[BOT] {message}", flush=True)


def die(message):
    print(f"[ERROR] {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def require_environment():
    required = {
        "GITHUB_TOKEN": GITHUB_TOKEN,
        "GITHUB_REPOSITORY": GITHUB_REPOSITORY,
        "INSTAGRAM_ACCESS_TOKEN": os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip(),
        "INSTAGRAM_USER_ID": os.getenv("INSTAGRAM_USER_ID", "").strip(),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        die("Missing required settings: " + ", ".join(missing))
    if not ANIME_GENRES:
        die("ANIME_GENRES is empty")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        die("ffmpeg and ffprobe are required")


def load_posted():
    if not POSTED_FILE.exists():
        return set()
    try:
        value = json.loads(POSTED_FILE.read_text(encoding="utf-8"))
        return set(map(str, value)) if isinstance(value, list) else set()
    except Exception:
        return set()


def save_posted(values):
    POSTED_FILE.write_text(json.dumps(sorted(values), indent=2), encoding="utf-8")


def anime_title(anime):
    title = anime.get("title", {})
    return title.get("english") or title.get("romaji") or title.get("native") or f"Anime {anime['id']}"


def github_release():
    api = "https://api.github.com"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{api}/repos/{GITHUB_REPOSITORY}/releases/tags/{GITHUB_RELEASE_TAG}"
    r = requests.get(url, headers=headers, timeout=60)
    if r.status_code == 200:
        return r.json()
    if r.status_code != 404:
        r.raise_for_status()

    r = requests.post(
        f"{api}/repos/{GITHUB_REPOSITORY}/releases",
        headers=headers,
        json={
            "tag_name": GITHUB_RELEASE_TAG,
            "name": GITHUB_RELEASE_TAG,
            "body": "Temporary hosting for automatically generated Instagram Reels.",
            "draft": False,
            "prerelease": False,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def upload_release_asset(file_path):
    release = github_release()
    upload_url = release["upload_url"].split("{", 1)[0]
    asset_name = file_path.name
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "video/mp4",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Remove an older asset with the same filename, if present.
    for asset in release.get("assets", []):
        if asset.get("name") == asset_name:
            requests.delete(asset["url"], headers=headers, timeout=60).raise_for_status()

    with file_path.open("rb") as stream:
        response = requests.post(
            upload_url,
            params={"name": asset_name},
            headers=headers,
            data=stream,
            timeout=600,
        )
    response.raise_for_status()

    return f"https://github.com/{GITHUB_REPOSITORY}/releases/download/{GITHUB_RELEASE_TAG}/{asset_name}"


def main():
    require_environment()
    posted = load_posted()

    log(f"Searching AniList for anime containing ALL genres: {', '.join(ANIME_GENRES)}")
    candidates = get_matching_anime(
        ANIME_GENRES,
        minimum_score=MIN_SCORE,
        per_page=ANIME_RESULTS,
    )
    candidates = [a for a in candidates if str(a["id"]) not in posted]
    random.shuffle(candidates)

    if not candidates:
        log("No unposted AniList candidates matched the requested genres/score.")
        return

    log(f"Found {len(candidates)} unposted candidates.")

    with tempfile.TemporaryDirectory(prefix="anime_reel_") as temp_dir:
        temp = Path(temp_dir)

        for anime in candidates:
            aid = str(anime["id"])
            title = anime_title(anime)
            log(f"Trying {title} (AniList ID {aid})")

            try:
                source_url = find_video_url(anime)
                if not source_url:
                    log("  No automatically discovered rights-approved video source; skipping.")
                    continue

                source_path = temp / f"source_{aid}.video"
                reel_path = temp / f"reel_{aid}.mp4"

                log("  Downloading source video...")
                download_video(source_url, source_path)

                log("  Searching for the strongest moment...")
                start, length, score = find_best_moment(
                    source_path,
                    CLIP_MIN_SECONDS,
                    CLIP_MAX_SECONDS,
                )
                log(f"  Best moment: start={start:.2f}s length={length:.2f}s score={score}")

                render_reel(source_path, reel_path, start, length)
                public_url = upload_release_asset(reel_path)
                log(f"  Public Reel URL: {public_url}")

                caption = f"{title}\n\n{INSTAGRAM_CAPTION}"
                media_id = publish_reel(public_url, caption)
                log(f"  Instagram published: {media_id}")

                posted.add(aid)
                save_posted(posted)
                log("  Saved posted.json")

                if POST_ONE_PER_RUN:
                    return

            except Exception as exc:
                log(f"  FAILED: {type(exc).__name__}: {exc}")
                continue

    log("Run finished without another successful post.")


if __name__ == "__main__":
    main()
