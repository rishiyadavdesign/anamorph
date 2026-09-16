#!/usr/bin/env python3
import cgi
import hashlib
import hmac
import html
import json
import mimetypes
import os
import re
import secrets
import shutil
import time
import uuid
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data" / "cms.json"
SECRET_FILE = ROOT / "data" / ".cms_secret"
WORK_DETAIL_TEMPLATE = ROOT / "templates" / "work-detail-framer.html"
UPLOAD_DIR = ROOT / "uploads"
IMAGE_DIR = UPLOAD_DIR / "images"
VIDEO_DIR = UPLOAD_DIR / "videos"

CMS_USER = os.environ.get("CMS_USER", "admin")
CMS_PASSWORD = os.environ.get("CMS_PASSWORD", "admin123")
MAX_UPLOAD_BYTES = int(os.environ.get("CMS_MAX_UPLOAD_MB", "250")) * 1024 * 1024
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}
ALLOWED_VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v"}


def ensure_storage():
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        DATA_FILE.write_text(json.dumps({"projects": []}, indent=2))
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32))


def secret_key():
    ensure_storage()
    return SECRET_FILE.read_text().strip().encode()


def load_cms():
    ensure_storage()
    with DATA_FILE.open() as f:
        data = json.load(f)
    data.setdefault("projects", [])
    data.setdefault("reels", [])
    data.setdefault("home", {"text_replacements": [], "image_replacements": []})
    return data


def save_cms(data):
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(DATA_FILE)


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


def unique_slug(data, collection, base, current_id=None):
    base = slugify(base)
    existing = {p.get("slug") for p in data.get(collection, []) if p.get("id") != current_id}
    if base not in existing:
        return base
    i = 2
    while f"{base}-{i}" in existing:
        i += 1
    return f"{base}-{i}"


def public_projects():
    projects = [p for p in load_cms()["projects"] if p.get("published", True)]
    return sorted(projects, key=lambda p: p.get("created_at", ""), reverse=True)


def public_reels():
    reels = [r for r in load_cms().get("reels", []) if r.get("published", True)]
    return sorted(reels, key=lambda r: r.get("created_at", ""), reverse=True)


def public_home():
    home = load_cms().get("home", {})
    return {
        "text_replacements": home.get("text_replacements", []) if isinstance(home.get("text_replacements", []), list) else [],
        "image_replacements": home.get("image_replacements", []) if isinstance(home.get("image_replacements", []), list) else [],
    }


def pairs_to_text(pairs):
    return "\n".join(f"{pair.get('from', '')} => {pair.get('to', '')}" for pair in pairs or [])


def text_to_pairs(value):
    pairs = []
    for line in str(value or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        separator = "=>" if "=>" in stripped else "|"
        if separator not in stripped:
            continue
        old, new = stripped.split(separator, 1)
        old = old.strip()
        new = new.strip()
        if old and new:
            pairs.append({"from": old, "to": new})
    return pairs


def append_pair(pairs, old, new):
    old = str(old or "").strip()
    new = str(new or "").strip()
    if old and new:
        pairs.append({"from": old, "to": new})


def find_project(slug):
    for project in public_projects():
        if project.get("slug") == slug:
            return project
    return None


def next_project(projects, slug):
    if not projects:
        return None
    index = next((i for i, p in enumerate(projects) if p.get("slug") == slug), -1)
    return projects[(index + 1) % len(projects)]


def escape(value):
    return html.escape(str(value or ""), quote=True)


def youtube_id(value=""):
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        return parsed.path.strip("/").split("/")[0]
    if "youtube.com" in host:
        if parsed.path.startswith("/watch"):
            return parse_qs(parsed.query).get("v", [""])[0]
        parts = [part for part in parsed.path.split("/") if part]
        if parts and parts[0] in {"shorts", "embed", "live"} and len(parts) > 1:
            return parts[1]
    return ""


def youtube_embed(value="", autoplay=False):
    video_id = youtube_id(value)
    if not video_id:
        return ""
    if autoplay:
        params = f"autoplay=1&mute=1&loop=1&playlist={quote(video_id)}&controls=0&rel=0&playsinline=1"
    else:
        params = "rel=0&playsinline=1"
    return f"https://www.youtube.com/embed/{quote(video_id)}?{params}"


def drive_image(value=""):
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if "drive.google.com" not in parsed.netloc.lower():
        return raw
    parts = [part for part in parsed.path.split("/") if part]
    file_id = ""
    if "d" in parts:
        index = parts.index("d")
        if index + 1 < len(parts):
            file_id = parts[index + 1]
    if not file_id:
        file_id = parse_qs(parsed.query).get("id", [""])[0]
    return f"https://drive.google.com/thumbnail?id={quote(file_id)}&sz=w2400" if file_id else raw


def media_html(item, mode="card"):
    image = escape(item.get("image"))
    video = str(item.get("video") or "").strip()
    title = escape(item.get("title"))
    embed = youtube_embed(video, mode != "detail")
    if embed:
        css_class = ' class="detail-media"' if mode == "detail" else ""
        return f'<iframe{css_class} src="{escape(embed)}" title="{title}" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>'
    if video:
        controls = "controls " if mode == "detail" else ""
        css_class = ' class="detail-media"' if mode == "detail" else ""
        return f'<video{css_class} src="{escape(video)}" poster="{image}" {controls}autoplay muted loop playsinline></video>'
    css_class = ' class="detail-media"' if mode == "detail" else ""
    return f'<img{css_class} src="{image}" alt="{title}">'


def signed_session_value():
    timestamp = str(int(time.time()))
    signature = hmac.new(secret_key(), timestamp.encode(), hashlib.sha256).hexdigest()
    return f"{timestamp}:{signature}"


def valid_session(value):
    if not value or ":" not in value:
        return False
    timestamp, signature = value.split(":", 1)
    expected = hmac.new(secret_key(), timestamp.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        age = time.time() - int(timestamp)
    except ValueError:
        return False
    return 0 <= age <= 60 * 60 * 24 * 7


def page_shell(title, body, extra_head=""):
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <link rel="icon" href="/assets/local/d189f945785ecf79.png">
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0a0a0a;
      --bg2: #0e1416;
      --paper: #f4f2ed;
      --muted: rgba(244,242,237,.62);
      --faint: rgba(244,242,237,.14);
      --line: rgba(244,242,237,.12);
      --accent: #db3903;
      --soft: rgba(244,242,237,.06);
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{ margin: 0; background: var(--bg); color: var(--paper); font-family: Inter, Arial, sans-serif; -webkit-font-smoothing: antialiased; }}
    body:before {{ content: ""; position: fixed; inset: 0; z-index: -2; background: radial-gradient(circle at 50% 0%, rgba(219,57,3,.13), transparent 30%), linear-gradient(180deg, #0e1416 0%, #0a0a0a 38%, #0a0a0a 100%); }}
    body:after {{ content: ""; position: fixed; inset: 0; z-index: -1; pointer-events: none; background: linear-gradient(90deg, rgba(244,242,237,.035) 1px, transparent 1px), linear-gradient(180deg, rgba(244,242,237,.03) 1px, transparent 1px); background-size: 20vw 100%, 100% 120px; mask-image: linear-gradient(to bottom, #000, transparent 78%); }}
    a {{ color: inherit; text-decoration: none; }}
    .wrap {{ width: min(1200px, calc(100vw - 32px)); margin: 0 auto; }}
    .topbar {{ position: fixed; left: 0; right: 0; bottom: 24px; z-index: 10; pointer-events: none; }}
    .topbar .wrap {{ width: max-content; max-width: calc(100vw - 28px); min-height: 0; display: flex; align-items: center; justify-content: center; gap: 8px; padding: 8px; border: 1px solid var(--line); border-radius: 16px; background: rgba(10,10,10,.66); backdrop-filter: blur(18px); box-shadow: 0 18px 60px rgba(0,0,0,.36); pointer-events: auto; }}
    .brand {{ font-size: 21px; letter-spacing: -.08em; line-height: .86; padding: 0 8px 0 4px; }}
    .nav {{ display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }}
    .pill, button, input[type=submit] {{ border: 1px solid var(--line); background: rgba(244,242,237,.06); color: var(--paper); border-radius: 999px; padding: 10px 14px; font: inherit; cursor: pointer; transition: transform .35s cubic-bezier(.16,1,.3,1), background .35s, border-color .35s; }}
    .pill:hover, button:hover, input[type=submit]:hover {{ transform: translateY(-1px); background: rgba(244,242,237,.12); border-color: rgba(244,242,237,.22); }}
    .pill.primary, input[type=submit], button.primary {{ background: var(--accent); border-color: var(--accent); }}
    .hero {{ min-height: 86vh; display: grid; align-items: end; padding: 120px 0 34px; border-bottom: 1px solid var(--line); position: relative; overflow: hidden; }}
    .hero.compact {{ min-height: 50vh; }}
    .hero-media {{ position: absolute; inset: 0; opacity: .48; transform: scale(1.04); animation: posterIn 2.4s cubic-bezier(.16,1,.3,1) forwards; }}
    .hero-media img, .hero-media video, .hero-media iframe {{ width: 100%; height: 100%; object-fit: cover; display: block; border: 0; filter: saturate(.82) contrast(1.08); }}
    .hero-media:after {{ content: ""; position: absolute; inset: 0; background: radial-gradient(circle at 50% 45%, transparent 0 36%, rgba(10,10,10,.5) 74%), linear-gradient(180deg, rgba(10,10,10,.22), rgba(10,10,10,.92)); }}
    .hero-content {{ position: relative; z-index: 1; }}
    .opening {{ min-height: 100vh; position: relative; display: grid; align-items: end; padding: 112px 0 38px; overflow: hidden; border-bottom: 1px solid var(--line); }}
    .opening .wrap {{ position: relative; z-index: 1; }}
    .opening-copy {{ font-size: clamp(48px, 6.45vw, 77px); line-height: 1.06; letter-spacing: -.07em; max-width: 1010px; margin: 0 0 58px; }}
    .opening-copy span {{ color: var(--muted); }}
    .reveal-word {{ display: inline-block; animation: wordIn 1.25s cubic-bezier(.16,1,.3,1) both; }}
    .reveal-word:nth-child(2n) {{ animation-delay: .06s; }}
    .reveal-word:nth-child(3n) {{ animation-delay: .12s; }}
    .reveal-muted {{ color: var(--muted); }}
    .time-grid {{ position: absolute; inset: 0; display: grid; grid-template-columns: repeat(5, 1fr); pointer-events: none; color: var(--muted); font-size: 12px; }}
    .time-tick {{ border-left: 1px solid var(--line); display: grid; grid-template-rows: auto 1fr auto 1fr; padding: 24px 10px; animation: tickIn 1.4s cubic-bezier(.16,1,.3,1) both; }}
    .time-tick:nth-child(even) {{ animation-name: tickDown; }}
    .time-tick:last-child {{ border-right: 1px solid var(--line); }}
    .plus {{ align-self: center; justify-self: start; color: var(--paper); font-size: 22px; line-height: 1; }}
    .rule {{ width: 1px; background: var(--line); min-height: 80px; }}
    .hero-row {{ display: grid; grid-template-columns: 240px 1fr 300px; gap: 28px; align-items: end; }}
    .services {{ display: grid; gap: 8px; color: var(--paper); font-size: 15px; letter-spacing: -.03em; }}
    .copy-large {{ max-width: 430px; margin-left: auto; text-align: right; font-size: clamp(22px, 2.4vw, 34px); line-height: 1.03; letter-spacing: -.055em; color: var(--muted); }}
    .copy-large strong {{ color: var(--paper); font-weight: 400; }}
    .eyebrow {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
    h1 {{ font-weight: 400; letter-spacing: -.08em; line-height: .86; font-size: clamp(72px, 17vw, 238px); margin: 18px 0 0; text-transform: capitalize; animation: riseIn 1.6s .15s cubic-bezier(.16,1,.3,1) both; }}
    h2 {{ font-weight: 400; letter-spacing: -.055em; line-height: 1; font-size: clamp(36px, 7vw, 86px); margin: 0; }}
    p {{ color: var(--muted); line-height: 1.55; }}
    .timeline {{ display: grid; grid-template-columns: repeat(5, 1fr); border-top: 1px solid var(--line); margin-top: 26px; color: rgba(244,242,237,.45); font-size: 12px; }}
    .tick {{ min-height: 74px; border-left: 1px solid var(--line); padding: 10px; display: flex; justify-content: space-between; align-items: flex-start; }}
    .tick:last-child {{ border-right: 1px solid var(--line); }}
    .section-head {{ display: grid; grid-template-columns: 1fr auto; align-items: end; gap: 20px; padding: 88px 0 22px; border-bottom: 1px solid var(--line); }}
    .work-count {{ display: grid; grid-template-columns: 1fr auto; align-items: center; padding: 22px 0; border-bottom: 1px solid var(--line); font-size: 14px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }}
    .work-count b {{ font-weight: 400; color: var(--paper); }}
    .work-list {{ padding: 0 0 112px; }}
    .work-row {{ display: grid; grid-template-columns: 70px minmax(210px,1fr) minmax(230px,.9fr) 110px minmax(180px,.75fr); gap: 20px; align-items: center; min-height: 148px; border-bottom: 1px solid var(--line); position: relative; overflow: hidden; animation: riseIn 1.2s cubic-bezier(.16,1,.3,1) both; }}
    .work-row:hover {{ border-color: rgba(244,242,237,.22); }}
    .work-row:hover .work-thumb {{ opacity: 1; transform: translateY(-50%) scale(1); }}
    .work-num, .work-year, .work-spec {{ color: var(--muted); font-size: 14px; text-transform: uppercase; }}
    .work-title {{ font-size: clamp(38px,6vw,84px); line-height: .9; letter-spacing: -.075em; font-weight: 400; }}
    .work-project {{ font-size: clamp(20px,2.3vw,34px); line-height: 1.02; letter-spacing: -.055em; color: var(--muted); }}
    .work-thumb {{ position: absolute; right: 18%; top: 50%; width: min(34vw,430px); aspect-ratio: 16 / 9; object-fit: cover; opacity: 0; transform: translateY(-50%) scale(.96); transition: .55s cubic-bezier(.16,1,.3,1); pointer-events: none; z-index: 2; box-shadow: 0 22px 80px rgba(0,0,0,.42); }}
    .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; padding: 28px 0 90px; }}
    .cms-card-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; padding: 28px 0 120px; }}
    .cms-card {{ min-height: 260px; display: grid; align-content: space-between; border: 1px solid var(--line); background: rgba(244,242,237,.045); padding: 18px; transition: transform .35s cubic-bezier(.16,1,.3,1), border-color .35s, background .35s; }}
    .cms-card:hover {{ transform: translateY(-2px); border-color: rgba(244,242,237,.26); background: rgba(244,242,237,.07); }}
    .cms-card h2 {{ font-size: clamp(40px,6vw,72px); }}
    .cms-form {{ display: grid; gap: 18px; }}
    .cms-editor-head {{ display: grid; grid-template-columns: 1fr auto; gap: 18px; align-items: end; border-bottom: 1px solid var(--line); padding-bottom: 18px; }}
    .cms-editor-head h2 {{ font-size: clamp(38px,6vw,76px); }}
    .cms-fieldset {{ border: 1px solid var(--line); background: rgba(244,242,237,.035); padding: 14px; display: grid; gap: 14px; }}
    .cms-fieldset-title {{ display: flex; justify-content: space-between; gap: 16px; color: var(--paper); font-size: 14px; text-transform: uppercase; letter-spacing: .04em; }}
    .cms-fieldset-title span {{ color: var(--muted); }}
    .cms-advanced {{ border-color: rgba(244,242,237,.16); background: rgba(10,10,10,.28); }}
    .home-section-map {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }}
    .home-section-chip {{ border-radius: 8px; text-align: left; display: grid; gap: 4px; padding: 10px; background: rgba(244,242,237,.045); }}
    .home-section-chip strong {{ font-weight: 400; color: var(--paper); font-size: 14px; }}
    .home-section-chip span {{ color: var(--muted); font-size: 12px; }}
    .cms-actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .card {{ border-top: 1px solid var(--line); padding-top: 14px; position: relative; animation: riseIn 1.2s cubic-bezier(.16,1,.3,1) both; }}
    .card:nth-child(2) {{ animation-delay: .08s; }}
    .card:nth-child(3) {{ animation-delay: .16s; }}
    .card:nth-child(4) {{ animation-delay: .24s; }}
    .thumb-frame {{ aspect-ratio: 16 / 9; overflow: hidden; background: #151515; position: relative; }}
    .thumb {{ width: 100%; height: 100%; object-fit: cover; display: block; transform: scale(1.01); transition: transform .8s cubic-bezier(.16,1,.3,1), filter .8s; }}
    .thumb-video {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 0; transition: opacity .5s; }}
    .card:hover .thumb {{ transform: scale(1.055); filter: brightness(.68); }}
    .card:hover .thumb-video {{ opacity: 1; }}
    .meta {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--muted); font-size: 12px; text-transform: uppercase; margin: 12px 0 18px; }}
    .card h3 {{ font-weight: 400; font-size: clamp(28px, 4vw, 48px); letter-spacing: -.06em; margin: 0 0 6px; }}
    .detail-media {{ width: 100%; max-height: 76vh; object-fit: cover; background: #111; display: block; }}
    .reel-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--line); margin: 0 0 112px; }}
    .reel-card {{ min-height: 560px; background: #0a0a0a; display: grid; grid-template-rows: 1fr auto; overflow: hidden; position: relative; }}
    .reel-card video, .reel-card img, .reel-card iframe {{ width: 100%; height: 100%; object-fit: cover; display: block; border: 0; filter: saturate(.86) contrast(1.04); transform: scale(1.01); transition: transform .8s cubic-bezier(.16,1,.3,1), filter .8s; }}
    .reel-card:hover video, .reel-card:hover img, .reel-card:hover iframe {{ transform: scale(1.055); filter: saturate(1) contrast(1.08); }}
    .reel-meta {{ border-top: 1px solid var(--line); padding: 14px; display: grid; grid-template-columns: 1fr auto; gap: 14px; background: #0a0a0a; }}
    .reel-meta h3 {{ font-size: clamp(28px,4vw,52px); font-weight: 400; letter-spacing: -.07em; line-height: .92; margin: 0; }}
    .reel-meta p {{ margin: 6px 0 0; }}
    .split {{ display: grid; grid-template-columns: 1.2fr .8fr; gap: 32px; padding: 36px 0 80px; }}
    .sheet {{ display: grid; grid-template-columns: repeat(4, 1fr); border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); margin: 42px 0 0; }}
    .sheet-item {{ min-height: 120px; border-left: 1px solid var(--line); padding: 14px; }}
    .sheet-item:last-child {{ border-right: 1px solid var(--line); }}
    .case-copy {{ display: grid; grid-template-columns: 260px 1fr; gap: 40px; padding: 72px 0; border-top: 1px solid var(--line); }}
    .case-copy h3 {{ font-size: clamp(34px,4vw,62px); font-weight: 400; letter-spacing: -.065em; line-height: .94; margin: 0; }}
    .case-copy p {{ font-size: clamp(20px,2vw,30px); line-height: 1.08; letter-spacing: -.05em; margin: 0; }}
    .next-link {{ display: grid; grid-template-columns: 1fr auto; align-items: end; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 24px 0 34px; margin-bottom: 90px; }}
    .next-link h2 {{ font-size: clamp(60px,13vw,180px); }}
    .panel {{ border: 1px solid var(--line); background: rgba(244,242,237,.045); padding: 18px; backdrop-filter: blur(14px); }}
    .panel.glass {{ background: rgba(10,10,10,.52); border-color: rgba(244,242,237,.16); box-shadow: 0 20px 60px rgba(0,0,0,.24); }}
    .stat-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 1px; background: var(--line); margin-top: 22px; }}
    .stat {{ background: rgba(10,10,10,.88); padding: 18px; }}
    .stat b {{ display: block; font-weight: 400; font-size: clamp(32px, 5vw, 64px); letter-spacing: -.07em; line-height: .9; }}
    .admin-grid {{ display: grid; grid-template-columns: minmax(0, 1fr) 410px; gap: 24px; padding: 108px 0 70px; }}
    .admin-grid > aside {{ position: sticky; top: 24px; align-self: start; }}
    label {{ display: grid; gap: 7px; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }}
    input, textarea, select {{ width: 100%; border: 1px solid var(--line); background: rgba(244,242,237,.06); color: var(--paper); padding: 12px; border-radius: 8px; font: inherit; outline: none; }}
    input:focus, textarea:focus, select:focus {{ border-color: rgba(244,242,237,.34); background: rgba(244,242,237,.085); }}
    input:focus, textarea:focus {{ border-color: rgba(244,242,237,.36); background: rgba(244,242,237,.09); }}
    textarea {{ min-height: 110px; resize: vertical; }}
    form {{ display: grid; gap: 14px; }}
    .row {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }}
    .list {{ display: grid; gap: 12px; }}
    .item {{ display: grid; grid-template-columns: 120px 1fr auto; gap: 14px; align-items: center; border: 1px solid var(--line); padding: 10px; background: rgba(244,242,237,.035); }}
    .item img {{ width: 120px; aspect-ratio: 16 / 9; object-fit: cover; background: #151515; }}
    details {{ border: 1px solid var(--line); padding: 14px; margin-top: 12px; background: rgba(244,242,237,.035); }}
    summary {{ cursor: pointer; }}
    .danger {{ background: #34110c; border-color: rgba(219,57,3,.45); }}
    .login {{ min-height: 100vh; display: grid; place-items: center; padding: 24px; background: linear-gradient(180deg, rgba(10,10,10,.12), rgba(10,10,10,.85)), url('/assets/local/323795fc9c20f1ac.png') center/cover; }}
    .login .panel {{ width: min(440px, 100%); }}
    @keyframes riseIn {{ from {{ opacity: 0; transform: translateY(48px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    @keyframes wordIn {{ from {{ opacity: .001; filter: blur(14px); transform: translateY(30px); }} to {{ opacity: 1; filter: blur(0); transform: translateY(0); }} }}
    @keyframes posterIn {{ from {{ opacity: .001; transform: scale(1.08); }} to {{ opacity: .48; transform: scale(1.04); }} }}
    @media (prefers-reduced-motion: reduce) {{ *, *:before, *:after {{ animation: none !important; transition: none !important; }} }}
    @keyframes tickIn {{ from {{ opacity: .001; transform: translateY(120px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    @keyframes tickDown {{ from {{ opacity: .001; transform: translateY(-120px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    @media (max-width: 920px) {{ .topbar {{ bottom: 14px; }} .topbar .wrap {{ width: calc(100vw - 28px); justify-content: space-between; }} .hero-row, .grid, .split, .admin-grid, .row, .case-copy, .reel-grid, .cms-card-grid {{ grid-template-columns: 1fr; }} .reel-card {{ min-height: 420px; }} .copy-large {{ margin: 22px 0 0; text-align: left; }} .timeline, .sheet, .stat-grid {{ grid-template-columns: repeat(2, 1fr); }} .time-grid {{ grid-template-columns: repeat(3,1fr); }} .time-tick:nth-child(even) {{ display: none; }} .opening-copy {{ font-size: clamp(44px,13vw,78px); }} .work-row {{ grid-template-columns: 46px 1fr; gap: 10px; padding: 22px 0; }} .work-project, .work-year, .work-spec {{ grid-column: 2; }} .work-thumb {{ display: none; }} .item {{ grid-template-columns: 82px 1fr; }} .item form {{ grid-column: 1 / -1; }} h1 {{ font-size: clamp(62px, 24vw, 130px); }} }}
  </style>
  {extra_head}
</head>
<body>{body}</body>
</html>"""


def work_index_html():
    projects = public_projects()
    rows = []
    for index, project in enumerate(projects, 1):
        img = escape(project.get("image"))
        rows.append(f"""
        <a class="work-row" href="/work/{escape(project.get('slug'))}">
          <span class="work-num">{index:02d}</span>
          <strong class="work-title">{escape(project.get('title'))}</strong>
          <span class="work-project">{escape(project.get('project'))}</span>
          <span class="work-year">{escape(project.get('year'))}</span>
          <span class="work-spec">{escape(project.get('spec') or project.get('discipline'))}</span>
          <img class="work-thumb" src="{img}" alt="">
        </a>""")
    body = f"""
    <header class="topbar"><div class="wrap"><a class="brand" href="/">Anamorph</a><nav class="nav"><a class="pill" href="/">Home</a><a class="pill primary" href="/work">Work</a><a class="pill" href="/admin">CMS</a></nav></div></header>
    <main>
      <section class="opening">
        <div class="time-grid"><div class="time-tick"><span>00:00</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>00:30</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>01:00</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>01:30</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>02:00</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div></div>
        <div class="wrap">
          <h1 class="opening-copy"><span class="reveal-word">Everything</span> <span class="reveal-word">that</span> <span class="reveal-word">left</span><br><span class="reveal-word reveal-muted">this</span> <span class="reveal-word reveal-muted">room</span> <span class="reveal-word reveal-muted">cut</span> <span class="reveal-word reveal-muted">by</span> <span class="reveal-word reveal-muted">cut</span></h1>
          <div class="work-count"><b>{len(projects)} Films - 2025-2026</b><span>00:02:00:00</span></div>
        </div>
      </section>
      <section class="wrap section-head"><div><div class="eyebrow">(02) - All Work</div><h2>Selected Work</h2></div><a class="pill primary" href="/admin">Upload Project</a></section>
      <section class="wrap work-list">{''.join(rows) or '<p>No projects published yet.</p>'}</section>
      <section class="wrap next-link"><div><div class="eyebrow">(03) - Booking</div><h2>Let's roll</h2></div><a class="pill primary" href="/admin">Add Work</a></section>
    </main>"""
    return page_shell("Selected Work - Anamorph", body)


def reels_html():
    reels = public_reels()
    cards = []
    for index, reel in enumerate(reels, 1):
        media = media_html(reel, "card")
        cards.append(f"""
        <article class="reel-card">
          {media}
          <div class="reel-meta"><div><span class="eyebrow">{index:02d} - Reel</span><h3>{escape(reel.get('title'))}</h3><p>{escape(reel.get('caption') or reel.get('format'))}</p></div><span class="eyebrow">{escape(reel.get('duration', '00:15'))}</span></div>
        </article>""")
    body = f"""
    <header class="topbar"><div class="wrap"><a class="brand" href="/">Anamorph</a><nav class="nav"><a class="pill" href="/">Home</a><a class="pill" href="/work">Work</a><a class="pill primary" href="/reels">Reels</a><a class="pill" href="/admin">CMS</a></nav></div></header>
    <main>
      <section class="opening">
        <div class="time-grid"><div class="time-tick"><span>00:00</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>00:07</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>00:15</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>00:30</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>00:45</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div></div>
        <div class="wrap">
          <h1 class="opening-copy"><span class="reveal-word">Short-form</span> <span class="reveal-word">cuts</span><br><span class="reveal-word reveal-muted">built</span> <span class="reveal-word reveal-muted">to</span> <span class="reveal-word reveal-muted">hold</span> <span class="reveal-word reveal-muted">attention</span></h1>
          <div class="work-count"><b>{len(reels)} Reels - Motion CMS</b><span>00:00:45:00</span></div>
        </div>
      </section>
      <section class="wrap section-head"><div><div class="eyebrow">(01) - Reels</div><h2>Social Cuts</h2></div><a class="pill primary" href="/admin">Upload Reel</a></section>
      <section class="wrap reel-grid">{''.join(cards) or '<p>No reels published yet.</p>'}</section>
    </main>"""
    return page_shell("Reels - Anamorph", body)


def work_detail_template_html(project):
    if not WORK_DETAIL_TEMPLATE.exists():
        return ""
    projects = public_projects()
    next_item = next_project(projects, project.get("slug")) or {}
    output = WORK_DETAIL_TEMPLATE.read_text(errors="ignore")
    replacements = [
        ("Citadel", next_item.get("title", "Selected Work")),
        ("citadel", next_item.get("slug", "work")),
        ("Meridian — Anamorph™", f"{project.get('title') or 'Project'} — Anamorph™"),
        ("Meridian", project.get("title", "")),
        ("Brand Identity", project.get("discipline", "")),
        (">2026<", f">{escape(project.get('year', ''))}<"),
        ("Identity &amp; Launch Film", escape(project.get("project", ""))),
        ("Atlas Group", project.get("client", "")),
        ("RED Komodo 4K 24p", project.get("spec", "")),
        ("Master and Six Cutdowns", project.get("deliverables", "")),
        ("https://framerusercontent.com/assets/giTLgTG1Xb4gSWKMSMwml7NXZw.mp4", project.get("video") or project.get("image") or ""),
        ("https://www.youtube.com/watch?v=Sgxbx65IDeM", project.get("video", "")),
    ]
    for old, new in replacements:
        output = output.replace(old, str(new or ""))
    story = escape(project.get("story") or "A cinematic project shaped around pace, texture, and retention.")
    output = output.replace("A new identity needed a film that could carry it — sixty days from first board to launch, and a name the market hadn’t heard yet.", story)
    output = output.replace("We cut to the grade, not around it. Two-frame holds on the wordmark, hard cuts on the beat, nothing that lingers. The launch version ran 02:14; the boardroom sat through it twice.", "We cut to the grade, not around it. Holds, hard cuts, texture, and rhythm stay locked to the idea.")
    output = output.replace("Lifted blacks and one warm accent pulled from the wordmark. The whole film sits inside the brand palette before the logo ever appears.", "Lifted blacks, restrained contrast, and one warm accent keep the whole film inside the brand palette.")
    output = output.replace("The film opened the launch event and ran paid for six weeks. Average watch time held above ninety per cent.", "The film was finished for launch with social cutdowns, title work, and delivery-ready masters.")
    return output


def project_html(project):
    templated = work_detail_template_html(project)
    if templated:
        return templated
    projects = public_projects()
    next_item = next_project(projects, project.get("slug")) or {}
    hero_media = media_html(project, "hero")
    media = media_html(project, "detail")
    body = f"""
    <header class="topbar"><div class="wrap"><a class="brand" href="/">Anamorph</a><nav class="nav"><a class="pill primary" href="/work">Work</a><a class="pill" href="/">Home</a><a class="pill" href="/admin">CMS</a></nav></div></header>
    <main>
      <section class="hero compact">
        <div class="hero-media">{hero_media}</div>
        <div class="wrap hero-content">
          <div class="eyebrow">{escape(project.get('discipline'))}</div>
          <h1>{escape(project.get('title'))}</h1>
          <div class="timeline"><div class="tick">00:00<span>+</span></div><div class="tick">00:30<span>+</span></div><div class="tick">01:00<span>+</span></div><div class="tick">01:30<span>+</span></div><div class="tick">02:00<span>+</span></div></div>
        </div>
      </section>
      <section class="wrap">
        <div class="section-head"><div><div class="eyebrow">(01) - The Sheet</div><h2>+</h2></div><span class="eyebrow">00:01:00:00</span></div>
        <div class="sheet"><div class="sheet-item"><p class="eyebrow">Client</p><p>{escape(project.get('client'))}</p></div><div class="sheet-item"><p class="eyebrow">Project</p><p>{escape(project.get('project'))}</p></div><div class="sheet-item"><p class="eyebrow">Spec</p><p>{escape(project.get('spec'))}</p></div><div class="sheet-item"><p class="eyebrow">Deliverables</p><p>{escape(project.get('deliverables'))}</p></div></div>
      </section>
      <section class="wrap">
        <div class="section-head"><div><div class="eyebrow">(02) - The Master</div><h2>00:02:00:00</h2></div></div>
        {media}
        <div class="work-count"><b>ANAMORPH_{escape(project.get('title'))}_MASTER.MP4</b><span>Editor - Noah Reyes</span></div>
      </section>
      <section class="wrap">
        <div class="case-copy"><h3>The Brief</h3><p>{escape(project.get('story') or 'A new identity needed a film that could carry it from first board to launch.')}</p></div>
        <div class="case-copy"><h3>The Cut</h3><p>We cut to the grade, not around it. Holds, hard cuts, texture, and rhythm stay locked to the idea.</p></div>
        <div class="case-copy"><h3>The Grade</h3><p>Lifted blacks, restrained contrast, and one warm accent keep the whole film inside the brand palette.</p></div>
        <div class="case-copy"><h3>The Result</h3><p>The film was finished for launch with social cutdowns, title work, and delivery-ready masters.</p></div>
        <div class="stat-grid"><div class="stat"><b>01</b><p>24H Reply Time</p></div><div class="stat"><b>02</b><p>Revision Rounds</p></div><div class="stat"><b>98%</b><p>On-time Delivery</p></div><div class="stat"><b>5D</b><p>First Cut</p></div></div>
      </section>
      <section class="wrap next-link"><div><div class="eyebrow">Next screening</div><h2>{escape(next_item.get('title', 'Selected Work'))}</h2></div><a class="pill primary" href="{('/work/' + escape(next_item.get('slug'))) if next_item.get('slug') else '/work'}">Next</a></section>
    </main>"""
    return page_shell(f"{project.get('title')} - Anamorph", body)


def login_html(error=""):
    message = f"<p style='color:#ff9b7d'>{escape(error)}</p>" if error else ""
    body = f"""
    <main class="login">
      <section class="panel glass">
        <div class="brand">Anamorph</div>
        <p class="eyebrow">(CMS) - Login</p>
        <h2>Studio Access</h2>
        <p>Upload project posters, reels, and case-study copy into the local portfolio.</p>
        {message}
        <form method="post" action="/login">
          <label>Username<input name="username" autocomplete="username" required></label>
          <label>Password<input type="password" name="password" autocomplete="current-password" required></label>
          <input type="submit" value="Login">
        </form>
      </section>
    </main>"""
    return page_shell("CMS Login", body)


def project_form(project=None):
    p = project or {}
    checked = "checked" if p.get("published", True) else ""
    return f"""
    <form method="post" action="/admin/projects" enctype="multipart/form-data">
      <input type="hidden" name="id" value="{escape(p.get('id', ''))}">
      <div class="row">
        <label>Title<input name="title" value="{escape(p.get('title', ''))}" required></label>
        <label>Slug<input name="slug" value="{escape(p.get('slug', ''))}" placeholder="auto from title"></label>
      </div>
      <div class="row">
        <label>Eyebrow<input name="eyebrow" value="{escape(p.get('eyebrow', '(01) - Selected Work'))}"></label>
        <label>Year<input name="year" value="{escape(p.get('year', '2026'))}"></label>
      </div>
      <div class="row">
        <label>Project<input name="project" value="{escape(p.get('project', ''))}"></label>
        <label>Discipline<input name="discipline" value="{escape(p.get('discipline', ''))}"></label>
      </div>
      <div class="row">
        <label>Client<input name="client" value="{escape(p.get('client', ''))}"></label>
        <label>Spec<input name="spec" value="{escape(p.get('spec', ''))}"></label>
      </div>
      <label>Deliverables<input name="deliverables" value="{escape(p.get('deliverables', ''))}"></label>
      <label>Story<textarea name="story">{escape(p.get('story', ''))}</textarea></label>
      <div class="row">
        <label>Poster image<input type="file" name="image" accept="image/*"></label>
        <label>Video file<input type="file" name="video" accept="video/*"></label>
      </div>
      <div class="row">
        <label>Google Drive image URL<input name="image_url" value="{escape(p.get('image', ''))}" placeholder="Paste Drive image share link"></label>
        <label>YouTube video URL<input name="video_url" value="{escape(p.get('video', ''))}" placeholder="Paste YouTube link"></label>
      </div>
      <label><span><input type="checkbox" name="published" {checked} style="width:auto"> Published</span></label>
      <input type="submit" value="{escape('Update project' if project else 'Create project')}">
    </form>"""


def reel_form(reel=None):
    r = reel or {}
    checked = "checked" if r.get("published", True) else ""
    return f"""
    <form method="post" action="/admin/reels" enctype="multipart/form-data">
      <input type="hidden" name="id" value="{escape(r.get('id', ''))}">
      <div class="row">
        <label>Title<input name="title" value="{escape(r.get('title', ''))}" required></label>
        <label>Slug<input name="slug" value="{escape(r.get('slug', ''))}" placeholder="auto from title"></label>
      </div>
      <div class="row">
        <label>Duration<input name="duration" value="{escape(r.get('duration', '00:15'))}"></label>
        <label>Format<input name="format" value="{escape(r.get('format', '9:16 Reel'))}"></label>
      </div>
      <label>Caption<textarea name="caption">{escape(r.get('caption', ''))}</textarea></label>
      <div class="row">
        <label>Poster image<input type="file" name="image" accept="image/*"></label>
        <label>Video file<input type="file" name="video" accept="video/*"></label>
      </div>
      <div class="row">
        <label>Google Drive image URL<input name="image_url" value="{escape(r.get('image', ''))}" placeholder="Paste Drive image share link"></label>
        <label>YouTube video URL<input name="video_url" value="{escape(r.get('video', ''))}" placeholder="Paste YouTube link"></label>
      </div>
      <label><span><input type="checkbox" name="published" {checked} style="width:auto"> Published</span></label>
      <input type="submit" value="{escape('Update reel' if reel else 'Create reel')}">
    </form>"""


def home_form(home=None):
    h = home or {}
    return f"""
    <form class="cms-form" method="post" action="/admin/home" enctype="multipart/form-data">
      <div class="cms-editor-head">
        <div>
          <div class="eyebrow">Guided home editor</div>
          <h2>Text & Images</h2>
          <p>Scan the homepage, choose a section, then pick the exact text or image from that section.</p>
        </div>
        <button class="primary" type="button" data-scan-home>Scan Homepage</button>
      </div>
      <div class="cms-fieldset">
        <div class="cms-fieldset-title"><span>00</span><strong>Homepage sections</strong></div>
        <label>Filter by section<select id="homeSectionFilter"><option value="">All homepage sections</option></select></label>
        <div id="homeSectionMap" class="home-section-map"></div>
      </div>
      <datalist id="homeTextOptions"></datalist>
      <datalist id="homeImageOptions"></datalist>
      <div class="cms-fieldset">
        <div class="cms-fieldset-title"><span>01</span><strong>Change one text</strong></div>
        <div class="row">
          <label>Current homepage text<input name="text_from" list="homeTextOptions" placeholder="Choose or paste current text"></label>
          <label>New text<input name="text_to" placeholder="Type replacement text"></label>
        </div>
      </div>
      <div class="cms-fieldset">
        <div class="cms-fieldset-title"><span>02</span><strong>Change one image</strong></div>
        <div class="row">
          <label>Current image URL<input name="image_target" list="homeImageOptions" placeholder="Choose or paste current image URL"></label>
          <label>New Google Drive image URL<input name="image_url" placeholder="Paste Drive image share link"></label>
        </div>
        <label>Or upload replacement image<input type="file" name="image" accept="image/*"></label>
      </div>
      <details class="cms-advanced" open>
        <summary>Advanced saved replacements</summary>
        <label>All text replacements<textarea name="text_replacements" placeholder="Anamorph => Your Brand&#10;Book a call => Start a project">{escape(pairs_to_text(h.get('text_replacements', [])))}</textarea></label>
        <label>All image replacements<textarea name="image_replacements" placeholder="/assets/local/323795fc9c20f1ac.png => https://drive.google.com/file/d/.../view">{escape(pairs_to_text(h.get('image_replacements', [])))}</textarea></label>
      </details>
      <input type="submit" value="Update home page">
      <script>
      (function() {{
        var state = {{ texts: [], images: [], sections: [] }};
        function clean(value) {{ return (value || '').replace(/\s+/g, ' ').trim(); }}
        function sectionName(el) {{
          var section = el && el.closest && el.closest('section,[data-framer-name],footer,header');
          if (!section) return 'Global';
          return section.getAttribute('data-framer-name') || section.id || section.tagName || 'Global';
        }}
        function uniqueItems(items) {{
          var seen = {{}};
          return items.filter(function(item) {{
            var key = item.section + '::' + item.value;
            if (seen[key] || !item.value) return false;
            seen[key] = 1;
            return true;
          }}).slice(0, 500);
        }}
        function filtered(items) {{
          var section = (document.getElementById('homeSectionFilter') || {{}}).value || '';
          return section ? items.filter(function(item) {{ return item.section === section; }}) : items;
        }}
        function fill(list, items) {{
          var el = document.getElementById(list);
          if (!el) return;
          el.innerHTML = '';
          filtered(items).forEach(function(item) {{
            var option = document.createElement('option');
            option.value = item.value;
            option.label = item.section;
            el.appendChild(option);
          }});
        }}
        function refresh() {{
          fill('homeTextOptions', state.texts);
          fill('homeImageOptions', state.images);
        }}
        function renderSections() {{
          var select = document.getElementById('homeSectionFilter');
          var map = document.getElementById('homeSectionMap');
          if (!select || !map) return;
          select.innerHTML = '<option value="">All homepage sections</option>';
          state.sections.forEach(function(section) {{
            var option = document.createElement('option');
            option.value = section;
            option.textContent = section;
            select.appendChild(option);
          }});
          map.innerHTML = '';
          state.sections.forEach(function(section) {{
            var textCount = state.texts.filter(function(item) {{ return item.section === section; }}).length;
            var imageCount = state.images.filter(function(item) {{ return item.section === section; }}).length;
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'home-section-chip';
            button.innerHTML = '<strong>' + section + '</strong><span>' + textCount + ' text / ' + imageCount + ' image</span>';
            button.addEventListener('click', function() {{ select.value = section; refresh(); }});
            map.appendChild(button);
          }});
        }}
        async function scan() {{
          try {{
            var res = await fetch('/', {{ cache: 'no-store' }});
            var html = await res.text();
            var doc = new DOMParser().parseFromString(html, 'text/html');
            var blocked = {{ SCRIPT: 1, STYLE: 1, NOSCRIPT: 1 }};
            var texts = [];
            var walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, {{
              acceptNode: function(node) {{
                var parent = node.parentElement;
                if (!parent || blocked[parent.tagName]) return NodeFilter.FILTER_REJECT;
                var text = clean(node.nodeValue);
                return text.length > 1 && text.length < 220 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
              }}
            }});
            while (walker.nextNode()) texts.push({{ value: clean(walker.currentNode.nodeValue), section: sectionName(walker.currentNode.parentElement) }});
            var images = [];
            doc.querySelectorAll('img').forEach(function(img) {{
              var section = sectionName(img);
              var src = img.getAttribute('src');
              if (src) images.push({{ value: src, section: section }});
              (img.getAttribute('srcset') || '').split(',').forEach(function(part) {{
                var first = part.trim().split(/\s+/)[0];
                if (first) images.push({{ value: first, section: section }});
              }});
            }});
            state.texts = uniqueItems(texts);
            state.images = uniqueItems(images);
            state.sections = Array.from(new Set(state.texts.concat(state.images).map(function(item) {{ return item.section; }}))).filter(Boolean);
            renderSections();
            refresh();
          }} catch (e) {{}}
        }}
        var filter = document.getElementById('homeSectionFilter');
        if (filter) filter.addEventListener('change', refresh);
        var scanButton = document.querySelector('[data-scan-home]');
        if (scanButton) scanButton.addEventListener('click', scan);
        scan();
      }})();
      </script>
    </form>"""


def admin_nav(active=""):
    def pill(href, label, key):
        primary = " primary" if active == key else ""
        return f'<a class="pill{primary}" href="{href}">{label}</a>'
    return f"""<header class="topbar"><div class="wrap"><a class="brand" href="/admin">CMS</a><nav class="nav">{pill('/admin/home', 'Home CMS', 'home')}{pill('/admin/work', 'Work CMS', 'work')}{pill('/admin/reels', 'Reels CMS', 'reels')}<a class="pill" href="/">Site</a><form method="post" action="/logout"><button>Logout</button></form></nav></div></header>"""


def admin_html():
    data = load_cms()
    body = f"""
    {admin_nav()}
    <main class="wrap">
      <section class="opening">
        <div class="time-grid"><div class="time-tick"><span>HOME</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>WORK</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>REELS</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div></div>
        <div class="wrap">
          <h1 class="opening-copy"><span class="reveal-word">CMS</span> <span class="reveal-word">Control</span><br><span class="reveal-word reveal-muted">choose</span> <span class="reveal-word reveal-muted">a</span> <span class="reveal-word reveal-muted">page</span></h1>
          <div class="work-count"><b>{len(data.get('projects', []))} Projects - {len(data.get('reels', []))} Reels</b><span>ANAMORPH CMS</span></div>
        </div>
      </section>
      <section class="section-head"><div><div class="eyebrow">(CMS) - Sections</div><h2>Edit Pages</h2></div></section>
      <section class="cms-card-grid">
        <a class="cms-card" href="/admin/home"><div><div class="eyebrow">Home Page</div><h2>Home CMS</h2><p>Change homepage text, images, and original Framer content replacements.</p></div><span class="pill primary">Edit Home</span></a>
        <a class="cms-card" href="/admin/work"><div><div class="eyebrow">Projects</div><h2>Work CMS</h2><p>Add, edit, publish, and delete project pages.</p></div><span class="pill primary">Edit Work</span></a>
        <a class="cms-card" href="/admin/reels"><div><div class="eyebrow">Homepage Videos</div><h2>Reels CMS</h2><p>Change the first three homepage reel videos and the reels page.</p></div><span class="pill primary">Edit Reels</span></a>
      </section>
    </main>"""
    return page_shell("Anamorph CMS", body)


def admin_home_html():
    data = load_cms()
    body = f"""
    {admin_nav('home')}
    <main class="wrap admin-grid">
      <section>
        <div class="eyebrow">(CMS) - Home Page</div>
        <h2>Home Content</h2>
        <p>Change home page text and images while the original Framer design, layout, and animation stay the same.</p>
        <div class="panel">{home_form(data.get('home', {}))}</div>
      </section>
      <aside class="panel glass">
        <div class="eyebrow">(Preview)</div>
        <h2>Home</h2>
        <p>Use text replacement rows for copy and image replacement rows for visual assets.</p>
        <a class="pill primary" href="/">Open Home</a>
        <a class="pill" href="/#reels">Home Reels</a>
      </aside>
    </main>"""
    return page_shell("Home CMS - Anamorph", body)


def admin_work_html():
    data = load_cms()
    items = []
    for p in data["projects"]:
        status = "Published" if p.get("published", True) else "Draft"
        items.append(f"""
        <div class="item">
          <img src="{escape(p.get('image'))}" alt="">
          <div><strong>{escape(p.get('title'))}</strong><p>/{escape(p.get('slug'))} - {escape(p.get('year'))} - {status}</p><a class="pill" href="/work/{escape(p.get('slug'))}">Preview</a></div>
          <form method="post" action="/admin/projects/delete" onsubmit="return confirm('Delete this project?')">
            <input type="hidden" name="id" value="{escape(p.get('id'))}">
            <button class="danger">Delete</button>
          </form>
        </div>""")
    edit_forms = "".join(f"<details><summary>Edit {escape(p.get('title'))}</summary>{project_form(p)}</details>" for p in data["projects"])
    body = f"""
    {admin_nav('work')}
    <main class="wrap admin-grid">
      <section>
        <div class="eyebrow">(CMS) - Work Page</div>
        <h2>Projects</h2>
        <p>Change project pages, posters, videos, copy, and publish state.</p>
        <div class="list">{''.join(items) or '<p>No projects yet.</p>'}</div>
        <div style="margin-top:24px">{edit_forms}</div>
      </section>
      <aside class="panel glass">
        <div class="eyebrow">(Upload) - New Case</div>
        <h2>Project</h2>
        {project_form()}
      </aside>
    </main>"""
    return page_shell("Work CMS - Anamorph", body)


def admin_reels_html():
    data = load_cms()
    reel_items = []
    for r in data.get("reels", []):
        status = "Published" if r.get("published", True) else "Draft"
        reel_items.append(f"""
        <div class="item">
          <img src="{escape(r.get('image'))}" alt="">
          <div><strong>{escape(r.get('title'))}</strong><p>/{escape(r.get('slug'))} - {escape(r.get('duration'))} - {status}</p><a class="pill" href="/reels">Preview</a></div>
          <form method="post" action="/admin/reels/delete" onsubmit="return confirm('Delete this reel?')">
            <input type="hidden" name="id" value="{escape(r.get('id'))}">
            <button class="danger">Delete</button>
          </form>
        </div>""")
    reel_edit_forms = "".join(f"<details><summary>Edit {escape(r.get('title'))}</summary>{reel_form(r)}</details>" for r in data.get("reels", []))
    body = f"""
    {admin_nav('reels')}
    <main class="wrap admin-grid">
      <section>
        <div class="eyebrow">(CMS) - Home Reels</div>
        <h2>Homepage Videos</h2>
        <p>These first three published reels replace only the videos inside the existing home page reels section. The Framer design stays the same.</p>
        <div class="list">{''.join(reel_items) or '<p>No reels yet.</p>'}</div>
        <div style="margin-top:24px">{reel_edit_forms}</div>
      </section>
      <aside class="panel glass">
        <div class="eyebrow">(Upload) - Home Reel Video</div>
        <h2>Reel Slot</h2>
        {reel_form()}
        <div style="height:20px"></div>
        <a class="pill primary" href="/reels">Preview Reels</a>
        <a class="pill" href="/#reels">Preview Home</a>
      </aside>
    </main>"""
    return page_shell("Reels CMS - Anamorph", body)


def read_field(form, name, default=""):
    field = form.getfirst(name)
    return str(field if field is not None else default).strip()


def save_upload(field, kind):
    if field is None or not getattr(field, "filename", ""):
        return ""
    filename = Path(field.filename).name
    ext = Path(filename).suffix.lower()
    allowed = ALLOWED_IMAGE_EXT if kind == "image" else ALLOWED_VIDEO_EXT
    if ext not in allowed:
        raise ValueError(f"{kind} file type not allowed")
    target_dir = IMAGE_DIR if kind == "image" else VIDEO_DIR
    target = target_dir / f"{int(time.time())}-{uuid.uuid4().hex[:10]}{ext}"
    with target.open("wb") as out:
        shutil.copyfileobj(field.file, out)
    return "/" + target.relative_to(ROOT).as_posix()


class CMSHandler(SimpleHTTPRequestHandler):
    server_version = "AnamorphCMS/1.0"

    def translate_path(self, path):
        parsed = urlparse(path)
        clean = unquote(parsed.path).lstrip("/")
        return str((ROOT / clean).resolve())

    def is_logged_in(self):
        cookie = SimpleCookie(self.headers.get("Cookie"))
        return valid_session(cookie.get("cms_session").value if cookie.get("cms_session") else "")

    def send_html(self, body, status=HTTPStatus.OK):
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, data, status=HTTPStatus.OK):
        payload = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def redirect(self, location):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/login":
            return self.send_html(login_html())
        if path == "/admin":
            if not self.is_logged_in():
                return self.redirect("/login")
            return self.send_html(admin_html())
        if path == "/admin/home":
            if not self.is_logged_in():
                return self.redirect("/login")
            return self.send_html(admin_home_html())
        if path == "/admin/work":
            if not self.is_logged_in():
                return self.redirect("/login")
            return self.send_html(admin_work_html())
        if path == "/admin/reels":
            if not self.is_logged_in():
                return self.redirect("/login")
            return self.send_html(admin_reels_html())
        if path == "/api/projects":
            return self.send_json({"projects": public_projects()})
        if path == "/api/reels":
            return self.send_json({"reels": public_reels()})
        if path == "/api/home":
            return self.send_json({"home": public_home()})
        if path == "/work":
            return self.send_html(work_index_html())
        if path == "/reels":
            return self.send_html(reels_html())
        if path.startswith("/work/"):
            slug = path.split("/", 2)[2]
            project = find_project(slug)
            if project:
                return self.send_html(project_html(project))
            return self.send_error(HTTPStatus.NOT_FOUND, "Project not found")
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/login":
            length = int(self.headers.get("Content-Length", "0"))
            values = parse_qs(self.rfile.read(length).decode())
            username = values.get("username", [""])[0]
            password = values.get("password", [""])[0]
            if hmac.compare_digest(username, CMS_USER) and hmac.compare_digest(password, CMS_PASSWORD):
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/admin")
                self.send_header("Set-Cookie", f"cms_session={signed_session_value()}; HttpOnly; SameSite=Lax; Path=/")
                self.end_headers()
                return
            return self.send_html(login_html("Wrong username or password."), HTTPStatus.UNAUTHORIZED)
        if path == "/logout":
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", "cms_session=; Max-Age=0; Path=/")
            self.end_headers()
            return
        if not self.is_logged_in():
            return self.redirect("/login")
        if path == "/admin/projects":
            return self.save_project()
        if path == "/admin/home":
            return self.save_home()
        if path == "/admin/projects/delete":
            return self.delete_project()
        if path == "/admin/reels":
            return self.save_reel()
        if path == "/admin/reels/delete":
            return self.delete_reel()
        return self.send_error(HTTPStatus.NOT_FOUND)

    def multipart_form(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_UPLOAD_BYTES:
            raise ValueError("Upload is too large")
        return cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": self.headers.get("Content-Type"),
            "CONTENT_LENGTH": str(length)
        })

    def save_project(self):
        try:
            form = self.multipart_form()
            data = load_cms()
            project_id = read_field(form, "id") or uuid.uuid4().hex
            existing = next((p for p in data["projects"] if p.get("id") == project_id), None)
            project = dict(existing or {"id": project_id, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            title = read_field(form, "title", project.get("title", "Untitled"))
            slug = read_field(form, "slug") or title
            project.update({
                "title": title,
                "slug": unique_slug(data, "projects", slug, project_id),
                "eyebrow": read_field(form, "eyebrow", project.get("eyebrow", "")),
                "year": read_field(form, "year", project.get("year", "")),
                "project": read_field(form, "project", project.get("project", "")),
                "discipline": read_field(form, "discipline", project.get("discipline", "")),
                "client": read_field(form, "client", project.get("client", "")),
                "spec": read_field(form, "spec", project.get("spec", "")),
                "deliverables": read_field(form, "deliverables", project.get("deliverables", "")),
                "story": read_field(form, "story", project.get("story", "")),
                "published": form.getfirst("published") == "on",
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            })
            image = save_upload(form["image"], "image") if "image" in form else ""
            video = save_upload(form["video"], "video") if "video" in form else ""
            image_url = drive_image(read_field(form, "image_url"))
            video_url = read_field(form, "video_url")
            if image:
                project["image"] = image
            elif image_url:
                project["image"] = image_url
            if video:
                project["video"] = video
            elif video_url:
                project["video"] = video_url
            if not project.get("image"):
                project["image"] = "/assets/local/4408de2269c8641c.jpg"
            if existing:
                existing.update(project)
            else:
                data["projects"].insert(0, project)
            save_cms(data)
            return self.redirect("/admin/work")
        except Exception as exc:
            return self.send_html(page_shell("CMS Error", f"<main class='login'><section class='panel'><h1>Error</h1><p>{escape(exc)}</p><a class='pill' href='/admin'>Back</a></section></main>"), HTTPStatus.BAD_REQUEST)

    def save_home(self):
        try:
            form = self.multipart_form()
            data = load_cms()
            home = {
                "text_replacements": text_to_pairs(read_field(form, "text_replacements")),
                "image_replacements": text_to_pairs(read_field(form, "image_replacements")),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            append_pair(home["text_replacements"], read_field(form, "text_from"), read_field(form, "text_to"))
            target = read_field(form, "image_target")
            image = save_upload(form["image"], "image") if "image" in form else ""
            image_url = drive_image(read_field(form, "image_url"))
            replacement = image or image_url
            if target and replacement:
                home["image_replacements"].append({"from": target, "to": replacement})
            data["home"] = home
            save_cms(data)
            return self.redirect("/admin/home")
        except Exception as exc:
            return self.send_html(page_shell("CMS Error", f"<main class='login'><section class='panel'><h1>Error</h1><p>{escape(exc)}</p><a class='pill' href='/admin'>Back</a></section></main>"), HTTPStatus.BAD_REQUEST)

    def delete_project(self):
        length = int(self.headers.get("Content-Length", "0"))
        values = parse_qs(self.rfile.read(length).decode())
        project_id = values.get("id", [""])[0]
        data = load_cms()
        data["projects"] = [p for p in data["projects"] if p.get("id") != project_id]
        save_cms(data)
        return self.redirect("/admin/work")

    def save_reel(self):
        try:
            form = self.multipart_form()
            data = load_cms()
            data.setdefault("reels", [])
            reel_id = read_field(form, "id") or uuid.uuid4().hex
            existing = next((r for r in data["reels"] if r.get("id") == reel_id), None)
            reel = dict(existing or {"id": reel_id, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            title = read_field(form, "title", reel.get("title", "Untitled Reel"))
            slug = read_field(form, "slug") or title
            reel.update({
                "title": title,
                "slug": unique_slug(data, "reels", slug, reel_id),
                "duration": read_field(form, "duration", reel.get("duration", "")),
                "format": read_field(form, "format", reel.get("format", "")),
                "caption": read_field(form, "caption", reel.get("caption", "")),
                "published": form.getfirst("published") == "on",
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            })
            image = save_upload(form["image"], "image") if "image" in form else ""
            video = save_upload(form["video"], "video") if "video" in form else ""
            image_url = drive_image(read_field(form, "image_url"))
            video_url = read_field(form, "video_url")
            if image:
                reel["image"] = image
            elif image_url:
                reel["image"] = image_url
            if video:
                reel["video"] = video
            elif video_url:
                reel["video"] = video_url
            if not reel.get("image"):
                reel["image"] = "/assets/local/323795fc9c20f1ac.png"
            if existing:
                existing.update(reel)
            else:
                data["reels"].insert(0, reel)
            save_cms(data)
            return self.redirect("/admin/reels")
        except Exception as exc:
            return self.send_html(page_shell("CMS Error", f"<main class='login'><section class='panel'><h1>Error</h1><p>{escape(exc)}</p><a class='pill' href='/admin'>Back</a></section></main>"), HTTPStatus.BAD_REQUEST)

    def delete_reel(self):
        length = int(self.headers.get("Content-Length", "0"))
        values = parse_qs(self.rfile.read(length).decode())
        reel_id = values.get("id", [""])[0]
        data = load_cms()
        data["reels"] = [r for r in data.get("reels", []) if r.get("id") != reel_id]
        save_cms(data)
        return self.redirect("/admin/reels")


def main():
    ensure_storage()
    port = int(os.environ.get("PORT", "56540"))
    os.chdir(ROOT)
    print(f"Anamorph CMS running on http://localhost:{port}")
    print(f"Login: {CMS_USER} / {CMS_PASSWORD}")
    ThreadingHTTPServer(("", port), CMSHandler).serve_forever()


if __name__ == "__main__":
    main()
