import { generate, registry, configured, headers } from "/gen.js";

const $ = (id) => document.getElementById(id);
const fileEl = $("file"), drop = $("drop"), statusEl = $("status"), preview = $("preview"), meta = $("meta");
const prog = $("prog"), countEl = $("count"), fillEl = $("fill"), stageTxt = $("stageTxt");
function tick({ remaining, pct }) { prog.hidden = false; countEl.textContent = Math.ceil(remaining) + "s"; fillEl.style.width = pct + "%"; }
const mode = $("mode"), modelSel = $("model"), prompt = $("prompt"), steps = $("steps");
let MODELS = [], file = null;

steps.addEventListener("input", () => { $("stepsOut").textContent = steps.value; });
drop.addEventListener("click", () => fileEl.click());
fileEl.addEventListener("change", () => { file = fileEl.files[0]; if (file) statusEl.textContent = "Photo: " + file.name; });
mode.addEventListener("change", fill);

function fill() {
  const list = MODELS.filter((m) => m.task === mode.value);
  modelSel.innerHTML = list.map((m) => `<option value="${m.id}">${m.id}</option>`).join("") || "<option>none</option>";
}

(async () => {
  MODELS = await registry();
  const labels = { text2image: "Text → Image", image_edit: "Edit an image", texture: "Texture" };
  mode.innerHTML = ["text2image", "image_edit", "texture"]
    .filter((t) => MODELS.some((m) => m.task === t))
    .map((t) => `<option value="${t}">${labels[t]}</option>`).join("");
  fill();
  if (!configured()) statusEl.textContent = "AI is not configured on the server yet.";
})();

async function cfImage() {
  const prompt = prompt.value.trim();
  if (!prompt) { statusEl.textContent = "Enter a prompt first."; return; }
  const est = 15; const t0 = Date.now(); prog.hidden = false;
  const timer = setInterval(() => tick({ remaining: Math.max(0, est - (Date.now() - t0) / 1000),
    pct: Math.min(95, ((Date.now() - t0) / 1000 / est) * 100) }), 1000);
  try {
    const r = await fetch("/api/ai/cf/image", { method: "POST",
      headers: { ...headers(), "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, steps: Number(steps.value) }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || "cloudflare failed");
    const url = new URL(j.url, location.origin).href;
    meta.textContent = "cloudflare · " + j.model;
    preview.innerHTML = `<img src="${url}" alt="result" /><br><a href="${url}" download>Download</a>`;
    const a = document.createElement("a"); a.href = url; a.download = j.artifact; a.click();
    countEl.textContent = "0s"; fillEl.style.width = "100%"; statusEl.textContent = "Done (Cloudflare).";
    setTimeout(() => { prog.hidden = true; }, 900);
  } catch (e) {
    statusEl.textContent = "Cloudflare: " + (e.message || e) + " — add AI_CF_ACCOUNT_ID/AI_CF_API_TOKEN to enable.";
    prog.hidden = true;
  } finally { clearInterval(timer); }
}

$("go").addEventListener("click", async () => {
  if ($("provider").value === "cloudflare") return cfImage();
  const btn = $("go"); btn.disabled = true;
  try {
    const job = await generate({ task: mode.value, model: modelSel.value, file, prompt: prompt.value.trim(), steps: Number(steps.value), onStage: (s) => { statusEl.textContent = s; stageTxt.textContent = s; }, onTick: tick });
    meta.textContent = "done";
    const url = new URL("/api/ai/bridge/artifacts/" + job.artifact, location.origin).href;
    preview.innerHTML = `<img src="${url}" alt="result" /><br><a href="${url}" download>Download</a>`;
    const a = document.createElement("a"); a.href = url; a.download = job.artifact; a.click();
    countEl.textContent = "0s"; fillEl.style.width = "100%"; statusEl.textContent = "Done.";
    setTimeout(() => { prog.hidden = true; }, 900);
  } catch (e) {
    statusEl.textContent = "Error: " + (e.message || e); prog.hidden = true;
  } finally { btn.disabled = false; }
});