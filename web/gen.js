/* One-click generation: upload -> queue -> trigger Kaggle -> poll -> result.
   Also runs a countdown/progress timer (estimate -> 0) while the job runs. */
const META = (n) => (document.querySelector(`meta[name="${n}"]`)?.content || "").trim();
const BRIDGE_KEY = META("ai-bridge-key");
const API_KEY = META("reavectors-key");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// rough per-task estimate in seconds (the countdown target)
const ESTIMATE = {
  text2image: 120, image_edit: 180, texture: 150,
  text2video: 600, image2video: 600, image2_3d: 600,
};

export function headers() {
  const h = {};
  if (BRIDGE_KEY) h["X-Bridge-Key"] = BRIDGE_KEY;
  if (API_KEY) h["X-API-Key"] = API_KEY;
  return h;
}
export const configured = () => !!BRIDGE_KEY;
export const artifactUrl = (job) => new URL("/api/ai/bridge/artifacts/" + job.artifact, location.origin).href;

export async function registry() {
  const r = await fetch("/api/ai/registry");
  return (await r.json()).models || [];
}

export async function generate({ task, model, file, prompt, steps = 30, onStage, onTick }) {
  const stage = (s) => onStage && onStage(s);
  const est = ESTIMATE[task] || 180;
  const t0 = Date.now();
  const timer = setInterval(() => {
    const elapsed = (Date.now() - t0) / 1000;
    const remaining = Math.max(0, est - elapsed);
    const pct = Math.min(95, (elapsed / Math.max(1, est)) * 100);
    onTick && onTick({ elapsed, remaining, estimate: est, pct });
  }, 1000);

  try {
    if (!BRIDGE_KEY) throw new Error("AI is not configured on the server (AI_BRIDGE_KEY missing).");

    let input_url = null;
    if (file) {
      stage("Uploading input…");
      const fd = new FormData();
      fd.append("file", file);
      fd.append("filename", file.name);
      const r = await fetch("/api/ai/bridge/inputs", { method: "POST", headers: headers(), body: fd });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || "upload failed");
      input_url = new URL(j.url, location.origin).href;
    }

    stage("Queueing job…");
    const q = await fetch("/api/ai/bridge/jobs", {
      method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
      body: JSON.stringify({ task, model, input_url, params: { prompt, steps } }),
    });
    const job = await q.json().catch(() => ({}));
    if (!q.ok) throw new Error(job.error || "queue failed");

    stage("Starting the GPU…");
    let note = "";
    try {
      const tr = await fetch("/api/ai/bridge/trigger", {
        method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: job.id }),
      });
      if (!tr.ok) note = (await tr.json().catch(() => ({}))).error || "";
    } catch (e) { note = String(e); }

    stage(note ? "Queued — the running GPU will pick it up." : "Running on Kaggle T4…");
    for (let i = 0; i < 180; i++) {
      await sleep(10000);
      const r = await fetch(`/api/ai/bridge/jobs/${job.id}`, { headers: headers() });
      if (!r.ok) continue;
      const j = await r.json();
      if (j.status === "done") return j;
      if (j.status === "failed") throw new Error(j.error || "job failed");
      stage(`Running on Kaggle… (${(i + 1) * 10}s)`);
    }
    throw new Error("timed out waiting for Kaggle");
  } finally {
    clearInterval(timer);
  }
}