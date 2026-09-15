const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const formidable = require("formidable");

const ROOT = path.join(__dirname, "..");
const SEED_FILE = path.join(ROOT, "data", "cms.json");
const CMS_USER = process.env.CMS_USER || "admin";
const CMS_PASSWORD = process.env.CMS_PASSWORD || "admin123";
const SESSION_SECRET = process.env.SESSION_SECRET || "anamorph-local-session-secret";
const CMS_BLOB_PATH = "cms/data.json";

const IMAGE_EXT = new Set([".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"]);
const VIDEO_EXT = new Set([".mp4", ".webm", ".mov", ".m4v"]);

function escapeHtml(value = "") {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function slugify(value) {
  return String(value || "project").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "project";
}

function parseCookies(req) {
  return Object.fromEntries(String(req.headers.cookie || "").split(";").filter(Boolean).map((part) => {
    const index = part.indexOf("=");
    return [part.slice(0, index).trim(), decodeURIComponent(part.slice(index + 1))];
  }));
}

function signSession() {
  const timestamp = String(Date.now());
  const sig = crypto.createHmac("sha256", SESSION_SECRET).update(timestamp).digest("hex");
  return `${timestamp}:${sig}`;
}

function validSession(value) {
  if (!value || !value.includes(":")) return false;
  const [timestamp, sig] = value.split(":");
  const expected = crypto.createHmac("sha256", SESSION_SECRET).update(timestamp).digest("hex");
  if (sig.length !== expected.length) return false;
  if (!crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) return false;
  return Date.now() - Number(timestamp) < 1000 * 60 * 60 * 24 * 7;
}

function seedCms() {
  return JSON.parse(fs.readFileSync(SEED_FILE, "utf8"));
}

async function blobApi() {
  if (!process.env.BLOB_READ_WRITE_TOKEN) return null;
  return await import("@vercel/blob");
}

async function loadCms() {
  const blob = await blobApi();
  if (!blob) return seedCms();
  const result = await blob.list({ prefix: CMS_BLOB_PATH, limit: 1, token: process.env.BLOB_READ_WRITE_TOKEN });
  const item = result.blobs.find((entry) => entry.pathname === CMS_BLOB_PATH);
  if (!item) {
    const seed = seedCms();
    await saveCms(seed);
    return seed;
  }
  const response = await fetch(item.url, { cache: "no-store" });
  return await response.json();
}

async function saveCms(data) {
  const blob = await blobApi();
  if (!blob) throw new Error("BLOB_READ_WRITE_TOKEN is required for CMS edits on Vercel.");
  await blob.put(CMS_BLOB_PATH, JSON.stringify(data, null, 2), {
    access: "public",
    addRandomSuffix: false,
    allowOverwrite: true,
    contentType: "application/json",
    token: process.env.BLOB_READ_WRITE_TOKEN
  });
}

function publicProjects(data) {
  return [...(data.projects || [])].filter((p) => p.published !== false).sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
}

function uniqueSlug(data, base, currentId) {
  const root = slugify(base);
  const existing = new Set((data.projects || []).filter((p) => p.id !== currentId).map((p) => p.slug));
  if (!existing.has(root)) return root;
  let i = 2;
  while (existing.has(`${root}-${i}`)) i += 1;
  return `${root}-${i}`;
}

function shell(title, body) {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(title)}</title>
  <link rel="icon" href="/assets/local/d189f945785ecf79.png">
  <style>
    :root{color-scheme:dark;--bg:#0a0a0a;--paper:#f4f2ed;--muted:rgba(244,242,237,.62);--line:rgba(244,242,237,.12);--accent:#db3903}
    *{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#0a0a0a;color:var(--paper);font-family:Inter,Arial,sans-serif;-webkit-font-smoothing:antialiased}
    body:before{content:"";position:fixed;inset:0;z-index:-2;background:radial-gradient(circle at 50% 0%,rgba(219,57,3,.13),transparent 30%),linear-gradient(180deg,#0e1416 0%,#0a0a0a 38%,#0a0a0a)}
    body:after{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background:linear-gradient(90deg,rgba(244,242,237,.035) 1px,transparent 1px),linear-gradient(180deg,rgba(244,242,237,.03) 1px,transparent 1px);background-size:20vw 100%,100% 120px;mask-image:linear-gradient(to bottom,#000,transparent 78%)}
    a{color:inherit;text-decoration:none}.wrap{width:min(1200px,calc(100vw - 32px));margin:0 auto}
    .topbar{position:fixed;inset:0 0 auto;z-index:10;backdrop-filter:blur(18px);background:rgba(10,10,10,.58);border-bottom:1px solid var(--line)}.topbar .wrap{min-height:68px;display:flex;align-items:center;justify-content:space-between;gap:18px}
    .brand{font-size:clamp(30px,4vw,58px);letter-spacing:-.08em;line-height:.86}.nav{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
    .pill,button,input[type=submit]{border:1px solid var(--line);background:rgba(244,242,237,.06);color:var(--paper);border-radius:999px;padding:10px 14px;font:inherit;cursor:pointer;transition:transform .35s cubic-bezier(.16,1,.3,1),background .35s,border-color .35s}.pill:hover,button:hover,input[type=submit]:hover{transform:translateY(-1px);background:rgba(244,242,237,.12);border-color:rgba(244,242,237,.22)}.pill.primary,input[type=submit],button.primary{background:var(--accent);border-color:var(--accent)}
    .hero{min-height:86vh;display:grid;align-items:end;padding:120px 0 34px;border-bottom:1px solid var(--line);position:relative;overflow:hidden}.hero.compact{min-height:50vh}.hero-media{position:absolute;inset:0;opacity:.48;transform:scale(1.04);animation:posterIn 2.4s cubic-bezier(.16,1,.3,1) forwards}.hero-media img,.hero-media video{width:100%;height:100%;object-fit:cover;display:block;filter:saturate(.82) contrast(1.08)}.hero-media:after{content:"";position:absolute;inset:0;background:radial-gradient(circle at 50% 45%,transparent 0 36%,rgba(10,10,10,.5) 74%),linear-gradient(180deg,rgba(10,10,10,.22),rgba(10,10,10,.92))}.hero-content{position:relative;z-index:1}.hero-row{display:grid;grid-template-columns:240px 1fr 300px;gap:28px;align-items:end}.services{display:grid;gap:8px;color:var(--paper);font-size:15px;letter-spacing:-.03em}.copy-large{max-width:430px;margin-left:auto;text-align:right;font-size:clamp(22px,2.4vw,34px);line-height:1.03;letter-spacing:-.055em;color:var(--muted)}.copy-large strong{color:var(--paper);font-weight:400}
    .eyebrow{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}h1{font-weight:400;letter-spacing:-.08em;line-height:.86;font-size:clamp(72px,17vw,238px);margin:18px 0 0;text-transform:capitalize;animation:riseIn 1.6s .15s cubic-bezier(.16,1,.3,1) both}h2{font-weight:400;letter-spacing:-.055em;line-height:1;font-size:clamp(36px,7vw,86px);margin:0}p{color:var(--muted);line-height:1.55}
    .timeline{display:grid;grid-template-columns:repeat(5,1fr);border-top:1px solid var(--line);margin-top:26px;color:rgba(244,242,237,.45);font-size:12px}.tick{min-height:74px;border-left:1px solid var(--line);padding:10px;display:flex;justify-content:space-between;align-items:flex-start}.tick:last-child{border-right:1px solid var(--line)}
    .section-head{display:grid;grid-template-columns:1fr auto;align-items:end;gap:20px;padding:88px 0 22px;border-bottom:1px solid var(--line)}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;padding:28px 0 90px}.card{border-top:1px solid var(--line);padding-top:14px;position:relative;animation:riseIn 1.2s cubic-bezier(.16,1,.3,1) both}.thumb-frame{aspect-ratio:16/9;overflow:hidden;background:#151515;position:relative}.thumb{width:100%;height:100%;object-fit:cover;display:block;transform:scale(1.01);transition:transform .8s cubic-bezier(.16,1,.3,1),filter .8s}.thumb-video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .5s}.card:hover .thumb{transform:scale(1.055);filter:brightness(.68)}.card:hover .thumb-video{opacity:1}.meta{display:flex;align-items:center;justify-content:space-between;gap:12px;color:var(--muted);font-size:12px;text-transform:uppercase;margin:12px 0 18px}.card h3{font-weight:400;font-size:clamp(28px,4vw,48px);letter-spacing:-.06em;margin:0 0 6px}
    .detail-media{width:100%;max-height:76vh;object-fit:cover;background:#111;display:block}.split{display:grid;grid-template-columns:1.2fr .8fr;gap:32px;padding:36px 0 80px}.panel{border:1px solid var(--line);background:rgba(244,242,237,.045);padding:18px;backdrop-filter:blur(14px)}.panel.glass{background:rgba(10,10,10,.52);border-color:rgba(244,242,237,.16);box-shadow:0 20px 60px rgba(0,0,0,.24)}.stat-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:var(--line);margin-top:22px}.stat{background:rgba(10,10,10,.88);padding:18px}.stat b{display:block;font-weight:400;font-size:clamp(32px,5vw,64px);letter-spacing:-.07em;line-height:.9}
    .admin-grid{display:grid;grid-template-columns:minmax(0,1fr) 390px;gap:24px;padding:108px 0 70px}label{display:grid;gap:7px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}input,textarea,select{width:100%;border:1px solid var(--line);background:rgba(244,242,237,.06);color:var(--paper);padding:12px;border-radius:8px;font:inherit;outline:none}textarea{min-height:110px;resize:vertical}form{display:grid;gap:14px}.row{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.list{display:grid;gap:12px}.item{display:grid;grid-template-columns:120px 1fr auto;gap:14px;align-items:center;border:1px solid var(--line);padding:10px;background:rgba(244,242,237,.035)}.item img{width:120px;aspect-ratio:16/9;object-fit:cover;background:#151515}details{border:1px solid var(--line);padding:14px;margin-top:12px;background:rgba(244,242,237,.035)}summary{cursor:pointer}.danger{background:#34110c;border-color:rgba(219,57,3,.45)}.login{min-height:100vh;display:grid;place-items:center;padding:24px;background:linear-gradient(180deg,rgba(10,10,10,.12),rgba(10,10,10,.85)),url('/assets/local/323795fc9c20f1ac.png') center/cover}.login .panel{width:min(440px,100%)}
    @keyframes riseIn{from{opacity:0;transform:translateY(48px)}to{opacity:1;transform:translateY(0)}}@keyframes posterIn{from{opacity:.001;transform:scale(1.08)}to{opacity:.48;transform:scale(1.04)}}@media(max-width:920px){.hero-row,.grid,.split,.admin-grid,.row{grid-template-columns:1fr}.copy-large{margin:22px 0 0;text-align:left}.timeline{grid-template-columns:repeat(3,1fr)}.item{grid-template-columns:82px 1fr}.item form{grid-column:1/-1}h1{font-size:clamp(62px,24vw,130px)}}
  </style>
</head><body>${body}</body></html>`;
}

function workIndex(projects) {
  const hero = projects[0] || {};
  const heroImage = escapeHtml(hero.image || "/assets/local/323795fc9c20f1ac.png");
  const heroVideo = escapeHtml(hero.video || "");
  const heroMedia = heroVideo ? `<video src="${heroVideo}" poster="${heroImage}" autoplay muted loop playsinline></video>` : `<img src="${heroImage}" alt="">`;
  const cards = projects.map((p, i) => {
    const video = p.video ? `<video class="thumb-video" src="${escapeHtml(p.video)}" muted loop playsinline></video>` : "";
    return `<a class="card" href="/work/${escapeHtml(p.slug)}"><div class="thumb-frame"><img class="thumb" src="${escapeHtml(p.image)}" alt="${escapeHtml(p.title)}">${video}</div><div class="meta"><span>(${String(i + 1).padStart(2, "0")}) - Selected Work</span><span>${escapeHtml(p.year)}</span></div><h3>${escapeHtml(p.title)}</h3><p>${escapeHtml(p.project)} - ${escapeHtml(p.discipline)}</p></a>`;
  }).join("");
  return shell("Work - Anamorph CMS", `<header class="topbar"><div class="wrap"><a class="brand" href="/">Anamorph</a><nav class="nav"><a class="pill" href="/">Home</a><a class="pill" href="/#reels">Reels</a><a class="pill primary" href="/admin">CMS</a></nav></div></header><main><section class="hero"><div class="hero-media">${heroMedia}</div><div class="wrap hero-content"><div class="hero-row"><div><div class="eyebrow">(01) - Services</div><div class="services"><span>Long-form Edits</span><span>Short-form Reels</span><span>Colour Grade</span><span>Motion & Titles</span></div></div><div><div class="eyebrow">(CMS) - Selected Work</div><h1>Work</h1></div><p class="copy-large"><strong>Cinematic editing</strong> for premium creatives and brands - <strong>long-form and short-form</strong>, cut for <strong>retention</strong> and graded so it feels like <strong>film.</strong></p></div><div class="timeline"><div class="tick">00:00<span>+</span></div><div class="tick">00:30<span>+</span></div><div class="tick">01:00<span>+</span></div><div class="tick">01:30<span>+</span></div><div class="tick">02:00<span>+</span></div></div></div></section><section class="wrap section-head"><div><div class="eyebrow">(02) - Portfolio CMS</div><h2>Selected Work</h2></div><a class="pill primary" href="/admin">Upload Project</a></section><section class="wrap grid">${cards || "<p>No projects published yet.</p>"}</section><script>document.querySelectorAll('.card').forEach(card=>{const v=card.querySelector('video');if(!v)return;card.addEventListener('mouseenter',()=>v.play());card.addEventListener('mouseleave',()=>{v.pause();v.currentTime=0;});});</script></main>`);
}

function projectPage(project) {
  const image = escapeHtml(project.image || "");
  const video = escapeHtml(project.video || "");
  const heroMedia = video ? `<video src="${video}" poster="${image}" autoplay muted loop playsinline></video>` : `<img src="${image}" alt="">`;
  const media = video ? `<video class="detail-media" src="${video}" poster="${image}" controls autoplay muted loop playsinline></video>` : `<img class="detail-media" src="${image}" alt="${escapeHtml(project.title)}">`;
  return shell(`${project.title} - Anamorph`, `<header class="topbar"><div class="wrap"><a class="brand" href="/">Anamorph</a><nav class="nav"><a class="pill" href="/work">Work</a><a class="pill" href="/">Home</a><a class="pill primary" href="/admin">CMS</a></nav></div></header><main><section class="hero"><div class="hero-media">${heroMedia}</div><div class="wrap hero-content"><div class="eyebrow">${escapeHtml(project.eyebrow)}</div><h1>${escapeHtml(project.title)}</h1><div class="timeline"><div class="tick">Client<span>${escapeHtml(project.client)}</span></div><div class="tick">Year<span>${escapeHtml(project.year)}</span></div><div class="tick">Format<span>${escapeHtml(project.discipline)}</span></div><div class="tick">Grade<span>Film</span></div><div class="tick">Status<span>Live</span></div></div></div></section><section class="wrap split"><div>${media}</div><aside class="panel glass"><p class="eyebrow">Year</p><h2>${escapeHtml(project.year)}</h2><p class="eyebrow">Client</p><p>${escapeHtml(project.client)}</p><p class="eyebrow">Spec</p><p>${escapeHtml(project.spec)}</p><p class="eyebrow">Deliverables</p><p>${escapeHtml(project.deliverables)}</p><p class="eyebrow">Story</p><p>${escapeHtml(project.story)}</p><div class="stat-grid"><div class="stat"><b>24H</b><p>Reply Time</p></div><div class="stat"><b>02</b><p>Revision Rounds</p></div><div class="stat"><b>98%</b><p>On-time Delivery</p></div><div class="stat"><b>5D</b><p>First Cut</p></div></div></aside></section></main>`);
}

function loginPage(error = "") {
  return shell("CMS Login", `<main class="login"><section class="panel glass"><div class="brand">Anamorph</div><p class="eyebrow">(CMS) - Login</p><h2>Studio Access</h2><p>Upload project posters, reels, and case-study copy into the local portfolio.</p>${error ? `<p style="color:#ff9b7d">${escapeHtml(error)}</p>` : ""}<form method="post" action="/login"><label>Username<input name="username" autocomplete="username" required></label><label>Password<input type="password" name="password" autocomplete="current-password" required></label><input type="submit" value="Login"></form></section></main>`);
}

function projectForm(project = {}) {
  const checked = project.published === false ? "" : "checked";
  return `<form method="post" action="/admin/projects" enctype="multipart/form-data"><input type="hidden" name="id" value="${escapeHtml(project.id || "")}"><div class="row"><label>Title<input name="title" value="${escapeHtml(project.title || "")}" required></label><label>Slug<input name="slug" value="${escapeHtml(project.slug || "")}" placeholder="auto from title"></label></div><div class="row"><label>Eyebrow<input name="eyebrow" value="${escapeHtml(project.eyebrow || "(01) - Selected Work")}"></label><label>Year<input name="year" value="${escapeHtml(project.year || "2026")}"></label></div><div class="row"><label>Project<input name="project" value="${escapeHtml(project.project || "")}"></label><label>Discipline<input name="discipline" value="${escapeHtml(project.discipline || "")}"></label></div><div class="row"><label>Client<input name="client" value="${escapeHtml(project.client || "")}"></label><label>Spec<input name="spec" value="${escapeHtml(project.spec || "")}"></label></div><label>Deliverables<input name="deliverables" value="${escapeHtml(project.deliverables || "")}"></label><label>Story<textarea name="story">${escapeHtml(project.story || "")}</textarea></label><div class="row"><label>Poster image<input type="file" name="image" accept="image/*"></label><label>Video file<input type="file" name="video" accept="video/*"></label></div><label><span><input type="checkbox" name="published" ${checked} style="width:auto"> Published</span></label><input type="submit" value="${project.id ? "Update project" : "Create project"}"></form>`;
}

function adminPage(data) {
  const items = (data.projects || []).map((p) => `<div class="item"><img src="${escapeHtml(p.image)}" alt=""><div><strong>${escapeHtml(p.title)}</strong><p>/${escapeHtml(p.slug)} - ${escapeHtml(p.year)} - ${p.published === false ? "Draft" : "Published"}</p><a class="pill" href="/work/${escapeHtml(p.slug)}">Preview</a></div><form method="post" action="/admin/projects/delete" onsubmit="return confirm('Delete this project?')"><input type="hidden" name="id" value="${escapeHtml(p.id)}"><button class="danger">Delete</button></form></div>`).join("");
  const edits = (data.projects || []).map((p) => `<details><summary>Edit ${escapeHtml(p.title)}</summary>${projectForm(p)}</details>`).join("");
  return shell("Anamorph CMS", `<header class="topbar"><div class="wrap"><a class="brand" href="/">Anamorph</a><nav class="nav"><a class="pill" href="/work">View Work</a><form method="post" action="/logout"><button>Logout</button></form></nav></div></header><main class="wrap admin-grid"><section><div class="eyebrow">(CMS) - Local Content</div><h2>Projects</h2><p>All images, videos, and project records are stored in Vercel Blob when deployed. Seed assets stay local in this repo.</p><div class="list">${items || "<p>No projects yet.</p>"}</div><div style="margin-top:24px">${edits}</div></section><aside class="panel glass"><div class="eyebrow">(Upload) - New Case</div><h2>New</h2>${projectForm()}</aside></main>`);
}

function send(res, status, body, type = "text/html; charset=utf-8") {
  res.statusCode = status;
  res.setHeader("Content-Type", type);
  res.end(body);
}

function redirect(res, location, extraHeaders = {}) {
  res.statusCode = 303;
  res.setHeader("Location", location);
  Object.entries(extraHeaders).forEach(([key, value]) => res.setHeader(key, value));
  res.end();
}

async function parseForm(req) {
  const form = formidable({ multiples: false, maxFileSize: 250 * 1024 * 1024 });
  return await new Promise((resolve, reject) => form.parse(req, (err, fields, files) => err ? reject(err) : resolve({ fields, files })));
}

function first(value) {
  return Array.isArray(value) ? value[0] : value;
}

async function uploadFile(file, kind) {
  const f = Array.isArray(file) ? file[0] : file;
  if (!f || !f.originalFilename) return "";
  const ext = path.extname(f.originalFilename).toLowerCase();
  const allowed = kind === "image" ? IMAGE_EXT : VIDEO_EXT;
  if (!allowed.has(ext)) throw new Error(`${kind} file type not allowed`);
  const blob = await blobApi();
  if (!blob) throw new Error("BLOB_READ_WRITE_TOKEN is required for uploads on Vercel.");
  const bytes = fs.readFileSync(f.filepath);
  const prefix = kind === "image" ? "uploads/images" : "uploads/videos";
  const result = await blob.put(`${prefix}/${Date.now()}-${crypto.randomUUID()}${ext}`, bytes, {
    access: "public",
    contentType: f.mimetype || undefined,
    token: process.env.BLOB_READ_WRITE_TOKEN
  });
  return result.url;
}

async function saveProject(req, res) {
  try {
    const { fields, files } = await parseForm(req);
    const data = await loadCms();
    const id = first(fields.id) || crypto.randomUUID();
    const existing = (data.projects || []).find((p) => p.id === id);
    const project = { ...(existing || { id, created_at: new Date().toISOString() }) };
    const title = first(fields.title) || project.title || "Untitled";
    Object.assign(project, {
      title,
      slug: uniqueSlug(data, first(fields.slug) || title, id),
      eyebrow: first(fields.eyebrow) || project.eyebrow || "",
      year: first(fields.year) || project.year || "",
      project: first(fields.project) || project.project || "",
      discipline: first(fields.discipline) || project.discipline || "",
      client: first(fields.client) || project.client || "",
      spec: first(fields.spec) || project.spec || "",
      deliverables: first(fields.deliverables) || project.deliverables || "",
      story: first(fields.story) || project.story || "",
      published: first(fields.published) === "on",
      updated_at: new Date().toISOString()
    });
    const image = await uploadFile(files.image, "image");
    const video = await uploadFile(files.video, "video");
    if (image) project.image = image;
    if (video) project.video = video;
    if (!project.image) project.image = "/assets/local/4408de2269c8641c.jpg";
    if (existing) Object.assign(existing, project);
    else data.projects.unshift(project);
    await saveCms(data);
    redirect(res, "/admin");
  } catch (error) {
    send(res, 400, shell("CMS Error", `<main class="login"><section class="panel glass"><h1>Error</h1><p>${escapeHtml(error.message)}</p><a class="pill" href="/admin">Back</a></section></main>`));
  }
}

async function deleteProject(req, res) {
  const { fields } = await parseForm(req);
  const data = await loadCms();
  const id = first(fields.id);
  data.projects = (data.projects || []).filter((p) => p.id !== id);
  await saveCms(data);
  redirect(res, "/admin");
}

module.exports = async function handler(req, res) {
  const url = new URL(req.url, `https://${req.headers.host || "localhost"}`);
  const pathname = url.pathname.replace(/\/$/, "") || "/";
  const cookies = parseCookies(req);
  const loggedIn = validSession(cookies.cms_session);

  if (req.method === "POST" && pathname === "/login") {
    let body = "";
    for await (const chunk of req) body += chunk;
    const params = new URLSearchParams(body);
    if (params.get("username") === CMS_USER && params.get("password") === CMS_PASSWORD) {
      redirect(res, "/admin", { "Set-Cookie": `cms_session=${encodeURIComponent(signSession())}; HttpOnly; SameSite=Lax; Path=/; Secure` });
    } else {
      send(res, 401, loginPage("Wrong username or password."));
    }
    return;
  }
  if (req.method === "POST" && pathname === "/logout") {
    redirect(res, "/login", { "Set-Cookie": "cms_session=; Max-Age=0; Path=/" });
    return;
  }

  const data = await loadCms();
  const projects = publicProjects(data);

  if (req.method === "GET" && pathname === "/api/projects") return send(res, 200, JSON.stringify({ projects }), "application/json; charset=utf-8");
  if (req.method === "GET" && pathname === "/login") return send(res, 200, loginPage());
  if (req.method === "GET" && pathname === "/admin") return loggedIn ? send(res, 200, adminPage(data)) : redirect(res, "/login");
  if (req.method === "POST" && pathname === "/admin/projects") return loggedIn ? saveProject(req, res) : redirect(res, "/login");
  if (req.method === "POST" && pathname === "/admin/projects/delete") return loggedIn ? deleteProject(req, res) : redirect(res, "/login");
  if (req.method === "GET" && pathname === "/work") return send(res, 200, workIndex(projects));
  if (req.method === "GET" && pathname.startsWith("/work/")) {
    const slug = pathname.split("/")[2];
    const project = projects.find((p) => p.slug === slug);
    if (!project) return send(res, 404, "Project not found", "text/plain; charset=utf-8");
    return send(res, 200, projectPage(project));
  }

  send(res, 404, "Not found", "text/plain; charset=utf-8");
};
