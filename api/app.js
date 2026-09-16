const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const formidable = require("formidable");

const ROOT = path.join(__dirname, "..");
const SEED_FILE = path.join(ROOT, "data", "cms.json");
const WORK_DETAIL_TEMPLATE = path.join(ROOT, "templates", "work-detail-framer.html");
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

function escapeAttr(value = "") {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function youtubeId(value = "") {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    const url = new URL(raw);
    if (url.hostname.includes("youtu.be")) return url.pathname.split("/").filter(Boolean)[0] || "";
    if (url.hostname.includes("youtube.com")) {
      if (url.pathname.startsWith("/watch")) return url.searchParams.get("v") || "";
      const parts = url.pathname.split("/").filter(Boolean);
      if (["shorts", "embed", "live"].includes(parts[0])) return parts[1] || "";
    }
  } catch (_) {}
  return "";
}

function youtubeEmbed(value = "", autoplay = false) {
  const id = youtubeId(value);
  if (!id) return "";
  const params = autoplay
    ? `autoplay=1&mute=1&loop=1&playlist=${encodeURIComponent(id)}&controls=0&rel=0&playsinline=1`
    : "rel=0&playsinline=1";
  return `https://www.youtube.com/embed/${encodeURIComponent(id)}?${params}`;
}

function driveImage(value = "") {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    const url = new URL(raw);
    if (!url.hostname.includes("drive.google.com")) return raw;
    const parts = url.pathname.split("/").filter(Boolean);
    const fileIndex = parts.indexOf("d");
    const id = fileIndex >= 0 ? parts[fileIndex + 1] : url.searchParams.get("id");
    return id ? `https://drive.google.com/thumbnail?id=${encodeURIComponent(id)}&sz=w2400` : raw;
  } catch (_) {
    return raw;
  }
}

function mediaHtml(item, mode = "card") {
  const image = escapeHtml(item.image || "");
  const video = String(item.video || "").trim();
  const title = escapeHtml(item.title || "");
  const yt = youtubeEmbed(video, mode !== "detail");
  if (yt) return `<iframe class="${mode === "detail" ? "detail-media" : ""}" src="${escapeHtml(yt)}" title="${title}" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>`;
  if (video) {
    const controls = mode === "detail" ? "controls " : "";
    const cls = mode === "detail" ? ' class="detail-media"' : "";
    return `<video${cls} src="${escapeHtml(video)}" poster="${image}" ${controls}autoplay muted loop playsinline></video>`;
  }
  return `<img${mode === "detail" ? ' class="detail-media"' : ""} src="${image}" alt="${title}">`;
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
  const data = JSON.parse(fs.readFileSync(SEED_FILE, "utf8"));
  data.home = data.home || { text_replacements: [], image_replacements: [] };
  return data;
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
  const data = await response.json();
  data.home = data.home || { text_replacements: [], image_replacements: [] };
  return data;
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

function publicReels(data) {
  return [...(data.reels || [])].filter((r) => r.published !== false).sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
}

function publicHome(data) {
  const home = data.home || {};
  return {
    text_replacements: Array.isArray(home.text_replacements) ? home.text_replacements : [],
    image_replacements: Array.isArray(home.image_replacements) ? home.image_replacements : []
  };
}

function pairsToText(pairs = []) {
  return pairs.map((pair) => `${pair.from || ""} => ${pair.to || ""}`).join("\n");
}

function textToPairs(value = "") {
  return String(value || "").split(/\r?\n/).map((line) => {
    const trimmed = line.trim();
    if (!trimmed) return null;
    const index = trimmed.includes("=>") ? trimmed.indexOf("=>") : trimmed.indexOf("|");
    if (index < 0) return null;
    const from = trimmed.slice(0, index).trim();
    const to = trimmed.slice(index + (trimmed.includes("=>") ? 2 : 1)).trim();
    return from && to ? { from, to } : null;
  }).filter(Boolean);
}

function appendPair(pairs, from, to) {
  const cleanFrom = String(from || "").trim();
  const cleanTo = String(to || "").trim();
  if (cleanFrom && cleanTo) pairs.push({ from: cleanFrom, to: cleanTo });
}

function uniqueSlug(data, collection, base, currentId) {
  const root = slugify(base);
  const existing = new Set((data[collection] || []).filter((p) => p.id !== currentId).map((p) => p.slug));
  if (!existing.has(root)) return root;
  let i = 2;
  while (existing.has(`${root}-${i}`)) i += 1;
  return `${root}-${i}`;
}

function nextProject(projects, slug) {
  if (!projects.length) return null;
  const index = projects.findIndex((p) => p.slug === slug);
  return projects[(index + 1 + projects.length) % projects.length] || projects[0];
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
    @font-face{font-family:"BDO Grotesk Variable";src:url("/assets/local/210f21e63da86188.woff2") format("woff2");font-style:normal;font-weight:400;font-display:swap}
    @font-face{font-family:"Inter";src:url("/assets/local/197dd743787c17b1.woff2") format("woff2");font-style:normal;font-weight:400;font-display:swap}
    :root{color-scheme:dark;--bg:#0a0a0a;--paper:#f4f2ed;--muted:rgba(244,242,237,.6);--faint:rgba(244,242,237,.3);--line:rgba(244,242,237,.12);--line-strong:rgba(244,242,237,.22);--accent:#db3903}
    *{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#0a0a0a;color:var(--paper);font-family:"BDO Grotesk Variable",Inter,Arial,sans-serif;-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}
    body:before{content:"";position:fixed;inset:0;z-index:-2;background:var(--bg)}
    body:after{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background:linear-gradient(90deg,rgba(244,242,237,.045) 1px,transparent 1px);background-size:20vw 100%;mask-image:linear-gradient(to bottom,#000,transparent 82%)}
    a{color:inherit;text-decoration:none}.wrap{width:min(1200px,calc(100vw - 32px));margin:0 auto}
    .topbar{position:fixed;left:0;right:0;bottom:24px;z-index:10;pointer-events:none}.topbar .wrap{width:max-content;max-width:calc(100vw - 28px);min-height:0;display:flex;align-items:center;justify-content:center;gap:8px;padding:8px;border:1px solid var(--line);border-radius:16px;background:rgba(10,10,10,.66);backdrop-filter:blur(18px);box-shadow:0 18px 60px rgba(0,0,0,.36);pointer-events:auto}
    .brand{font-size:21px;letter-spacing:-.08em;line-height:.86;padding:0 8px 0 4px}.nav{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
    .pill,button,input[type=submit]{border:1px solid var(--line);background:rgba(244,242,237,.06);color:var(--paper);border-radius:999px;padding:10px 14px;font:inherit;font-size:13px;letter-spacing:-.05em;cursor:pointer;transition:transform .35s cubic-bezier(.16,1,.3,1),background .35s,border-color .35s}.pill:hover,button:hover,input[type=submit]:hover{transform:translateY(-1px);background:rgba(244,242,237,.12);border-color:rgba(244,242,237,.22)}.pill.primary,input[type=submit],button.primary{background:var(--accent);border-color:var(--accent)}
    .hero{min-height:100vh;display:grid;align-items:end;padding:120px 0 34px;border-bottom:1px solid var(--line);position:relative;overflow:hidden}.hero.compact{min-height:76vh}.hero-media{position:absolute;inset:0;opacity:.001;transform:scale(1.08);animation:posterIn 2.4s cubic-bezier(.16,1,.3,1) forwards}.hero-media img,.hero-media video,.hero-media iframe{width:100%;height:100%;object-fit:cover;display:block;border:0;filter:saturate(.78) contrast(1.08)}.hero-media:after{content:"";position:absolute;inset:0;background:radial-gradient(circle at 50% 45%,transparent 0 34%,rgba(10,10,10,.45) 72%),linear-gradient(180deg,rgba(10,10,10,.16),rgba(10,10,10,.94))}.hero-content{position:relative;z-index:1}.hero-row{display:grid;grid-template-columns:250px 1fr 330px;gap:28px;align-items:end}.services{display:grid;gap:8px;color:var(--paper);font-size:15px;letter-spacing:-.05em}.copy-large{max-width:430px;margin-left:auto;text-align:right;font-size:clamp(22px,2.4vw,34px);line-height:1.03;letter-spacing:-.055em;color:var(--muted)}.copy-large strong{color:var(--paper);font-weight:400}
    .opening{min-height:100vh;position:relative;display:grid;align-items:end;padding:112px 0 38px;overflow:hidden;border-bottom:1px solid var(--line)}.opening .wrap{position:relative;z-index:1}.opening-copy{font-size:clamp(48px,6.45vw,77px);line-height:1.06;letter-spacing:-.07em;max-width:1010px;margin:0 0 58px}.opening-copy span{color:var(--muted)}.reveal-word{display:inline-block;animation:wordIn 1.25s cubic-bezier(.16,1,.3,1) both}.reveal-word:nth-child(2n){animation-delay:.06s}.reveal-word:nth-child(3n){animation-delay:.12s}.reveal-muted{color:var(--muted)}.time-grid{position:absolute;inset:0;display:grid;grid-template-columns:repeat(5,1fr);pointer-events:none;color:var(--muted);font-size:12px}.time-tick{border-left:1px solid var(--line);display:grid;grid-template-rows:auto 1fr auto 1fr;padding:24px 10px;animation:tickIn 1.4s cubic-bezier(.16,1,.3,1) both}.time-tick:nth-child(even){animation-name:tickDown}.time-tick:last-child{border-right:1px solid var(--line)}.plus{align-self:center;justify-self:start;color:var(--paper);font-size:22px;line-height:1}.rule{width:1px;background:var(--line);min-height:80px}
    .eyebrow{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}h1{font-weight:400;letter-spacing:-.08em;line-height:.82;font-size:clamp(78px,19vw,240px);margin:18px 0 0;text-transform:capitalize;animation:riseIn 1.6s .15s cubic-bezier(.16,1,.3,1) both}h2{font-weight:400;letter-spacing:-.07em;line-height:1;font-size:clamp(42px,8vw,96px);margin:0}p{color:var(--muted);line-height:1.45;letter-spacing:-.035em}
    .timeline{display:grid;grid-template-columns:repeat(5,1fr);border-top:1px solid var(--line);margin-top:26px;color:rgba(244,242,237,.45);font-size:12px}.tick{min-height:74px;border-left:1px solid var(--line);padding:10px;display:flex;justify-content:space-between;align-items:flex-start}.tick:last-child{border-right:1px solid var(--line)}.tick span{text-align:right;color:var(--paper)}
    .section-head{display:grid;grid-template-columns:1fr auto;align-items:end;gap:20px;padding:80px 0 22px;border-bottom:1px solid var(--line)}.work-count{display:grid;grid-template-columns:1fr auto;align-items:center;padding:22px 0;border-bottom:1px solid var(--line);font-size:14px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}.work-count b{font-weight:400;color:var(--paper)}.work-screening-poster{position:absolute;inset:0;opacity:.42;transform:scale(1.04);animation:posterIn 2.4s cubic-bezier(.16,1,.3,1) both}.work-screening-poster img,.work-screening-poster video{width:100%;height:100%;object-fit:cover;display:block;filter:saturate(.82) contrast(1.08)}.work-screening-grade{position:absolute;inset:0;background:radial-gradient(circle at 50% 38%,transparent 0 26%,rgba(10,10,10,.48) 64%),linear-gradient(180deg,rgba(10,10,10,.2),rgba(10,10,10,.92));pointer-events:none}.rec-badge{display:inline-flex;align-items:center;gap:8px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}.rec-badge:before{content:"";width:8px;height:8px;border-radius:50%;background:var(--accent);box-shadow:0 0 18px rgba(219,57,3,.8)}.work-spec-strip{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin-top:22px}.work-spec-cell{min-height:112px;border-left:1px solid var(--line);padding:14px}.work-spec-cell:last-child{border-right:1px solid var(--line)}.work-spec-cell strong{display:block;font-size:clamp(28px,4vw,56px);line-height:.92;letter-spacing:-.07em;font-weight:400;color:var(--paper);margin-top:18px}.work-list{padding:0 0 112px}.work-row{display:grid;grid-template-columns:70px minmax(210px,1fr) minmax(230px,.9fr) 110px minmax(180px,.75fr);gap:20px;align-items:center;min-height:148px;border-bottom:1px solid var(--line);position:relative;overflow:hidden;animation:riseIn 1.2s cubic-bezier(.16,1,.3,1) both}.work-row:hover{border-color:var(--line-strong)}.work-row:hover .work-thumb{opacity:1;transform:translateY(-50%) scale(1)}.work-num,.work-year,.work-spec{color:var(--muted);font-size:14px;text-transform:uppercase}.work-title{font-size:clamp(38px,6vw,84px);line-height:.9;letter-spacing:-.075em}.work-project{font-size:clamp(20px,2.3vw,34px);line-height:1.02;letter-spacing:-.055em;color:var(--muted)}.work-thumb{position:absolute;right:18%;top:50%;width:min(34vw,430px);aspect-ratio:16/9;object-fit:cover;opacity:0;transform:translateY(-50%) scale(.96);transition:.55s cubic-bezier(.16,1,.3,1);pointer-events:none;z-index:2;box-shadow:0 22px 80px rgba(0,0,0,.42)}
    .detail-media{width:100%;height:min(82vh,56vw);max-height:82vh;object-fit:cover;background:#111;display:block;border:0}.reel-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);margin:0 0 112px}.reel-card{min-height:560px;background:#0a0a0a;display:grid;grid-template-rows:1fr auto;overflow:hidden;position:relative}.reel-card video,.reel-card img,.reel-card iframe{width:100%;height:100%;object-fit:cover;display:block;border:0;filter:saturate(.86) contrast(1.04);transform:scale(1.01);transition:transform .8s cubic-bezier(.16,1,.3,1),filter .8s}.reel-card:hover video,.reel-card:hover img,.reel-card:hover iframe{transform:scale(1.055);filter:saturate(1) contrast(1.08)}.reel-meta{border-top:1px solid var(--line);padding:14px;display:grid;grid-template-columns:1fr auto;gap:14px;background:#0a0a0a}.reel-meta h3{font-size:clamp(28px,4vw,52px);font-weight:400;letter-spacing:-.07em;line-height:.92;margin:0}.reel-meta p{margin:6px 0 0}.split{display:grid;grid-template-columns:1.2fr .8fr;gap:32px;padding:36px 0 80px}.panel{border:1px solid var(--line);background:rgba(244,242,237,.045);padding:18px;backdrop-filter:blur(14px)}.panel.glass{background:rgba(10,10,10,.52);border-color:rgba(244,242,237,.16);box-shadow:0 20px 60px rgba(0,0,0,.24)}.sheet{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin:42px 0 0}.sheet-item{min-height:120px;border-left:1px solid var(--line);padding:14px}.sheet-item:last-child{border-right:1px solid var(--line)}.case-copy{display:grid;grid-template-columns:260px 1fr;gap:40px;padding:72px 0;border-top:1px solid var(--line)}.case-copy h3{font-size:clamp(34px,4vw,62px);font-weight:400;letter-spacing:-.065em;line-height:.94;margin:0}.case-copy p{font-size:clamp(20px,2vw,30px);line-height:1.08;letter-spacing:-.05em;margin:0}.next-link{display:grid;grid-template-columns:1fr auto;align-items:end;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:24px 0 34px;margin-bottom:90px}.next-link h2{font-size:clamp(60px,13vw,180px)}.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);margin-top:22px}.stat{background:rgba(10,10,10,.88);padding:18px}.stat b{display:block;font-weight:400;font-size:clamp(32px,5vw,64px);letter-spacing:-.07em;line-height:.9}
    .work-cms{padding:108px 0 120px}.work-cms-hero{display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,.55fr);gap:24px;align-items:end;border-bottom:1px solid var(--line);padding-bottom:24px;margin-bottom:24px}.work-cms-hero h2{font-size:clamp(54px,10vw,132px)}.cms-stat-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line)}.cms-stat-tile{background:rgba(10,10,10,.86);padding:16px;min-height:118px;display:grid;align-content:space-between}.cms-stat-tile b{font-weight:400;font-size:clamp(34px,5vw,70px);line-height:.86;letter-spacing:-.07em;color:var(--paper)}.work-cms-layout{display:grid;grid-template-columns:minmax(0,1fr) 420px;gap:24px;align-items:start}.project-card-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.project-card{border:1px solid var(--line);background:rgba(244,242,237,.04);overflow:hidden;min-width:0;transition:transform .35s cubic-bezier(.16,1,.3,1),border-color .35s,background .35s}.project-card:hover{transform:translateY(-2px);border-color:rgba(244,242,237,.24);background:rgba(244,242,237,.065)}.project-card-media{position:relative;aspect-ratio:16/10;background:#121212;overflow:hidden}.project-card-media img{width:100%;height:100%;object-fit:cover;display:block;filter:saturate(.86) contrast(1.05);transition:transform .7s cubic-bezier(.16,1,.3,1)}.project-card:hover .project-card-media img{transform:scale(1.045)}.status-pill{position:absolute;left:12px;top:12px;border:1px solid rgba(244,242,237,.24);background:rgba(10,10,10,.68);backdrop-filter:blur(12px);border-radius:999px;padding:7px 10px;color:var(--paper);font-size:11px;text-transform:uppercase;letter-spacing:.06em}.status-pill.draft{border-color:rgba(219,57,3,.5);color:#ffb39b}.project-card-body{padding:16px;display:grid;gap:14px}.project-card-title{display:grid;gap:8px}.project-card-title h3{font-weight:400;font-size:clamp(30px,4.4vw,58px);line-height:.9;letter-spacing:-.07em;margin:0}.project-card-title p{margin:0}.project-meta{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:var(--line);font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}.project-meta span{background:rgba(10,10,10,.82);padding:10px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.project-card-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.project-card-actions form{display:block;margin-left:auto}.project-edit{margin-top:0;padding:0;background:transparent;border:0}.project-edit summary{display:inline-flex;border:1px solid var(--line);background:rgba(244,242,237,.06);border-radius:999px;padding:10px 14px;font-size:13px;letter-spacing:-.05em}.project-edit[open]{flex-basis:100%;width:100%}.project-edit[open] summary{margin-bottom:14px;background:rgba(244,242,237,.12)}.project-edit .cms-form-wrap{border-top:1px solid var(--line);padding-top:14px}.new-project-panel{position:sticky;top:24px}.empty-state{border:1px solid var(--line);background:rgba(244,242,237,.035);padding:24px;color:var(--muted)}.admin-grid{display:grid;grid-template-columns:minmax(0,1fr) 410px;gap:24px;padding:108px 0 120px}.cms-form{display:grid;gap:18px}.cms-editor-head{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:end;border-bottom:1px solid var(--line);padding-bottom:18px}.cms-editor-head h2{font-size:clamp(38px,6vw,76px)}.cms-fieldset{border:1px solid var(--line);background:rgba(244,242,237,.035);padding:14px;display:grid;gap:14px}.cms-fieldset-title{display:flex;justify-content:space-between;gap:16px;color:var(--paper);font-size:14px;text-transform:uppercase;letter-spacing:.04em}.cms-fieldset-title span{color:var(--muted)}.cms-advanced{border-color:rgba(244,242,237,.16);background:rgba(10,10,10,.28)}.home-section-map{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.home-section-chip{border-radius:8px;text-align:left;display:grid;gap:4px;padding:10px;background:rgba(244,242,237,.045)}.home-section-chip strong{font-weight:400;color:var(--paper);font-size:14px}.home-section-chip span{color:var(--muted);font-size:12px}.cms-card-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;padding:28px 0 120px}.cms-card{min-height:260px;display:grid;align-content:space-between;border:1px solid var(--line);background:rgba(244,242,237,.045);padding:18px;transition:transform .35s cubic-bezier(.16,1,.3,1),border-color .35s,background .35s}.cms-card:hover{transform:translateY(-2px);border-color:rgba(244,242,237,.26);background:rgba(244,242,237,.07)}.cms-card h2{font-size:clamp(40px,6vw,72px)}.cms-actions{display:flex;gap:8px;flex-wrap:wrap}.admin-grid>aside{position:sticky;top:24px;align-self:start}label{display:grid;gap:7px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}input,textarea,select{width:100%;border:1px solid var(--line);background:rgba(244,242,237,.06);color:var(--paper);padding:12px;border-radius:8px;font:inherit;outline:none}input:focus,textarea:focus,select:focus{border-color:rgba(244,242,237,.34);background:rgba(244,242,237,.085)}textarea{min-height:118px;resize:vertical}form{display:grid;gap:14px}.row{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.list{display:grid;gap:12px}.item{display:grid;grid-template-columns:120px 1fr auto;gap:14px;align-items:center;border:1px solid var(--line);padding:10px;background:rgba(244,242,237,.035)}.item img{width:120px;aspect-ratio:16/9;object-fit:cover;background:#151515}details{border:1px solid var(--line);padding:14px;margin-top:12px;background:rgba(244,242,237,.035)}summary{cursor:pointer}.danger{background:#34110c;border-color:rgba(219,57,3,.45)}.login{min-height:100vh;display:grid;place-items:center;padding:24px;background:linear-gradient(180deg,rgba(10,10,10,.12),rgba(10,10,10,.85)),url('/assets/local/323795fc9c20f1ac.png') center/cover}.login .panel{width:min(440px,100%)}
    @keyframes riseIn{from{opacity:0;transform:translateY(48px)}to{opacity:1;transform:translateY(0)}}@keyframes wordIn{from{opacity:.001;filter:blur(14px);transform:translateY(30px)}to{opacity:1;filter:blur(0);transform:translateY(0)}}@keyframes posterIn{from{opacity:.001;transform:scale(1.08)}to{opacity:.48;transform:scale(1.04)}}@keyframes tickIn{from{opacity:.001;transform:translateY(120px)}to{opacity:1;transform:translateY(0)}}@keyframes tickDown{from{opacity:.001;transform:translateY(-120px)}to{opacity:1;transform:translateY(0)}}@media(max-width:920px){.topbar{bottom:14px}.topbar .wrap{width:calc(100vw - 28px);justify-content:space-between}.hero-row,.split,.admin-grid,.work-cms-hero,.work-cms-layout,.project-card-grid,.row,.case-copy,.reel-grid,.cms-card-grid{grid-template-columns:1fr}.reel-card{min-height:420px}.copy-large{margin:22px 0 0;text-align:left}.timeline,.sheet,.stat-grid,.work-spec-strip{grid-template-columns:1fr 1fr}.time-grid{grid-template-columns:repeat(3,1fr)}.time-tick:nth-child(even){display:none}.opening-copy{font-size:clamp(44px,13vw,78px)}.work-row{grid-template-columns:46px 1fr;gap:10px;padding:22px 0}.work-project,.work-year,.work-spec{grid-column:2}.work-thumb{display:none}.item{grid-template-columns:82px 1fr}.item form{grid-column:1/-1}h1{font-size:clamp(68px,24vw,132px)}}
  </style>
</head><body>${body}</body></html>`;
}

function workIndex(projects) {
  const featured = projects[0] || {};
  const heroMedia = featured.video ? `<video src="${escapeHtml(featured.video)}" poster="${escapeHtml(featured.image || '')}" autoplay muted loop playsinline></video>` : `<img src="${escapeHtml(featured.image || '/assets/local/323795fc9c20f1ac.png')}" alt="">`;
  const rows = projects.map((p, i) => {
    return `<a class="work-row" href="/work/${escapeHtml(p.slug)}"><span class="work-num">${String(i + 1).padStart(2, "0")}</span><strong class="work-title">${escapeHtml(p.title)}</strong><span class="work-project">${escapeHtml(p.project)}</span><span class="work-year">${escapeHtml(p.year)}</span><span class="work-spec">${escapeHtml(p.spec || p.discipline)}</span><img class="work-thumb" src="${escapeHtml(p.image)}" alt=""></a>`;
  }).join("");
  return shell("Selected Work - Anamorph", `<header class="topbar"><div class="wrap"><a class="brand" href="/">Anamorph</a><nav class="nav"><a class="pill" href="/">Home</a><a class="pill primary" href="/work">Work</a><a class="pill" href="/reels">Reels</a><a class="pill" href="/admin/work">CMS</a></nav></div></header><main><section class="opening"><div class="work-screening-poster">${heroMedia}</div><div class="work-screening-grade"></div><div class="time-grid"><div class="time-tick"><span>00:00</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>00:30</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>01:00</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>01:30</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>02:00</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div></div><div class="wrap"><div class="rec-badge">REC SELECTED WORK</div><h1 class="opening-copy"><span class="reveal-word">Selected</span> <span class="reveal-word">work</span><br><span class="reveal-word reveal-muted">cut</span> <span class="reveal-word reveal-muted">like</span> <span class="reveal-word reveal-muted">a</span> <span class="reveal-word reveal-muted">screening</span></h1><div class="work-count"><b>${projects.length} Films - 2025-2026</b><span>00:02:00:00</span></div><div class="work-spec-strip"><div class="work-spec-cell"><span class="eyebrow">Featured</span><strong>${escapeHtml(featured.title || 'Project')}</strong></div><div class="work-spec-cell"><span class="eyebrow">Discipline</span><strong>${escapeHtml(featured.discipline || 'Film')}</strong></div><div class="work-spec-cell"><span class="eyebrow">Latest Year</span><strong>${escapeHtml(featured.year || '2026')}</strong></div><div class="work-spec-cell"><span class="eyebrow">Archive</span><strong>${projects.length}</strong></div></div></div></section><section class="wrap section-head"><div><div class="eyebrow">(02) - All Work</div><h2>Screenings</h2></div><a class="pill primary" href="/admin/work">Upload Project</a></section><section class="wrap work-list">${rows || "<p>No projects published yet.</p>"}</section><section class="wrap next-link"><div><div class="eyebrow">(03) - Booking</div><h2>Let's roll</h2></div><a class="pill primary" href="/admin/work">Add Work</a></section></main>`);
}

function reelsPage(reels) {
  const cards = reels.map((r, i) => {
    const media = mediaHtml(r, "card");
    return `<article class="reel-card">${media}<div class="reel-meta"><div><span class="eyebrow">${String(i + 1).padStart(2, "0")} - Reel</span><h3>${escapeHtml(r.title)}</h3><p>${escapeHtml(r.caption || r.format || "")}</p></div><span class="eyebrow">${escapeHtml(r.duration || "00:15")}</span></div></article>`;
  }).join("");
  return shell("Reels - Anamorph", `<header class="topbar"><div class="wrap"><a class="brand" href="/">Anamorph</a><nav class="nav"><a class="pill" href="/">Home</a><a class="pill" href="/work">Work</a><a class="pill primary" href="/reels">Reels</a><a class="pill" href="/admin">CMS</a></nav></div></header><main><section class="opening"><div class="time-grid"><div class="time-tick"><span>00:00</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>00:07</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>00:15</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>00:30</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>00:45</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div></div><div class="wrap"><h1 class="opening-copy"><span class="reveal-word">Short-form</span> <span class="reveal-word">cuts</span><br><span class="reveal-word reveal-muted">built</span> <span class="reveal-word reveal-muted">to</span> <span class="reveal-word reveal-muted">hold</span> <span class="reveal-word reveal-muted">attention</span></h1><div class="work-count"><b>${reels.length} Reels - Motion CMS</b><span>00:00:45:00</span></div></div></section><section class="wrap section-head"><div><div class="eyebrow">(01) - Reels</div><h2>Social Cuts</h2></div><a class="pill primary" href="/admin">Upload Reel</a></section><section class="wrap reel-grid">${cards || "<p>No reels published yet.</p>"}</section></main>`);
}

function workDetailTemplatePage(project, projects = []) {
  if (!fs.existsSync(WORK_DETAIL_TEMPLATE)) return "";
  const next = nextProject(projects, project.slug) || {};
  let html = fs.readFileSync(WORK_DETAIL_TEMPLATE, "utf8");
  const replacements = [
    ["Citadel", next.title || "Selected Work"],
    ["citadel", next.slug || "work"],
    ["Meridian — Anamorph™", `${project.title || "Project"} — Anamorph™`],
    ["Meridian", project.title || ""],
    ["Brand Identity", project.discipline || ""],
    [">2026<", `>${escapeHtml(project.year || "")}<`],
    ["Identity &amp; Launch Film", escapeHtml(project.project || "")],
    ["Atlas Group", project.client || ""],
    ["RED Komodo 4K 24p", project.spec || ""],
    ["Master and Six Cutdowns", project.deliverables || ""],
    ["https://framerusercontent.com/assets/giTLgTG1Xb4gSWKMSMwml7NXZw.mp4", project.video || project.image || ""],
    ["https://www.youtube.com/watch?v=Sgxbx65IDeM", project.video || ""]
  ];
  replacements.forEach(([from, to]) => {
    html = html.split(from).join(String(to || ""));
  });
  const story = escapeHtml(project.story || "A cinematic project shaped around pace, texture, and retention.");
  html = html
    .replace("A new identity needed a film that could carry it — sixty days from first board to launch, and a name the market hadn’t heard yet.", story)
    .replace("We cut to the grade, not around it. Two-frame holds on the wordmark, hard cuts on the beat, nothing that lingers. The launch version ran 02:14; the boardroom sat through it twice.", "We cut to the grade, not around it. Holds, hard cuts, texture, and rhythm stay locked to the idea.")
    .replace("Lifted blacks and one warm accent pulled from the wordmark. The whole film sits inside the brand palette before the logo ever appears.", "Lifted blacks, restrained contrast, and one warm accent keep the whole film inside the brand palette.")
    .replace("The film opened the launch event and ran paid for six weeks. Average watch time held above ninety per cent.", "The film was finished for launch with social cutdowns, title work, and delivery-ready masters.");
  html = html.replace("</body>", `<script>window.__ANAMORPH_PROJECT__=${JSON.stringify({
    title: project.title || "",
    slug: project.slug || "",
    image: project.image || "",
    video: project.video || "",
    nextSlug: next.slug || "",
    nextTitle: next.title || ""
  })};</script></body>`);
  return html;
}

function projectPage(project, projects = []) {
  const templated = workDetailTemplatePage(project, projects);
  if (templated) return templated;
  const next = nextProject(projects, project.slug) || {};
  const heroMedia = mediaHtml(project, "hero");
  const media = mediaHtml(project, "detail");
  return shell(`${project.title} - Anamorph`, `<header class="topbar"><div class="wrap"><a class="brand" href="/">Anamorph</a><nav class="nav"><a class="pill primary" href="/work">Work</a><a class="pill" href="/reels">Reels</a><a class="pill" href="/">Home</a><a class="pill" href="/admin">CMS</a></nav></div></header><main><section class="hero compact"><div class="hero-media">${heroMedia}</div><div class="wrap hero-content"><div class="eyebrow">${escapeHtml(project.discipline)}</div><h1>${escapeHtml(project.title)}</h1><div class="timeline"><div class="tick">00:00<span>+</span></div><div class="tick">00:30<span>+</span></div><div class="tick">01:00<span>+</span></div><div class="tick">01:30<span>+</span></div><div class="tick">02:00<span>+</span></div></div></div></section><section class="wrap"><div class="section-head"><div><div class="eyebrow">(01) - The Sheet</div><h2>+</h2></div><span class="eyebrow">00:01:00:00</span></div><div class="sheet"><div class="sheet-item"><p class="eyebrow">Client</p><p>${escapeHtml(project.client)}</p></div><div class="sheet-item"><p class="eyebrow">Project</p><p>${escapeHtml(project.project)}</p></div><div class="sheet-item"><p class="eyebrow">Spec</p><p>${escapeHtml(project.spec)}</p></div><div class="sheet-item"><p class="eyebrow">Deliverables</p><p>${escapeHtml(project.deliverables)}</p></div></div></section><section class="wrap"><div class="section-head"><div><div class="eyebrow">(02) - The Master</div><h2>00:02:00:00</h2></div></div>${media}<div class="work-count"><b>ANAMORPH_${escapeHtml(project.title)}_MASTER.MP4</b><span>Editor - Noah Reyes</span></div></section><section class="wrap"><div class="case-copy"><h3>The Brief</h3><p>${escapeHtml(project.story || "A new identity needed a film that could carry it from first board to launch.")}</p></div><div class="case-copy"><h3>The Cut</h3><p>We cut to the grade, not around it. Holds, hard cuts, texture, and rhythm stay locked to the idea.</p></div><div class="case-copy"><h3>The Grade</h3><p>Lifted blacks, restrained contrast, and one warm accent keep the whole film inside the brand palette.</p></div><div class="case-copy"><h3>The Result</h3><p>The film was finished for launch with social cutdowns, title work, and delivery-ready masters.</p></div><div class="stat-grid"><div class="stat"><b>01</b><p>24H Reply Time</p></div><div class="stat"><b>02</b><p>Revision Rounds</p></div><div class="stat"><b>98%</b><p>On-time Delivery</p></div><div class="stat"><b>5D</b><p>First Cut</p></div></div></section><section class="wrap next-link"><div><div class="eyebrow">Next screening</div><h2>${escapeHtml(next.title || "Selected Work")}</h2></div><a class="pill primary" href="${next.slug ? `/work/${escapeHtml(next.slug)}` : "/work"}">Next</a></section></main>`);
}

function loginPage(error = "") {
  return shell("CMS Login", `<main class="login"><section class="panel glass"><div class="brand">Anamorph</div><p class="eyebrow">(CMS) - Login</p><h2>Studio Access</h2><p>Upload project posters, reels, and case-study copy into the local portfolio.</p>${error ? `<p style="color:#ff9b7d">${escapeHtml(error)}</p>` : ""}<form method="post" action="/login"><label>Username<input name="username" autocomplete="username" required></label><label>Password<input type="password" name="password" autocomplete="current-password" required></label><input type="submit" value="Login"></form></section></main>`);
}

function projectForm(project = {}) {
  const checked = project.published === false ? "" : "checked";
  return `<form method="post" action="/admin/projects" enctype="multipart/form-data"><input type="hidden" name="id" value="${escapeHtml(project.id || "")}"><div class="row"><label>Title<input name="title" value="${escapeHtml(project.title || "")}" required></label><label>Slug<input name="slug" value="${escapeHtml(project.slug || "")}" placeholder="auto from title"></label></div><div class="row"><label>Eyebrow<input name="eyebrow" value="${escapeHtml(project.eyebrow || "(01) - Selected Work")}"></label><label>Year<input name="year" value="${escapeHtml(project.year || "2026")}"></label></div><div class="row"><label>Project<input name="project" value="${escapeHtml(project.project || "")}"></label><label>Discipline<input name="discipline" value="${escapeHtml(project.discipline || "")}"></label></div><div class="row"><label>Client<input name="client" value="${escapeHtml(project.client || "")}"></label><label>Spec<input name="spec" value="${escapeHtml(project.spec || "")}"></label></div><label>Deliverables<input name="deliverables" value="${escapeHtml(project.deliverables || "")}"></label><label>Story<textarea name="story">${escapeHtml(project.story || "")}</textarea></label><div class="row"><label>Poster image<input type="file" name="image" accept="image/*"></label><label>Video file<input type="file" name="video" accept="video/*"></label></div><div class="row"><label>Google Drive image URL<input name="image_url" value="${escapeHtml(project.image || "")}" placeholder="Paste Drive image share link"></label><label>YouTube video URL<input name="video_url" value="${escapeHtml(project.video || "")}" placeholder="Paste YouTube link"></label></div><label><span><input type="checkbox" name="published" ${checked} style="width:auto"> Published</span></label><input type="submit" value="${project.id ? "Update project" : "Create project"}"></form>`;
}

function reelForm(reel = {}) {
  const checked = reel.published === false ? "" : "checked";
  return `<form method="post" action="/admin/reels" enctype="multipart/form-data"><input type="hidden" name="id" value="${escapeHtml(reel.id || "")}"><div class="row"><label>Title<input name="title" value="${escapeHtml(reel.title || "")}" required></label><label>Slug<input name="slug" value="${escapeHtml(reel.slug || "")}" placeholder="auto from title"></label></div><div class="row"><label>Duration<input name="duration" value="${escapeHtml(reel.duration || "00:15")}"></label><label>Format<input name="format" value="${escapeHtml(reel.format || "9:16 Reel")}"></label></div><label>Caption<textarea name="caption">${escapeHtml(reel.caption || "")}</textarea></label><div class="row"><label>Poster image<input type="file" name="image" accept="image/*"></label><label>Video file<input type="file" name="video" accept="video/*"></label></div><div class="row"><label>Google Drive image URL<input name="image_url" value="${escapeHtml(reel.image || "")}" placeholder="Paste Drive image share link"></label><label>YouTube video URL<input name="video_url" value="${escapeHtml(reel.video || "")}" placeholder="Paste YouTube link"></label></div><label><span><input type="checkbox" name="published" ${checked} style="width:auto"> Published</span></label><input type="submit" value="${reel.id ? "Update reel" : "Create reel"}"></form>`;
}

function homeForm(home = {}) {
  return `<form class="cms-form" method="post" action="/admin/home" enctype="multipart/form-data"><div class="cms-editor-head"><div><div class="eyebrow">Guided home editor</div><h2>Text & Images</h2><p>Scan the homepage, choose a section, then pick the exact text or image from that section.</p></div><button class="primary" type="button" data-scan-home>Scan Homepage</button></div><div class="cms-fieldset"><div class="cms-fieldset-title"><span>00</span><strong>Homepage sections</strong></div><label>Filter by section<select id="homeSectionFilter"><option value="">All homepage sections</option></select></label><div id="homeSectionMap" class="home-section-map"></div></div><datalist id="homeTextOptions"></datalist><datalist id="homeImageOptions"></datalist><div class="cms-fieldset"><div class="cms-fieldset-title"><span>01</span><strong>Change one text</strong></div><div class="row"><label>Current homepage text<input name="text_from" list="homeTextOptions" placeholder="Choose or paste current text"></label><label>New text<input name="text_to" placeholder="Type replacement text"></label></div></div><div class="cms-fieldset"><div class="cms-fieldset-title"><span>02</span><strong>Change one image</strong></div><div class="row"><label>Current image URL<input name="image_target" list="homeImageOptions" placeholder="Choose or paste current image URL"></label><label>New Google Drive image URL<input name="image_url" placeholder="Paste Drive image share link"></label></div><label>Or upload replacement image<input type="file" name="image" accept="image/*"></label></div><details class="cms-advanced" open><summary>Advanced saved replacements</summary><label>All text replacements<textarea name="text_replacements" placeholder="Anamorph => Your Brand&#10;Book a call => Start a project">${escapeHtml(pairsToText(home.text_replacements || []))}</textarea></label><label>All image replacements<textarea name="image_replacements" placeholder="/assets/local/323795fc9c20f1ac.png => https://drive.google.com/file/d/.../view">${escapeHtml(pairsToText(home.image_replacements || []))}</textarea></label></details><input type="submit" value="Save home page"><script>(function(){var state={texts:[],images:[],sections:[]};function clean(v){return (v||'').replace(/\s+/g,' ').trim();}function sectionName(el){var section=el&&el.closest&&el.closest('section,[data-framer-name],footer,header');if(!section)return 'Global';return section.getAttribute('data-framer-name')||section.id||section.tagName||'Global';}function uniqueItems(items){var seen={};return items.filter(function(item){var key=item.section+'::'+item.value;if(seen[key]||!item.value)return false;seen[key]=1;return true;}).slice(0,500);}function filtered(items){var section=document.getElementById('homeSectionFilter')?.value||'';return section?items.filter(function(item){return item.section===section;}):items;}function fill(list,items){var el=document.getElementById(list);if(!el)return;el.innerHTML='';filtered(items).forEach(function(item){var option=document.createElement('option');option.value=item.value;option.label=item.section;el.appendChild(option);});}function renderSections(){var select=document.getElementById('homeSectionFilter');var map=document.getElementById('homeSectionMap');if(!select||!map)return;select.innerHTML='<option value="">All homepage sections</option>';state.sections.forEach(function(section){var option=document.createElement('option');option.value=section;option.textContent=section;select.appendChild(option);});map.innerHTML='';state.sections.forEach(function(section){var textCount=state.texts.filter(function(item){return item.section===section;}).length;var imageCount=state.images.filter(function(item){return item.section===section;}).length;var button=document.createElement('button');button.type='button';button.className='home-section-chip';button.innerHTML='<strong>'+section+'</strong><span>'+textCount+' text / '+imageCount+' image</span>';button.addEventListener('click',function(){select.value=section;refresh();});map.appendChild(button);});}function refresh(){fill('homeTextOptions',state.texts);fill('homeImageOptions',state.images);}async function scan(){try{var res=await fetch('/',{cache:'no-store'});var html=await res.text();var doc=new DOMParser().parseFromString(html,'text/html');var blocked={SCRIPT:1,STYLE:1,NOSCRIPT:1};var texts=[];var walker=doc.createTreeWalker(doc.body,NodeFilter.SHOW_TEXT,{acceptNode:function(node){var parent=node.parentElement;if(!parent||blocked[parent.tagName])return NodeFilter.FILTER_REJECT;var text=clean(node.nodeValue);return text.length>1&&text.length<220?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_REJECT;}});while(walker.nextNode()){texts.push({value:clean(walker.currentNode.nodeValue),section:sectionName(walker.currentNode.parentElement)});}var images=[];doc.querySelectorAll('img').forEach(function(img){var section=sectionName(img);var src=img.getAttribute('src');if(src)images.push({value:src,section:section});(img.getAttribute('srcset')||'').split(',').forEach(function(part){var first=part.trim().split(/\s+/)[0];if(first)images.push({value:first,section:section});});});state.texts=uniqueItems(texts);state.images=uniqueItems(images);state.sections=Array.from(new Set(state.texts.concat(state.images).map(function(item){return item.section;}))).filter(Boolean);renderSections();refresh();}catch(e){}}document.getElementById('homeSectionFilter')?.addEventListener('change',refresh);document.querySelector('[data-scan-home]')?.addEventListener('click',scan);scan();})();</script></form>`;
}

function adminNav(active = "") {
  const pill = (href, label, key) => `<a class="pill ${active === key ? "primary" : ""}" href="${href}">${label}</a>`;
  return `<header class="topbar"><div class="wrap"><a class="brand" href="/admin">CMS</a><nav class="nav">${pill("/admin/home", "Home CMS", "home")}${pill("/admin/work", "Work CMS", "work")}${pill("/admin/reels", "Reels CMS", "reels")}<a class="pill" href="/">Site</a><form method="post" action="/logout"><button>Logout</button></form></nav></div></header>`;
}

function adminPage(data) {
  return shell("Anamorph CMS", `${adminNav()}<main class="wrap"><section class="opening"><div class="time-grid"><div class="time-tick"><span>HOME</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>WORK</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div><div class="time-tick"><span>REELS</span><span class="rule"></span><span class="plus">+</span><span class="rule"></span></div></div><div class="wrap"><h1 class="opening-copy"><span class="reveal-word">CMS</span> <span class="reveal-word">Control</span><br><span class="reveal-word reveal-muted">choose</span> <span class="reveal-word reveal-muted">a</span> <span class="reveal-word reveal-muted">page</span></h1><div class="work-count"><b>${(data.projects || []).length} Projects - ${(data.reels || []).length} Reels</b><span>ANAMORPH CMS</span></div></div></section><section class="section-head"><div><div class="eyebrow">(CMS) - Sections</div><h2>Edit Pages</h2></div></section><section class="cms-card-grid"><a class="cms-card" href="/admin/home"><div><div class="eyebrow">Home Page</div><h2>Home CMS</h2><p>Change homepage text, images, and original Framer content replacements.</p></div><span class="pill primary">Edit Home</span></a><a class="cms-card" href="/admin/work"><div><div class="eyebrow">Projects</div><h2>Work CMS</h2><p>Add, edit, publish, and delete project pages.</p></div><span class="pill primary">Edit Work</span></a><a class="cms-card" href="/admin/reels"><div><div class="eyebrow">Homepage Videos</div><h2>Reels CMS</h2><p>Change the first three homepage reel videos and the reels page.</p></div><span class="pill primary">Edit Reels</span></a></section></main>`);
}

function adminHomePage(data) {
  return shell("Home CMS - Anamorph", `${adminNav("home")}<main class="wrap admin-grid"><section><div class="eyebrow">(CMS) - Home Page</div><h2>Home Content</h2><p>Change home page text and images while the original Framer design, layout, and animation stay the same.</p><div class="panel">${homeForm(data.home || {})}</div></section><aside class="panel glass"><div class="eyebrow">(Preview)</div><h2>Home</h2><p>Use text replacement rows for copy and image replacement rows for visual assets.</p><a class="pill primary" href="/">Open Home</a><a class="pill" href="/#reels">Home Reels</a></aside></main>`);
}

function adminWorkPage(data) {
  const projects = data.projects || [];
  const published = projects.filter((p) => p.published !== false).length;
  const drafts = projects.length - published;
  const latestYear = projects.map((p) => p.year).filter(Boolean).sort().pop() || "2026";
  const cards = projects.map((p, i) => {
    const status = p.published === false ? "Draft" : "Published";
    const statusClass = p.published === false ? " draft" : "";
    return `<article class="project-card"><div class="project-card-media"><img src="${escapeHtml(p.image || '/assets/local/323795fc9c20f1ac.png')}" alt=""><span class="status-pill${statusClass}">${status}</span></div><div class="project-card-body"><div class="project-card-title"><div class="eyebrow">${String(i + 1).padStart(2, "0")} - /${escapeHtml(p.slug || '')}</div><h3>${escapeHtml(p.title || 'Untitled project')}</h3><p>${escapeHtml(p.project || p.discipline || 'Project')}</p></div><div class="project-meta"><span>${escapeHtml(p.year || 'Year')}</span><span>${escapeHtml(p.spec || p.discipline || 'Spec')}</span><span>${escapeHtml(p.client || 'Client')}</span><span>${escapeHtml(p.deliverables || 'Deliverables')}</span></div><div class="project-card-actions"><a class="pill primary" href="/work/${escapeHtml(p.slug || '')}">Preview</a><details class="project-edit"><summary>Edit</summary><div class="cms-form-wrap">${projectForm(p)}</div></details><form method="post" action="/admin/projects/delete" onsubmit="return confirm('Delete this project?')"><input type="hidden" name="id" value="${escapeHtml(p.id || '')}"><button class="danger">Delete</button></form></div></div></article>`;
  }).join("");
  return shell("Work CMS - Anamorph", `${adminNav("work")}<main class="wrap work-cms"><section class="work-cms-hero"><div><div class="eyebrow">(CMS) - Work Page</div><h2>Work Library</h2><p>Upload projects, update case-study text, swap posters or YouTube videos, and control what appears on the public work page.</p></div><div class="cms-stat-strip"><div class="cms-stat-tile"><span class="eyebrow">Projects</span><b>${projects.length}</b></div><div class="cms-stat-tile"><span class="eyebrow">Published</span><b>${published}</b></div><div class="cms-stat-tile"><span class="eyebrow">Drafts</span><b>${drafts}</b></div></div></section><section class="work-cms-layout"><div class="project-card-grid">${cards || '<div class="empty-state">No projects yet. Create the first project from the panel on the right.</div>'}</div><aside class="panel glass new-project-panel"><div class="eyebrow">(Upload) - New Case</div><h2>New Project</h2><p>Add poster images, Google Drive image links, local video files, or YouTube video links. Published items show on the live Work page.</p>${projectForm()}<div class="project-meta" style="margin-top:14px"><span>${latestYear}</span><span>${projects.length} Total</span></div></aside></section></main>`);
}

function adminReelsPage(data) {
  const reelItems = (data.reels || []).map((r) => `<div class="item"><img src="${escapeHtml(r.image)}" alt=""><div><strong>${escapeHtml(r.title)}</strong><p>/${escapeHtml(r.slug)} - ${escapeHtml(r.duration)} - ${r.published === false ? "Draft" : "Published"}</p><a class="pill" href="/reels">Preview</a></div><form method="post" action="/admin/reels/delete" onsubmit="return confirm('Delete this reel?')"><input type="hidden" name="id" value="${escapeHtml(r.id)}"><button class="danger">Delete</button></form></div>`).join("");
  const reelEdits = (data.reels || []).map((r) => `<details><summary>Edit ${escapeHtml(r.title)}</summary>${reelForm(r)}</details>`).join("");
  return shell("Reels CMS - Anamorph", `${adminNav("reels")}<main class="wrap admin-grid"><section><div class="eyebrow">(CMS) - Home Reels</div><h2>Homepage Videos</h2><p>These first three published reels replace only the videos inside the existing home page reels section. The Framer design stays the same.</p><div class="list">${reelItems || "<p>No reels yet.</p>"}</div><div style="margin-top:24px">${reelEdits}</div></section><aside class="panel glass"><div class="eyebrow">(Upload) - Home Reel Video</div><h2>Reel Slot</h2>${reelForm()}<div style="height:20px"></div><a class="pill primary" href="/reels">Preview Reels</a><a class="pill" href="/#reels">Preview Home</a></aside></main>`);
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
      slug: uniqueSlug(data, "projects", first(fields.slug) || title, id),
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
    const imageUrl = driveImage(first(fields.image_url));
    const videoUrl = first(fields.video_url);
    if (image) project.image = image;
    else if (imageUrl) project.image = imageUrl;
    if (video) project.video = video;
    else if (videoUrl) project.video = videoUrl;
    if (!project.image) project.image = "/assets/local/4408de2269c8641c.jpg";
    if (existing) Object.assign(existing, project);
    else data.projects.unshift(project);
    await saveCms(data);
    redirect(res, "/admin/work");
  } catch (error) {
    send(res, 400, shell("CMS Error", `<main class="login"><section class="panel glass"><h1>Error</h1><p>${escapeHtml(error.message)}</p><a class="pill" href="/admin">Back</a></section></main>`));
  }
}

async function saveReel(req, res) {
  try {
    const { fields, files } = await parseForm(req);
    const data = await loadCms();
    data.reels = data.reels || [];
    const id = first(fields.id) || crypto.randomUUID();
    const existing = data.reels.find((r) => r.id === id);
    const reel = { ...(existing || { id, created_at: new Date().toISOString() }) };
    const title = first(fields.title) || reel.title || "Untitled Reel";
    Object.assign(reel, {
      title,
      slug: uniqueSlug(data, "reels", first(fields.slug) || title, id),
      duration: first(fields.duration) || reel.duration || "",
      format: first(fields.format) || reel.format || "",
      caption: first(fields.caption) || reel.caption || "",
      published: first(fields.published) === "on",
      updated_at: new Date().toISOString()
    });
    const image = await uploadFile(files.image, "image");
    const video = await uploadFile(files.video, "video");
    const imageUrl = driveImage(first(fields.image_url));
    const videoUrl = first(fields.video_url);
    if (image) reel.image = image;
    else if (imageUrl) reel.image = imageUrl;
    if (video) reel.video = video;
    else if (videoUrl) reel.video = videoUrl;
    if (!reel.image) reel.image = "/assets/local/323795fc9c20f1ac.png";
    if (existing) Object.assign(existing, reel);
    else data.reels.unshift(reel);
    await saveCms(data);
    redirect(res, "/admin/reels");
  } catch (error) {
    send(res, 400, shell("CMS Error", `<main class="login"><section class="panel glass"><h1>Error</h1><p>${escapeHtml(error.message)}</p><a class="pill" href="/admin">Back</a></section></main>`));
  }
}

async function saveHome(req, res) {
  try {
    const { fields, files } = await parseForm(req);
    const data = await loadCms();
    const home = {
      text_replacements: textToPairs(first(fields.text_replacements)),
      image_replacements: textToPairs(first(fields.image_replacements)),
      updated_at: new Date().toISOString()
    };
    appendPair(home.text_replacements, first(fields.text_from), first(fields.text_to));
    const target = first(fields.image_target);
    const uploaded = await uploadFile(files.image, "image");
    const imageUrl = driveImage(first(fields.image_url));
    const replacement = uploaded || imageUrl;
    if (target && replacement) {
      home.image_replacements.push({ from: target.trim(), to: replacement });
    }
    data.home = home;
    await saveCms(data);
    redirect(res, "/admin/home");
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
  redirect(res, "/admin/work");
}

async function deleteReel(req, res) {
  const { fields } = await parseForm(req);
  const data = await loadCms();
  const id = first(fields.id);
  data.reels = (data.reels || []).filter((r) => r.id !== id);
  await saveCms(data);
  redirect(res, "/admin/reels");
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
  const reels = publicReels(data);

  if (req.method === "GET" && pathname === "/api/projects") return send(res, 200, JSON.stringify({ projects }), "application/json; charset=utf-8");
  if (req.method === "GET" && pathname === "/api/reels") return send(res, 200, JSON.stringify({ reels }), "application/json; charset=utf-8");
  if (req.method === "GET" && pathname === "/api/home") return send(res, 200, JSON.stringify({ home: publicHome(data) }), "application/json; charset=utf-8");
  if (req.method === "GET" && pathname === "/login") return send(res, 200, loginPage());
  if (req.method === "GET" && pathname === "/admin") return loggedIn ? send(res, 200, adminPage(data)) : redirect(res, "/login");
  if (req.method === "GET" && pathname === "/admin/home") return loggedIn ? send(res, 200, adminHomePage(data)) : redirect(res, "/login");
  if (req.method === "GET" && pathname === "/admin/work") return loggedIn ? send(res, 200, adminWorkPage(data)) : redirect(res, "/login");
  if (req.method === "GET" && pathname === "/admin/reels") return loggedIn ? send(res, 200, adminReelsPage(data)) : redirect(res, "/login");
  if (req.method === "POST" && pathname === "/admin/home") return loggedIn ? saveHome(req, res) : redirect(res, "/login");
  if (req.method === "POST" && pathname === "/admin/projects") return loggedIn ? saveProject(req, res) : redirect(res, "/login");
  if (req.method === "POST" && pathname === "/admin/projects/delete") return loggedIn ? deleteProject(req, res) : redirect(res, "/login");
  if (req.method === "POST" && pathname === "/admin/reels") return loggedIn ? saveReel(req, res) : redirect(res, "/login");
  if (req.method === "POST" && pathname === "/admin/reels/delete") return loggedIn ? deleteReel(req, res) : redirect(res, "/login");
  if (req.method === "GET" && pathname === "/work") return send(res, 200, workIndex(projects));
  if (req.method === "GET" && pathname === "/reels") return send(res, 200, reelsPage(reels));
  if (req.method === "GET" && pathname.startsWith("/work/")) {
    const slug = pathname.split("/")[2];
    const project = projects.find((p) => p.slug === slug);
    if (!project) return send(res, 404, "Project not found", "text/plain; charset=utf-8");
    return send(res, 200, projectPage(project, projects));
  }

  send(res, 404, "Not found", "text/plain; charset=utf-8");
};
