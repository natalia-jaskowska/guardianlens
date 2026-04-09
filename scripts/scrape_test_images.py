"""Scrape test screenshots from Reddit for development debugging.

DEBUGGING ONLY. The downloaded images:

- Land in ``data/scraped/`` which is **already gitignored** — they never
  end up in the repo.
- Contain real users' content. Do NOT use them in any submission, demo
  video, public release, or any context where the dashboard would label
  them as "GROOMING DETECTED" / "BULLYING DETECTED". That would be
  defamation. They exist only so we can verify the analyzer + rendering
  pipeline works on real images instead of synthetic Pillow chats.

Source: Reddit's public JSON API. No auth required for read-only access.
Rate limit: ~1 request/second per Reddit's etiquette guidelines.

Usage::

    .venv/bin/python scripts/scrape_test_images.py
    .venv/bin/python scripts/scrape_test_images.py --limit 20
    .venv/bin/python scripts/scrape_test_images.py --subreddit Minecraft

Output::

    data/scraped/<subreddit>_<post_id>.{jpg,png,webp}
    data/scraped/manifest.json
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

# Reddit blocks the default urllib UA. Use a unique one identifying the project.
USER_AGENT = "guardlens-debug/0.1 (research; pipeline-test)"

# Subreddits likely to contain screenshots of game / chat / app content
# that the GuardLens analyzer should be able to read with Gemma 4 vision.
DEFAULT_SUBREDDITS: tuple[tuple[str, str, str], ...] = (
    ("Minecraft", "top", "month"),
    ("discordapp", "top", "month"),
    ("RobloxScreenShots", "top", "month"),
    ("ios", "top", "month"),
    ("instagramreality", "top", "month"),
    ("PhoneScreens", "top", "year"),
    ("messages", "top", "year"),
    ("ihadastroke", "top", "month"),
)

OUTPUT_DIR = Path("data/scraped")
ALLOWED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
MIN_FILE_BYTES = 5_000  # skip tiny thumbnails
MAX_FILE_BYTES = 10_000_000  # skip huge files


def fetch_subreddit(name: str, sort: str, t: str, limit: int = 25) -> list[dict]:
    """Pull post metadata from a subreddit's public JSON endpoint."""
    url = f"https://www.reddit.com/r/{name}/{sort}.json?limit={limit}&t={t}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        print(f"  ! r/{name}: HTTP {exc.code}")
        return []
    except urllib.error.URLError as exc:
        print(f"  ! r/{name}: {exc.reason}")
        return []
    return [child.get("data", {}) for child in payload.get("data", {}).get("children", [])]


def is_image_post(post: dict) -> bool:
    """Filter to direct-image posts that aren't NSFW or galleries."""
    if post.get("over_18"):
        return False
    if post.get("is_gallery"):
        return False
    url = (post.get("url") or post.get("url_overridden_by_dest") or "").lower()
    if not url:
        return False
    if not url.endswith(ALLOWED_EXTENSIONS):
        # Reddit sometimes flags image posts via post_hint instead of file extension
        return post.get("post_hint") == "image"
    return True


def download_image(post: dict, dest: Path) -> Path | None:
    """Download a single post's image. Returns the saved path or None on failure."""
    url = post.get("url") or post.get("url_overridden_by_dest")
    if not url:
        return None
    ext = url.rsplit(".", 1)[-1].split("?")[0].lower()
    if ext not in {"png", "jpg", "jpeg", "webp"}:
        ext = "jpg"
    filename = f"{post.get('subreddit', 'unknown')}_{post.get('id', 'no-id')}.{ext}"
    target = dest / filename
    if target.exists():
        return target
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        print(f"  ! {filename}: HTTP {exc.code}")
        return None
    except urllib.error.URLError as exc:
        print(f"  ! {filename}: {exc.reason}")
        return None

    if len(data) < MIN_FILE_BYTES:
        print(f"  ! {filename}: too small ({len(data)} bytes), skipping")
        return None
    if len(data) > MAX_FILE_BYTES:
        print(f"  ! {filename}: too large ({len(data) // 1_000_000} MB), skipping")
        return None

    target.write_bytes(data)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape ~N test screenshots from Reddit (debugging only)."
    )
    parser.add_argument("--limit", type=int, default=10, help="Max images to download")
    parser.add_argument(
        "--subreddit",
        action="append",
        default=None,
        help="Override default subreddit list. Repeatable. e.g. --subreddit Minecraft",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output: {OUTPUT_DIR.resolve()}")
    print("DEBUGGING ONLY — these images must not be committed or used in submissions.\n")

    targets: list[tuple[str, str, str]] = (
        [(s, "top", "month") for s in args.subreddit]
        if args.subreddit
        else list(DEFAULT_SUBREDDITS)
    )

    manifest: list[dict] = []
    downloaded = 0

    for subreddit, sort, t in targets:
        if downloaded >= args.limit:
            break
        print(f"Fetching r/{subreddit} ({sort}/{t}) ...")
        posts = fetch_subreddit(subreddit, sort, t, limit=25)
        time.sleep(1.0)  # be polite

        for post in posts:
            if downloaded >= args.limit:
                break
            if not is_image_post(post):
                continue
            target = download_image(post, OUTPUT_DIR)
            if target is None:
                continue
            title = (post.get("title") or "")[:60]
            print(f"  + {target.name}  ({title})")
            manifest.append(
                {
                    "file": target.name,
                    "subreddit": post.get("subreddit"),
                    "post_id": post.get("id"),
                    "title": post.get("title"),
                    "permalink": f"https://reddit.com{post.get('permalink', '')}",
                    "image_url": post.get("url"),
                    "score": post.get("score"),
                    "created_utc": post.get("created_utc"),
                    "size_bytes": target.stat().st_size,
                }
            )
            downloaded += 1
            time.sleep(0.6)

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print()
    print(f"Downloaded {downloaded} images to {OUTPUT_DIR}/")
    print(f"Manifest: {manifest_path}")
    if downloaded == 0:
        print("\nNo images downloaded. Reddit may have rate-limited or the")
        print("target subreddits returned no image posts in the time window.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
