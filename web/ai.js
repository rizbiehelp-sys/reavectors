/* ReaVector AI Workspace — owner queue + Kaggle trigger + result viewer. */
import * as THREE from "/vendor/three/three.module.js";
import { OrbitControls } from "/vendor/three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "/vendor/three/addons/loaders/GLTFLoader.js";

const $ = (id) => document.getElementById(id);
const keyEl = $("key"), taskEl = $("task"), modelEl = $("model"), fileEl = $("file"),
      urlEl = $("url"), promptEl = $("prompt"), stepsEl = $("steps"), stepsOut = $("stepsOut");
const statusEl = $("status"), outEl = $("out"), preview = $("preview"), metaEl = $("meta");
const backendEl = $("backend"), emptyEl = $("empty"), viewport = $("viewport");
const API_KEY = (document.querySelector('meta[name="reavectors-key"]')?.content || "").trim();

const KEY_HINT = "Render → Environment → AI_BRIDGE_KEY (copy the exact value).";

let REGISTRY = [], currentJob = null;
let renderer, scene, camera, controls, group;

// ---- three.js viewer --------------------------------------------------
function initThree() {
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(viewport.clientWidth, viewport.clientHeight);
  viewport.appendChild(renderer.domElement);
  scene = new THREE.Scene(); scene.background = new THREE.Color(0x0b0f14);
  camera = new THREE.PerspectiveCamera(42, viewport.clientWidth / viewport.clientHeight, 0.01, 100);
  camera.position.set(0, 0.2, 3);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x223, 1.1));
  const k = new THREE.DirectionalLight(0xffffff, 2); k.position.set(2, 3, 4); scene.add(k);
  group = new THREE.Group(); scene.add(group);
  addEventListener("resize", () => {
    camera.aspect = viewport.clientWidth / viewport.clientHeight; camera.updateProjectionMatrix();
    renderer.setSize(viewport.clientWidth, viewport.clientHeight);
  });
  (function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();
}

function showGlb(url) {
  viewport.style.display = "block";
  new GLTFLoader().load(url, (g) => {
    group.clear(); group.add(g.scene);
    const box = new THREE.Box3().setFromObject(g.scene);
    const size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
    g.scene.position.sub(c);
    const m = Math.max(size.x, size.y, size.z) || 1;
    camera.position.set(0, m * 0.15, m * 2.2); controls.target.set(0, 0, 0); controls.update();
    emptyEl.style.display = "none";
  }, undefined, (e) => { preview.textContent = "GLB load failed: " + e; });
}

// ---- helpers ----------------------------------------------------------
function headers() {
  const h = {};
  const k = keyEl.value.trim();
  if (k) h["X-Bridge-Key"] = k;
  if (API_KEY) h["X-API-Key"] = API_KEY;
  return h;
}
const abs = (u) => new URL(u, location.origin).href;

async function loadRegistry() {
  try {
    const r = await fetch("/api/ai/registry"); const j = await r.json();
    REGISTRY = j.models || [];
    taskEl.innerHTML = [...new Set(REGISTRY.map((m) => m.task))].map((t) => `<option>${t}</option>`).join("");
    if (REGISTRY.some((m) => m.task === "image2_3d")) taskEl.value = "image2_3d";
    fillModels();
  } catch (e) { outEl.textContent = "registry load failed: " + e; }
}
function fillModels() {
  const t = taskEl.value;
  const list = REGISTRY.filter((m) => m.task === t);
  modelEl.innerHTML = list.map((m) => `<option value="${m.id}">${m.id} · ${m.status} · ${m.vram_gb}GB</option>`).join("");
}
taskEl.addEventListener("change", fillModels);
stepsEl.addEventListener("input", () => { stepsOut.textContent = stepsEl.value; });

async function checkBackend() {
  if (!keyEl.value.trim()) {
    backendEl.textContent = "bridge: key needed";
    statusEl.textContent = "Paste your bridge key and Save. " + KEY_HINT;
    return;
  }
  try {
    const r = await fetch("/api/ai/bridge/backend", { headers: headers() });
    const j = await r.json().catch(() => ({}));
    if (r.ok) {
      backendEl.textContent = "bridge: " + (j.backend || "ok");
      statusEl.textContent = `Bridge key valid (${j.backend || "ok"}).`;
    } else {
      backendEl.textContent = "bridge: key invalid";
      statusEl.textContent = "Bridge key invalid — " + KEY_HINT;
    }
  } catch { backendEl.textContent = "bridge: offline"; }
}

async function uploadInput() {
  if (!fileEl.files[0]) return urlEl.value.trim() || "";
  const fd = new FormData();
  fd.append("file", fileEl.files[0]);
  fd.append("filename", fileEl.files[0].name);
  const r = await fetch("/api/ai/bridge/inputs", { method: "POST", headers: headers(), body: fd });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(r.status === 403 ? "Bridge key invalid — " + KEY_HINT : (j.error || `upload ${r.status}`));
  return abs(j.url);
}

async function queueJob() {
  if (!keyEl.value.trim()) { statusEl.textContent = "Paste your bridge key first. " + KEY_HINT; return; }
  statusEl.textContent = "Uploading input…";
  try {
    const input_url = await uploadInput();
    const body = {
      task: taskEl.value, model: modelEl.value, input_url: input_url || null,
      params: { prompt: promptEl.value.trim(), steps: Number(stepsEl.value) },
    };
    const r = await fetch("/api/ai/bridge/jobs", {
      method: "POST", headers: { ...headers(), "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(r.status === 403 ? "Bridge key invalid — " + KEY_HINT : (j.error || `queue ${r.status}`));
    currentJob = j;
    statusEl.textContent = `Queued ${j.id} (${j.model}). Now press “Run on Kaggle”.`;
    renderJob(j);
  } catch (e) { statusEl.textContent = "Queue error: " + (e.message || e); }
}

async function trigger() {
  if (!keyEl.value.trim()) { statusEl.textContent = "Paste your bridge key first. " + KEY_HINT; return; }
  if (!currentJob) { statusEl.textContent = "Queue a job first."; return; }
  statusEl.textContent = "Triggering Kaggle kernel…";
  try {
    const r = await fetch("/api/ai/bridge/trigger", {
      method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: currentJob.id }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(r.status === 403 ? "Bridge key invalid — " + KEY_HINT : (j.error || `trigger ${r.status}`));
    statusEl.textContent = `Kernel pushed: ${j.kernel}. Kaggle takes a few minutes — press Refresh.`;
    refresh();
  } catch (e) { statusEl.textContent = "Trigger error: " + (e.message || e); }
}

async function refresh() {
  if (!currentJob) return;
  try {
    const r = await fetch(`/api/ai/bridge/jobs/${currentJob.id}`, { headers: headers() });
    if (r.ok) { currentJob = await r.json(); renderJob(currentJob); }
    const kr = await fetch("/api/ai/bridge/kernel?ref=rizbiehelp/reavector-worker", { headers: headers() });
    if (kr.ok) { const k = await kr.json(); metaEl.textContent = "kernel: " + (k.status || ""); }
  } catch (e) { outEl.textContent = "refresh: " + e; }
}

function renderJob(job) {
  outEl.textContent = JSON.stringify(job, null, 2).slice(0, 1200);
  metaEl.textContent = "job: " + job.status;
  if (!job.artifact) { preview.textContent = "Status: " + job.status + (job.error ? (" — " + job.error) : ""); return; }
  const url = abs("/api/ai/bridge/artifacts/" + job.artifact);
  const ext = (job.artifact.split(".").pop() || "").toLowerCase();
  if (ext === "glb" || ext === "gltf") {
    preview.innerHTML = `<a href="${url}" download>Download ${job.artifact}</a>`;
    showGlb(url);
  } else if (["png", "jpg", "jpeg", "webp"].includes(ext)) {
    viewport.style.display = "none";
    preview.innerHTML = `<img src="${url}" alt="result" />`;
  } else if (["mp4", "webm"].includes(ext)) {
    viewport.style.display = "none";
    preview.innerHTML = `<video src="${url}" controls></video>`;
  } else {
    preview.innerHTML = `<a href="${url}" download>Download ${job.artifact}</a>`;
  }
}

// ---- wiring -----------------------------------------------------------
keyEl.value = localStorage.getItem("rv_bridge_key") || "";
$("saveKey").addEventListener("click", () => {
  localStorage.setItem("rv_bridge_key", keyEl.value.trim());
  statusEl.textContent = "Key saved — checking…";
  checkBackend();
});
$("checkBackend").addEventListener("click", checkBackend);
$("queue").addEventListener("click", queueJob);
$("trigger").addEventListener("click", trigger);
$("refresh").addEventListener("click", refresh);

initThree(); loadRegistry(); checkBackend();