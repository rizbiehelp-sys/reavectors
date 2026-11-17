import { generate, registry, configured } from "/gen.js";

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
  fill();
  if (!configured()) statusEl.textContent = "AI is not configured on the server yet.";
})();

$("go").addEventListener("click", async () => {
  const btn = $("go"); btn.disabled = true;
  try {
    const job = await generate({ task: mode.value, model: modelSel.value, file, prompt: prompt.value.trim(), steps: Number(steps.value), onStage: (s) => { statusEl.textContent = s; stageTxt.textContent = s; }, onTick: tick });
    meta.textContent = "done";
    const url = new URL("/api/ai/bridge/artifacts/" + job.artifact, location.origin).href;
    preview.innerHTML = `<video src="${url}" controls></video><br><a href="${url}" download>Download</a>`;
    const a = document.createElement("a"); a.href = url; a.download = job.artifact; a.click();
    countEl.textContent = "0s"; fillEl.style.width = "100%"; statusEl.textContent = "Done."; setTimeout(() => { prog.hidden = true; }, 900);
  } catch (e) {
    statusEl.textContent = "Error: " + (e.message || e); prog.hidden = true;
  } finally { btn.disabled = false; }
});