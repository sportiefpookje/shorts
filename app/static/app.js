// Gedeelde helpers
async function api(path, opts = {}) {
  const o = { ...opts };
  if (o.json !== undefined) {
    o.body = JSON.stringify(o.json);
    o.headers = { "Content-Type": "application/json", ...(o.headers || {}) };
    delete o.json;
  }
  const r = await fetch(path, o);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    toast("Fout: " + msg);
    throw new Error(msg);
  }
  return r.json();
}

function toast(msg, ms = 2600) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtTime(t) {
  t = Math.max(0, t);
  const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = (t % 60).toFixed(1).padStart(4, "0");
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + s;
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

async function refreshBadge() {
  try {
    const jobs = await (await fetch("/api/jobs")).json();
    const n = jobs.reduce((a, j) => a + (j.n_pending || 0), 0);
    const b = document.getElementById("nav-pending");
    if (b) { b.textContent = n; b.hidden = n === 0; }
  } catch (e) {}
}
refreshBadge();
setInterval(refreshBadge, 5000);
