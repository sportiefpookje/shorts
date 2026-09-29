// Review: live 9:16-preview in de browser (zelfde layout- en ondertitellogica als de render)
const S = 0.5; // canvas 540x960 = de helft van 1080x1920
// libass rekent de lettergrootte als winAscent+winDescent, de browser als em: Montserrat = 1,562 em
const ASS_FONT = 1 / 1.562;
const cv = document.getElementById("cv"), ctx = cv.getContext("2d");
const vid = document.getElementById("vid");
let clips = [], cur = null, showAll = false;

// ---------- Data ----------
async function load(keepId) {
  let url = "/api/clips";
  if (JOB_ID) url += `?job=${JOB_ID}`;
  else if (showAll) url += "?status=all";
  const list = await api(url);
  clips = showAll || JOB_ID ? list : list.filter(c => c.status === "pending");
  document.getElementById("empty").hidden = clips.some(c => c.status === "pending") || (showAll && clips.length);
  document.getElementById("review").hidden = !clips.length || !document.getElementById("empty").hidden;
  renderList();
  const next = clips.find(c => c.id === keepId) || clips.find(c => c.status === "pending") || clips[0];
  if (next) select(next.id);
}

function renderList() {
  const pending = clips.filter(c => c.status === "pending").length;
  document.getElementById("list-count").textContent = `${pending} te beoordelen`;
  document.getElementById("list").innerHTML = clips.map(c => `
    <div class="item ${cur && c.id === cur.id ? "active" : ""} ${c.status !== "pending" ? "done" : ""}" data-id="${c.id}">
      <div class="row" style="gap:6px;margin-bottom:3px">
        <span class="score ${c.score >= 8 ? "hi" : ""}">${Math.round(c.score)}</span>
        <span class="small muted">${(c.end - c.start).toFixed(0)} s</span>
        <span class="grow"></span>
        ${c.status === "approved" ? '<span class="chip ok">✓</span>' : c.status === "rejected" ? '<span class="chip bad">✕</span>' : ""}
      </div>
      <div class="t">${esc(c.title || "(geen titel)")}</div>
    </div>`).join("");
  document.querySelectorAll("#list .item").forEach(el => el.onclick = () => select(+el.dataset.id));
}

function select(id) {
  cur = clips.find(c => c.id === id);
  if (!cur) return;
  groupsCache = null;
  const src = `/media/source/${cur.id}`;
  if (!vid.src.endsWith(src)) { vid.src = src; }
  vid.currentTime = Math.max(0, cur.start - cur.src_offset);
  document.getElementById("e-title").value = cur.title;
  document.getElementById("e-hook").value = cur.hook;
  document.getElementById("e-desc").value = cur.description;
  document.getElementById("e-tags").value = cur.hashtags;
  document.getElementById("e-caption").value = wordsIn(cur).map(w => w[2]).join(" ");
  document.getElementById("e-score").textContent = Math.round(cur.score) + "/10";
  document.getElementById("e-score").className = "score " + (cur.score >= 8 ? "hi" : "");
  document.getElementById("e-reason").textContent = cur.reason;
  updateStatus();
  updateLayoutUI();
  updateTitleCount();
  renderList();
  const item = document.querySelector(`#list .item[data-id="${id}"]`);
  if (item) item.scrollIntoView({ block: "nearest" });
  vid.play().catch(() => {});
}

function updateStatus() {
  const st = { pending: "", approved: '<span class="chip ok">goedgekeurd</span>', rejected: '<span class="chip bad">afgekeurd</span>' };
  document.getElementById("e-status").innerHTML = st[cur.status] || "";
  const r = {
    none: "", queued: "Wacht op render…", rendering: '<span class="spinner"></span> Renderen…',
    done: `✓ Gerenderd · <a href="/media/short/${cur.id}" target="_blank">bekijk eindresultaat</a>`,
    error: `<span style="color:var(--bad)">Render mislukt: ${esc(cur.render_error.slice(-300))}</span>`,
  };
  document.getElementById("render-info").innerHTML = cur.status === "approved" ? (r[cur.render_status] || "") : "";
}

async function save(fields) {
  if (!cur) return;
  const id = cur.id;
  const updated = await api(`/api/clips/${id}`, { method: "PATCH", json: fields });
  const i = clips.findIndex(c => c.id === id);
  if (i >= 0) clips[i] = updated;
  if (cur && cur.id === id) { cur = updated; groupsCache = null; updateStatus(); }
  renderList();
  return updated;
}
const saveText = debounce(() => save({
  title: document.getElementById("e-title").value,
  hook: document.getElementById("e-hook").value,
  description: document.getElementById("e-desc").value,
  hashtags: document.getElementById("e-tags").value,
}), 500);
["e-title", "e-hook", "e-desc", "e-tags"].forEach(id => document.getElementById(id).addEventListener("input", () => {
  if (id === "e-hook") cur.hook = document.getElementById(id).value; // direct zichtbaar in preview
  updateTitleCount();
  saveText();
}));
document.getElementById("e-caption").addEventListener("change", e => save({ caption_text: e.target.value }));

function updateTitleCount() {
  const n = document.getElementById("e-title").value.length;
  const el = document.getElementById("title-count");
  el.textContent = `${n}/60`;
  el.className = "count" + (n > 60 ? " over" : "");
}

// ---------- Layout ----------
function updateLayoutUI() {
  document.querySelectorAll("[data-layout]").forEach(b => b.classList.toggle("sel", b.dataset.layout === cur.layout));
  const splitOk = !!(cur.framing && cur.framing.facecam);
  document.querySelector('[data-layout="split"]').disabled = !splitOk;
  document.querySelector('[data-layout="split"]').title = splitOk ? "Facecam boven, game onder" : "Geen facecam gevonden in deze clip";
  document.querySelector('[data-layout="track"]').disabled = !(cur.framing && cur.framing.track);
  const showPos = cur.layout === "center" || cur.layout === "split";
  document.getElementById("pos-wrap").hidden = !showPos;
  document.getElementById("pos-label").textContent = cur.layout === "split" ? "Positie gameplay-uitsnede" : "Positie uitsnede";
  document.getElementById("e-pos").value = cur.layout === "split" ? (cur.framing.game_cx ?? 0.5) : (cur.framing.cx ?? 0.5);
}
document.querySelectorAll("[data-layout]").forEach(b => b.onclick = () => {
  cur.layout = b.dataset.layout;
  updateLayoutUI();
  save({ layout: cur.layout });
});
const savePos = debounce(() => save({ framing: cur.layout === "split" ? { game_cx: cur.framing.game_cx } : { cx: cur.framing.cx } }), 400);
document.getElementById("e-pos").addEventListener("input", e => {
  const v = parseFloat(e.target.value);
  if (cur.layout === "split") cur.framing.game_cx = v; else cur.framing.cx = v;
  savePos();
});

// ---------- Tekenen ----------
function cropX(t, W, H) {
  const cw = H * 9 / 16, maxX = Math.max(W - cw, 0), fr = cur.framing || {};
  const clamp = v => Math.min(Math.max(v, 0), maxX);
  if (cur.layout === "track" && fr.track) {
    const keys = fr.track, px = keys.map(k => clamp(k[1] * W - cw / 2));
    let x = px[0];
    for (let i = 1; i < keys.length; i++) {
      x += (px[i] - px[i - 1]) * Math.min(Math.max((t - keys[i][0]) / 0.4, 0), 1);
    }
    return clamp(x);
  }
  return clamp((fr.cx ?? 0.5) * W - cw / 2);
}

function drawCover(sx, sy, sw, sh, dx, dy, dw, dh) {
  // Zoals ffmpeg scale=...:force_original_aspect_ratio=increase + crop
  const r = Math.max(dw / sw, dh / sh), cw = dw / r, ch = dh / r;
  ctx.drawImage(vid, sx + (sw - cw) / 2, sy + (sh - ch) / 2, cw, ch, dx, dy, dw, dh);
}

function drawFrame() {
  const W = vid.videoWidth, H = vid.videoHeight;
  if (!W || !cur) return;
  const t = vid.currentTime;
  let layout = cur.layout;
  if ((layout === "track" || layout === "center") && W / H < 0.9) layout = "blur";
  ctx.clearRect(0, 0, 540, 960);
  if (layout === "track" || layout === "center") {
    const cw = H * 9 / 16;
    ctx.drawImage(vid, cropX(t, W, H), 0, cw, H, 0, 0, 540, 960);
  } else if (layout === "split" && cur.framing.facecam) {
    const [fx, fy, fw, fh] = cur.framing.facecam;
    drawCover(fx * W, fy * H, fw * W, fh * H, 0, 0, 540, 384);
    const gw = Math.min(H * 1080 / 1152, W);
    const gx = Math.min(Math.max((cur.framing.game_cx ?? 0.5) * W - gw / 2, 0), W - gw);
    drawCover(gx, 0, gw, H, 0, 384, 540, 576);
  } else {
    ctx.filter = "blur(14px) brightness(0.93)";
    drawCover(0, 0, W, H, -20, -20, 580, 1000);
    ctx.filter = "none";
    const r = Math.min(540 / W, 960 / H);
    ctx.drawImage(vid, 0, 0, W, H, (540 - W * r) / 2, (960 - H * r) / 2, W * r, H * r);
  }
  const rel = t + cur.src_offset - cur.start;
  drawHook(rel);
  drawCaptions(rel, layout);
}

function wordsIn(c) {
  return (c.words || []).filter(w => w[1] > c.start && w[0] < c.end);
}

let groupsCache = null;
function groups() {
  if (groupsCache) return groupsCache;
  const ws = wordsIn(cur).map(w => [w[0] - cur.start, w[1] - cur.start, w[2]]);
  const out = [];
  let g = [];
  for (const w of ws) {
    if (g.length) {
      const gap = w[0] - g[g.length - 1][1];
      const chars = g.reduce((a, x) => a + x[2].length + 1, 0) + w[2].length;
      if (g.length >= CAP.max_words || chars > CAP.max_chars || gap > 0.45 || /[.!?,]$/.test(g[g.length - 1][2])) { out.push(g); g = []; }
    }
    g.push(w);
  }
  if (g.length) out.push(g);
  return (groupsCache = out);
}

function drawCaptions(rel, layout) {
  if (!SETTINGS.captions) return;
  const gs = groups(), dur = cur.end - cur.start;
  for (let gi = 0; gi < gs.length; gi++) {
    const g = gs[gi];
    const next = gi + 1 < gs.length ? gs[gi + 1][0][0] : dur;
    const gEnd = Math.min(next, g[g.length - 1][1] + 0.5, dur);
    if (rel < g[0][0] || rel >= gEnd) continue;
    let active = 0;
    g.forEach((w, i) => { if (rel >= w[0]) active = i; });
    const words = g.map(w => SETTINGS.caption_uppercase ? w[2].toUpperCase() : w[2]);
    const pop = Math.min(1, 0.7 + (rel - g[0][0]) / 0.09 * 0.3);
    ctx.save();
    ctx.translate(270, (CAP.y[layout] || 1370) * S);
    ctx.scale(pop, pop);
    ctx.font = `${CAP.cap_size * S * ASS_FONT}px "Montserrat ExtraBold"`;
    ctx.textBaseline = "middle";
    ctx.lineJoin = "round";
    const space = ctx.measureText(" ").width;
    const widths = words.map(w => ctx.measureText(w).width);
    const total = widths.reduce((a, b) => a + b, 0) + space * (words.length - 1);
    if (total > 540 - 120 * S) { const f = (540 - 120 * S) / total; ctx.scale(f, f); }
    let x = -total / 2;
    words.forEach((w, i) => {
      ctx.lineWidth = 8 * S * 2;
      ctx.strokeStyle = "#000";
      ctx.shadowColor = "rgba(0,0,0,.5)"; ctx.shadowOffsetX = ctx.shadowOffsetY = 3 * S;
      ctx.strokeText(w, x, 0);
      ctx.shadowColor = "transparent";
      ctx.fillStyle = i === active ? SETTINGS.caption_color : "#fff";
      ctx.fillText(w, x, 0);
      x += widths[i] + space;
    });
    ctx.restore();
    break;
  }
}

function drawHook(rel) {
  const text = (cur.hook || "").trim();
  if (!text || !SETTINGS.hook_overlay || rel < 0 || rel > CAP.hook_seconds) return;
  ctx.save();
  ctx.font = `${CAP.hook_size * S * ASS_FONT}px "Montserrat ExtraBold"`;
  ctx.textBaseline = "top";
  const maxW = 540 - 2 * 90 * S - 2 * 22 * S;
  const lines = [];
  let line = "";
  for (const w of text.split(/\s+/)) {
    const test = line ? line + " " + w : w;
    if (ctx.measureText(test).width > maxW && line) { lines.push(line); line = w; } else line = test;
  }
  lines.push(line);
  if (lines.length === 2) { // libass verdeelt regels gelijkmatig (WrapStyle 0)
    const ws = text.split(/\s+/);
    let best = null;
    for (let i = 1; i < ws.length; i++) {
      const a = ws.slice(0, i).join(" "), b = ws.slice(i).join(" ");
      const m = Math.max(ctx.measureText(a).width, ctx.measureText(b).width);
      if (m <= maxW && (!best || m < best[0])) best = [m, a, b];
    }
    if (best) { lines[0] = best[1]; lines[1] = best[2]; }
  }
  const lh = CAP.hook_size * S * ASS_FONT * 1.25, pad = 22 * S;
  const fade = Math.min(1, rel / 0.08, (CAP.hook_seconds - rel) / 0.25);
  ctx.globalAlpha = Math.max(0, fade);
  lines.forEach((l, i) => {
    const w = ctx.measureText(l).width, y = CAP.hook_y * S + i * lh;
    ctx.fillStyle = "#fff";
    ctx.fillRect(270 - w / 2 - pad, y - pad * 0.6, w + 2 * pad, lh + pad * 0.6);
    ctx.fillStyle = "#000";
    ctx.textAlign = "center";
    ctx.fillText(l, 270, y);
  });
  ctx.restore();
}

// Afspelen: loop binnen [start, end]
function tick() {
  if (cur && vid.readyState >= 2) {
    const endF = cur.end - cur.src_offset, startF = cur.start - cur.src_offset;
    if (vid.currentTime >= endF || vid.currentTime < startF - 0.5) vid.currentTime = startF;
    drawFrame();
  }
  if (cur) updateTimeline();
  document.getElementById("paused").hidden = !vid.paused;
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);
document.fonts.load(`46px "Montserrat ExtraBold"`);

function togglePlay() { if (vid.paused) vid.play(); else vid.pause(); }
document.getElementById("phone").onclick = togglePlay;

// ---------- Tijdlijn ----------
const tl = document.getElementById("tl");
const pct = t => 100 * (t - cur.win_start) / (cur.win_end - cur.win_start);
function updateTimeline() {
  document.getElementById("tl-sel").style.left = pct(cur.start) + "%";
  document.getElementById("tl-sel").style.width = (pct(cur.end) - pct(cur.start)) + "%";
  document.getElementById("h-start").style.left = pct(cur.start) + "%";
  document.getElementById("h-end").style.left = pct(cur.end) + "%";
  document.getElementById("tl-head").style.left = pct(vid.currentTime + cur.src_offset) + "%";
  document.getElementById("t-start").textContent = fmtTime(cur.start);
  document.getElementById("t-end").textContent = fmtTime(cur.end);
  const d = cur.end - cur.start;
  document.getElementById("t-dur").innerHTML = `<b style="color:${d > SETTINGS.max_duration ? "var(--bad)" : "inherit"}">${d.toFixed(1)} s</b>`;
}
const timeAt = e => {
  const r = tl.getBoundingClientRect();
  return cur.win_start + Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1) * (cur.win_end - cur.win_start);
};
const saveTimes = debounce(() => save({ start: cur.start, end: cur.end }), 400);
let drag = null;
document.getElementById("h-start").onmousedown = e => { drag = "start"; e.stopPropagation(); };
document.getElementById("h-end").onmousedown = e => { drag = "end"; e.stopPropagation(); };
tl.onmousedown = e => { vid.currentTime = timeAt(e) - cur.src_offset; };
document.addEventListener("mousemove", e => {
  if (!drag) return;
  const t = timeAt(e);
  if (drag === "start") cur.start = Math.min(t, cur.end - 1);
  else cur.end = Math.max(t, cur.start + 1);
  groupsCache = null;
  vid.currentTime = (drag === "start" ? cur.start : Math.max(cur.start, cur.end - 2)) - cur.src_offset;
});
document.addEventListener("mouseup", () => { if (drag) { drag = null; saveTimes(); } });

function nudge(which, delta) {
  cur[which] = Math.min(Math.max(cur[which] + delta, cur.win_start), cur.win_end);
  if (cur.end - cur.start < 1) return;
  groupsCache = null;
  vid.currentTime = (which === "start" ? cur.start : Math.max(cur.start, cur.end - 2.5)) - cur.src_offset;
  vid.play().catch(() => {});
  saveTimes();
}
document.querySelectorAll("[data-nudge]").forEach(b => b.onclick = () => {
  const [w, d] = b.dataset.nudge.split(",");
  nudge(w, parseFloat(d));
});

// ---------- Beslissen ----------
async function decide(status) {
  if (!cur) return;
  const id = cur.id;
  await save({
    status,
    title: document.getElementById("e-title").value,
    hook: document.getElementById("e-hook").value,
    description: document.getElementById("e-desc").value,
    hashtags: document.getElementById("e-tags").value,
  });
  toast(status === "approved" ? "✓ Goedgekeurd — wordt gerenderd" : "✕ Afgekeurd", 1400);
  const idx = clips.findIndex(c => c.id === id);
  const next = clips.slice(idx + 1).find(c => c.status === "pending") || clips.find(c => c.status === "pending");
  if (next) select(next.id);
  else load();
}
document.getElementById("approve").onclick = () => decide("approved");
document.getElementById("reject").onclick = () => decide("rejected");

function step(d) {
  const i = clips.findIndex(c => c.id === cur.id);
  const n = clips[(i + d + clips.length) % clips.length];
  if (n) select(n.id);
}

document.addEventListener("keydown", e => {
  if (["INPUT", "TEXTAREA"].includes(e.target.tagName)) {
    if (e.key === "Escape") e.target.blur();
    return;
  }
  const k = e.key.toLowerCase();
  const actions = {
    " ": togglePlay, a: () => decide("approved"), r: () => decide("rejected"),
    j: () => step(-1), k: () => step(1), arrowup: () => step(-1), arrowdown: () => step(1),
    q: () => nudge("start", -0.5), w: () => nudge("start", 0.5),
    o: () => nudge("end", -0.5), p: () => nudge("end", 0.5),
    b: () => { vid.currentTime = Math.max(cur.start, cur.end - 3) - cur.src_offset; vid.play(); },
  };
  if (actions[k] && cur) { e.preventDefault(); actions[k](); }
});

document.getElementById("all-toggle").onchange = e => { showAll = e.target.checked; load(cur && cur.id); };
document.getElementById("show-all").onclick = () => { showAll = true; document.getElementById("all-toggle").checked = true; load(); };

// Renderstatus bijwerken
setInterval(async () => {
  if (!cur || cur.status !== "approved" || cur.render_status === "done") return;
  const fresh = (await api(JOB_ID ? `/api/clips?job=${JOB_ID}` : "/api/clips?status=approved")).find(c => c.id === cur.id);
  if (fresh) { cur.render_status = fresh.render_status; cur.render_error = fresh.render_error; updateStatus(); }
}, 2500);

load();
