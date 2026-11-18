/* ReaVector Image Studio — one unified pipeline (Cloudflare only).
   Preserve mode keeps the real product pixels; transparent mode returns RGBA. */
import { headers } from "/gen.js";

const $ = (id) => document.getElementById(id);
const mainEl = $("main"), refsEl = $("refs"), mainPrev = $("mainPrev"), refPrev = $("refPrev");
const promptEl = $("prompt"), preserveEl = $("preserve"), outputEl = $("output"), modelEl = $("model");
const goEl = $("go"), statusEl = $("status"), metaEl = $("meta");
const origEl = $("orig"), resultEl = $("result"), understoodEl = $("understood");
const downloads = $("downloads"), dlPng = $("dlPng"), dlJpg = $("dlJpg");
const prog = $("prog"), countEl = $("count"), fillEl = $("fill"), stageTxt = $("stageTxt");

let mainFile = null, refFiles = [], resultUrl = "";

function tick({ remaining, pct }) {
  prog.hidden = false;
  countEl.textContent = Math.ceil(remaining) + "s";
  fillEl.style.width = pct + "%";
}

mainEl.addEventListener("change", async () => {
  mainFile = mainEl.files[0] || null;
  if (!mainFile) return;
  mainOrig(mainFile);
  statusEl.textContent = "Photo: " + mainFile.name + " — analysing…";
  try {
    const fd = new FormData();
    fd.append("image", mainFile);
    const r = await fetch("/api/image/analyze", { method: "POST", headers: headers(), body: fd });
    const j = await r.json().catch(() => ({}));
    if (r.ok && j.understood) showUnderstood(j.understood);
    statusEl.textContent = "Ready — describe the background and press Generate.";
  } catch (e) {
    statusEl.textContent = "Ready (analysis skipped).";
  }
});

function mainOrig(file) {
  origEl.src = URL.createObjectURL(file);
}

refsEl.addEventListener("change", () => {
  refFiles = Array.from(refsEl.files).slice(0, 3);
  refPrev.innerHTML = "";
  refFiles.forEach((f) => {
    const img = document.createElement("img");
    img.className = "refprev"; img.src = URL.createObjectURL(f); img.hidden = false;
    refPrev.appendChild(img);
  });
});

function showUnderstood(u) {
  understoodEl.hidden = false;
  const rows = Object.entries(u).map(([k, v]) => `<div class="kv"><span>${k}</span><span>${Array.isArray(v) ? v.join(", ") : v}</span></div>`).join("");
  understoodEl.innerHTML = `<h4>What ReaVector understood</h4>${rows}`;
}

goEl.addEventListener("click", async () => {
  const btn = goEl; btn.disabled = true;
  const est = mainFile ? 20 : 12;
  const t0 = Date.now();
  prog.hidden = false; stageTxt.textContent = mainFile ? "Preparing product…" : "Generating…";
  const timer = setInterval(() => tick({
    remaining: Math.max(0, est - (Date.now() - t0) / 1000),
    pct: Math.min(95, ((Date.now() - t0) / 1000 / est) * 100),
  }), 1000);

  try {
    const fd = new FormData();
    if (mainFile) fd.append("image", mainFile);
    refFiles.forEach((f, i) => fd.append("reference" + (i + 1), f));
    fd.append("prompt", promptEl.value.trim());
    fd.append("preserve", preserveEl.checked ? "1" : "0");
    fd.append("transparent", outputEl.value === "transparent" ? "1" : "0");
    fd.append("model", modelEl.value);

    const r = await fetch("/api/image/generate", { method: "POST", headers: headers(), body: fd });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || "generation failed");

    resultUrl = new URL(j.url, location.origin).href;
    resultEl.src = resultUrl;
    downloads.style.display = "flex";
    dlPng.href = resultUrl;
    dlPng.download = j.artifact;
    metaEl.textContent = `${j.mode} · ${j.background || ""} · refs ${j.refs_used || 0}`;
    if (j.understood) showUnderstood(j.understood);
    countEl.textContent = "0s"; fillEl.style.width = "100%";
    statusEl.textContent = j.transparent ? "Done — transparent PNG." : "Done — your product is preserved.";
    setTimeout(() => { prog.hidden = true; }, 900);
  } catch (e) {
    statusEl.textContent = "Error: " + (e.message || e);
    prog.hidden = true;
  } finally {
    clearInterval(timer);
    btn.disabled = false;
  }
});

dlJpg.addEventListener("click", () => {
  if (!resultUrl) return;
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.onload = () => {
    const c = document.createElement("canvas");
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(img, 0, 0);
    c.toBlob((b) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(b); a.download = "reavector.jpg"; a.click();
    }, "image/jpeg", 0.92);
  };
  img.src = resultUrl;
});