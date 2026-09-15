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
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data" / "cms.json"
SECRET_FILE = ROOT / "data" / ".cms_secret"
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
    return data


def save_cms(data):
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(DATA_FILE)


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


def unique_slug(data, base, current_id=None):
    base = slugify(base)
    existing = {p.get("slug") for p in data["projects"] if p.get("id") != current_id}
    if base not in existing:
        return base
    i = 2
    while f"{base}-{i}" in existing:
        i += 1
    return f"{base}-{i}"


def public_projects():
    projects = [p for p in load_cms()["projects"] if p.get("published", True)]
    return sorted(projects, key=lambda p: p.get("created_at", ""), reverse=True)


def find_project(slug):
    for project in public_projects():
        if project.get("slug") == slug:
            return project
    return None


def escape(value):
    return html.escape(str(value or ""), quote=True)


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
    .topbar {{ position: fixed; left: 0; right: 0; top: 0; z-index: 10; backdrop-filter: blur(18px); background: rgba(10,10,10,.58); border-bottom: 1px solid var(--line); }}
    .topbar .wrap {{ min-height: 68px; display: flex; align-items: center; justify-content: space-between; gap: 18px; }}
    .brand {{ font-size: clamp(30px, 4vw, 58px); letter-spacing: -.08em; line-height: .86; }}
    .nav {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
    .pill, button, input[type=submit] {{ border: 1px solid var(--line); background: rgba(244,242,237,.06); color: var(--paper); border-radius: 999px; padding: 10px 14px; font: inherit; cursor: pointer; transition: transform .35s cubic-bezier(.16,1,.3,1), background .35s, border-color .35s; }}
    .pill:hover, button:hover, input[type=submit]:hover {{ transform: translateY(-1px); background: rgba(244,242,237,.12); border-color: rgba(244,242,237,.22); }}
    .pill.primary, input[type=submit], button.primary {{ background: var(--accent); border-color: var(--accent); }}
    .hero {{ min-height: 86vh; display: grid; align-items: end; padding: 120px 0 34px; border-bottom: 1px solid var(--line); position: relative; overflow: hidden; }}
    .hero.compact {{ min-height: 50vh; }}
    .hero-media {{ position: absolute; inset: 0; opacity: .48; transform: scale(1.04); animation: posterIn 2.4s cubic-bezier(.16,1,.3,1) forwards; }}
    .hero-media img, .hero-media video {{ width: 100%; height: 100%; object-fit: cover; display: block; filter: saturate(.82) contrast(1.08); }}
    .hero-media:after {{ content: ""; position: absolute; inset: 0; background: radial-gradient(circle at 50% 45%, transparent 0 36%, rgba(10,10,10,.5) 74%), linear-gradient(180deg, rgba(10,10,10,.22), rgba(10,10,10,.92)); }}
    .hero-content {{ position: relative; z-index: 1; }}
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
    .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; padding: 28px 0 90px; }}
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
    .split {{ display: grid; grid-template-columns: 1.2fr .8fr; gap: 32px; padding: 36px 0 80px; }}
    .panel {{ border: 1px solid var(--line); background: rgba(244,242,237,.045); padding: 18px; backdrop-filter: blur(14px); }}
    .panel.glass {{ background: rgba(10,10,10,.52); border-color: rgba(244,242,237,.16); box-shadow: 0 20px 60px rgba(0,0,0,.24); }}
    .stat-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 1px; background: var(--line); margin-top: 22px; }}
    .stat {{ background: rgba(10,10,10,.88); padding: 18px; }}
    .stat b {{ display: block; font-weight: 400; font-size: clamp(32px, 5vw, 64px); letter-spacing: -.07em; line-height: .9; }}
    .admin-grid {{ display: grid; grid-template-columns: minmax(0, 1fr) 390px; gap: 24px; padding: 108px 0 70px; }}
    label {{ display: grid; gap: 7px; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }}
    input, textarea, select {{ width: 100%; border: 1px solid var(--line); background: rgba(244,242,237,.06); color: var(--paper); padding: 12px; border-radius: 8px; font: inherit; outline: none; }}
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
    @keyframes posterIn {{ from {{ opacity: .001; transform: scale(1.08); }} to {{ opacity: .48; transform: scale(1.04); }} }}
    @media (prefers-reduced-motion: reduce) {{ *, *:before, *:after {{ animation: none !important; transition: none !important; }} }}
    @media (max-width: 920px) {{ .hero-row, .grid, .split, .admin-grid, .row {{ grid-template-columns: 1fr; }} .copy-large {{ margin: 22px 0 0; text-align: left; }} .timeline {{ grid-template-columns: repeat(3, 1fr); }} .item {{ grid-template-columns: 82px 1fr; }} .item form {{ grid-column: 1 / -1; }} h1 {{ font-size: clamp(62px, 24vw, 130px); }} }}
  </style>
  {extra_head}
</head>
<body>{body}</body>
</html>"""


def work_index_html():
    projects = public_projects()
    hero = projects[0] if projects else {}
    hero_image = escape(hero.get("image", "/assets/local/323795fc9c20f1ac.png"))
    hero_video = escape(hero.get("video", ""))
    hero_media = f'<video src="{hero_video}" poster="{hero_image}" autoplay muted loop playsinline></video>' if hero_video else f'<img src="{hero_image}" alt="">'
    cards = []
    for index, project in enumerate(projects, 1):
        img = escape(project.get("image"))
        vid = escape(project.get("video"))
        video = f'<video class="thumb-video" src="{vid}" muted loop playsinline></video>' if vid else ""
        cards.append(f"""
        <a class="card" href="/work/{escape(project.get('slug'))}">
          <div class="thumb-frame"><img class="thumb" src="{img}" alt="{escape(project.get('title'))}">{video}</div>
          <div class="meta"><span>({index:02d}) - Selected Work</span><span>{escape(project.get('year'))}</span></div>
          <h3>{escape(project.get('title'))}</h3>
          <p>{escape(project.get('project'))} - {escape(project.get('discipline'))}</p>
        </a>""")
    body = f"""
    <header class="topbar"><div class="wrap"><a class="brand" href="/">Anamorph</a><nav class="nav"><a class="pill" href="/">Home</a><a class="pill" href="/#reels">Reels</a><a class="pill primary" href="/admin">CMS</a></nav></div></header>
    <main>
      <section class="hero">
        <div class="hero-media">{hero_media}</div>
        <div class="wrap hero-content">
          <div class="hero-row">
            <div><div class="eyebrow">(01) - Services</div><div class="services"><span>Long-form Edits</span><span>Short-form Reels</span><span>Colour Grade</span><span>Motion & Titles</span></div></div>
            <div><div class="eyebrow">(CMS) - Selected Work</div><h1>Work</h1></div>
            <p class="copy-large"><strong>Cinematic editing</strong> for premium creatives and brands - <strong>long-form and short-form</strong>, cut for <strong>retention</strong> and graded so it feels like <strong>film.</strong></p>
          </div>
          <div class="timeline"><div class="tick">00:00<span>+</span></div><div class="tick">00:30<span>+</span></div><div class="tick">01:00<span>+</span></div><div class="tick">01:30<span>+</span></div><div class="tick">02:00<span>+</span></div></div>
        </div>
      </section>
      <section class="wrap section-head"><div><div class="eyebrow">(02) - Portfolio CMS</div><h2>Selected Work</h2></div><a class="pill primary" href="/admin">Upload Project</a></section>
      <section class="wrap grid">{''.join(cards) or '<p>No projects published yet.</p>'}</section>
      <script>document.querySelectorAll('.card').forEach(card=>{{const v=card.querySelector('video'); if(!v)return; card.addEventListener('mouseenter',()=>v.play()); card.addEventListener('mouseleave',()=>{{v.pause(); v.currentTime=0;}});}});</script>
    </main>"""
    return page_shell("Work - Anamorph CMS", body)


def project_html(project):
    image = escape(project.get("image"))
    video = escape(project.get("video"))
    hero_media = f'<video src="{video}" poster="{image}" autoplay muted loop playsinline></video>' if video else f'<img src="{image}" alt="">'
    media = f'<video class="detail-media" src="{video}" poster="{image}" controls autoplay muted loop playsinline></video>' if video else f'<img class="detail-media" src="{image}" alt="{escape(project.get("title"))}">'
    body = f"""
    <header class="topbar"><div class="wrap"><a class="brand" href="/">Anamorph</a><nav class="nav"><a class="pill" href="/work">Work</a><a class="pill" href="/">Home</a><a class="pill primary" href="/admin">CMS</a></nav></div></header>
    <main>
      <section class="hero">
        <div class="hero-media">{hero_media}</div>
        <div class="wrap hero-content">
          <div class="eyebrow">{escape(project.get('eyebrow'))}</div>
          <h1>{escape(project.get('title'))}</h1>
          <div class="timeline"><div class="tick">Client<span>{escape(project.get('client'))}</span></div><div class="tick">Year<span>{escape(project.get('year'))}</span></div><div class="tick">Format<span>{escape(project.get('discipline'))}</span></div><div class="tick">Grade<span>Film</span></div><div class="tick">Status<span>Live</span></div></div>
        </div>
      </section>
      <section class="wrap split">
        <div>{media}</div>
        <aside class="panel glass">
          <p class="eyebrow">Year</p><h2>{escape(project.get('year'))}</h2>
          <p class="eyebrow">Client</p><p>{escape(project.get('client'))}</p>
          <p class="eyebrow">Spec</p><p>{escape(project.get('spec'))}</p>
          <p class="eyebrow">Deliverables</p><p>{escape(project.get('deliverables'))}</p>
          <p class="eyebrow">Story</p><p>{escape(project.get('story'))}</p>
          <div class="stat-grid"><div class="stat"><b>24H</b><p>Reply Time</p></div><div class="stat"><b>02</b><p>Revision Rounds</p></div><div class="stat"><b>98%</b><p>On-time Delivery</p></div><div class="stat"><b>5D</b><p>First Cut</p></div></div>
        </aside>
      </section>
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
      <label><span><input type="checkbox" name="published" {checked} style="width:auto"> Published</span></label>
      <input type="submit" value="{escape('Update project' if project else 'Create project')}">
    </form>"""


def admin_html():
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
    <header class="topbar"><div class="wrap"><a class="brand" href="/">Anamorph</a><nav class="nav"><a class="pill" href="/work">View Work</a><form method="post" action="/logout"><button>Logout</button></form></nav></div></header>
    <main class="wrap admin-grid">
      <section>
        <div class="eyebrow">(CMS) - Local Content</div>
        <h2>Projects</h2>
        <p>All images, videos, and project records are stored locally. Uploads are written into the workspace and served by this CMS server.</p>
        <div class="list">{''.join(items) or '<p>No projects yet.</p>'}</div>
        <div style="margin-top:24px">{edit_forms}</div>
      </section>
      <aside class="panel glass">
        <div class="eyebrow">(Upload) - New Case</div>
        <h2>New</h2>
        {project_form()}
      </aside>
    </main>"""
    return page_shell("Anamorph CMS", body)


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
        if path == "/api/projects":
            return self.send_json({"projects": public_projects()})
        if path == "/work":
            return self.send_html(work_index_html())
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
        if path == "/admin/projects/delete":
            return self.delete_project()
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
                "slug": unique_slug(data, slug, project_id),
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
            if image:
                project["image"] = image
            if video:
                project["video"] = video
            if not project.get("image"):
                project["image"] = "/assets/local/4408de2269c8641c.jpg"
            if existing:
                existing.update(project)
            else:
                data["projects"].insert(0, project)
            save_cms(data)
            return self.redirect("/admin")
        except Exception as exc:
            return self.send_html(page_shell("CMS Error", f"<main class='login'><section class='panel'><h1>Error</h1><p>{escape(exc)}</p><a class='pill' href='/admin'>Back</a></section></main>"), HTTPStatus.BAD_REQUEST)

    def delete_project(self):
        length = int(self.headers.get("Content-Length", "0"))
        values = parse_qs(self.rfile.read(length).decode())
        project_id = values.get("id", [""])[0]
        data = load_cms()
        data["projects"] = [p for p in data["projects"] if p.get("id") != project_id]
        save_cms(data)
        return self.redirect("/admin")


def main():
    ensure_storage()
    port = int(os.environ.get("PORT", "56540"))
    os.chdir(ROOT)
    print(f"Anamorph CMS running on http://localhost:{port}")
    print(f"Login: {CMS_USER} / {CMS_PASSWORD}")
    ThreadingHTTPServer(("", port), CMSHandler).serve_forever()


if __name__ == "__main__":
    main()
