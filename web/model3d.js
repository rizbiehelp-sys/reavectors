import * as THREE from "/vendor/three/three.module.js";
import { OrbitControls } from "/vendor/three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "/vendor/three/addons/loaders/GLTFLoader.js";
import { generate, registry, configured, headers } from "/gen.js";

const $ = (id) => document.getElementById(id);
const viewport = $("viewport"), empty = $("empty"), statusEl = $("status"), meta = $("meta"), dl = $("dl");
const prog = $("prog"), countEl = $("count"), fillEl = $("fill"), stageTxt = $("stageTxt");
function tick({ remaining, pct }) { prog.hidden = false; countEl.textContent = Math.ceil(remaining) + "s"; fillEl.style.width = pct + "%"; }
const fileEl = $("file"), drop = $("drop"), modelSel = $("model"), steps = $("steps");
let file = null, MODELS = [];

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(viewport.clientWidth, viewport.clientHeight);
viewport.appendChild(renderer.domElement);
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x0b0f14);
const camera = new THREE.PerspectiveCamera(42, viewport.clientWidth / viewport.clientHeight, 0.01, 100);
camera.position.set(0, 0.2, 3);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.autoRotate = true; controls.autoRotateSpeed = 1.2;
controls.target.set(0, 0, 0);
const key = new THREE.DirectionalLight(0xffffff, 2); key.position.set(2, 3, 4);
key.castShadow = true; key.shadow.mapSize.set(1024, 1024); scene.add(key);
const hemi = new THREE.HemisphereLight(0xffffff, 0x223, 1.1); scene.add(hemi);
const ground = new THREE.Mesh(new THREE.CircleGeometry(4, 48),
  new THREE.MeshStandardMaterial({ color: 0x151b23, roughness: 0.9 }));
ground.rotation.x = -Math.PI / 2; ground.position.y = -0.001; ground.receiveShadow = true; scene.add(ground);
const group = new THREE.Group(); scene.add(group);
addEventListener("resize", () => {
  camera.aspect = viewport.clientWidth / viewport.clientHeight; camera.updateProjectionMatrix();
  renderer.setSize(viewport.clientWidth, viewport.clientHeight);
});
(function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();

steps.addEventListener("input", () => { $("stepsOut").textContent = steps.value; });
drop.addEventListener("click", () => fileEl.click());
fileEl.addEventListener("change", () => { file = fileEl.files[0]; if (file) { statusEl.textContent = "Photo: " + file.name; refPreview.src = URL.createObjectURL(file); refPreview.hidden = false; } });

(async () => {
  MODELS = (await registry()).filter((m) => m.task === "image2_3d");
  modelSel.innerHTML = MODELS.map((m) => `<option value="${m.id}">${m.id} · ${m.vram_gb}GB</option>`).join("") || "<option>none</option>";
  if (!configured()) statusEl.textContent = "AI is not configured on the server yet.";
})();

function showGlb(url, name) {
  new GLTFLoader().load(url, (g) => {
    group.clear(); group.add(g.scene);
    const box = new THREE.Box3().setFromObject(g.scene);
    const size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
    g.scene.position.sub(c);
    const m = Math.max(size.x, size.y, size.z) || 1;
    camera.position.set(0, m * 0.15, m * 2.2); controls.target.set(0, 0, 0); controls.update();
    window.__rvMaxD = m;
    empty.style.display = "none";
    dl.style.display = "block";
    dl.innerHTML = `<a href="${url}" download="${name}">Download .glb</a>`;
  }, undefined, (e) => { statusEl.textContent = "GLB load failed: " + e; });
}

function view(name) {
  const d = (window.__rvMaxD || 1) * 2.2;
  const P = { front: [0, 0, d], back: [0, 0, -d], left: [-d, 0, 0], right: [d, 0, 0] }[name] || [0, (window.__rvMaxD||1)*0.15, d];
  camera.position.set(P[0], P[1], P[2]); controls.target.set(0, 0, 0); controls.update();
}
document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => view(b.dataset.view)));
$("resetView").addEventListener("click", () => view("front"));
$("fsBtn").addEventListener("click", () => {
  if (!document.fullscreenElement) viewport.requestFullscreen?.(); else document.exitFullscreen?.();
});
$("lighting").addEventListener("change", () => {
  const v = $("lighting").value;
  if (v === "soft") { key.intensity = 1.2; hemi.intensity = 1.5; key.color.set(0xffffff); scene.background = new THREE.Color(0x11161d); }
  else if (v === "sunset") { key.intensity = 2.4; hemi.intensity = 0.6; key.color.set(0xffb07a); scene.background = new THREE.Color(0x1a120c); }
  else { key.intensity = 2.0; hemi.intensity = 1.1; key.color.set(0xffffff); scene.background = new THREE.Color(0x0b0f14); }
});
$("shadows").addEventListener("change", () => { renderer.shadowMap.enabled = $("shadows").checked; });
$("spin").addEventListener("change", () => { controls.autoRotate = $("spin").checked; });
window.addEventListener("beforeunload", () => { renderer.dispose(); });


function renderParametric(spec) {
  group.clear();
  const pts = spec.profile.map((q) => new THREE.Vector2(Math.max(0.0006, q[0]), q[1]));
  const bodyR = Math.max(...pts.map((v) => v.x));
  const col = new THREE.Color(...(spec.materials.body_color || [200, 200, 200]).map((v) => v / 255));
  group.add(new THREE.Mesh(new THREE.LatheGeometry(pts, 128),
    new THREE.MeshStandardMaterial({ color: col, roughness: 0.42, metalness: 0 })));
  const botR = pts[0].x;
  const bot = new THREE.Mesh(new THREE.CircleGeometry(botR, 64),
    new THREE.MeshStandardMaterial({ color: col, side: THREE.DoubleSide }));
  bot.rotation.x = Math.PI / 2; bot.position.y = -0.5; group.add(bot);
  const topR = pts[pts.length - 1].x, capR = Math.max(topR * 1.6, bodyR * 0.3);
  const cap = new THREE.Mesh(new THREE.CylinderGeometry(capR, capR, 0.075, 64),
    new THREE.MeshStandardMaterial({ color: 0x9aa4ad, metalness: 0.9, roughness: 0.3 }));
  cap.position.y = 0.5 + 0.0375; group.add(cap);
  if (spec.label && spec.label.image) {
    new THREE.TextureLoader().load(spec.label.image, (tex) => {
      tex.colorSpace = THREE.SRGBColorSpace;
      const band = spec.model.label_band, h = Math.max(0.02, band.y1 - band.y0);
      const lr = bodyR * 1.004;
      const lg = new THREE.CylinderGeometry(lr, lr, h, 128, 1, true, -Math.PI / 2, Math.PI);
      const lbl = new THREE.Mesh(lg, new THREE.MeshStandardMaterial({ map: tex, transparent: true, side: THREE.DoubleSide, roughness: 0.55 }));
      lbl.position.y = (band.y0 + band.y1) / 2; group.add(lbl);
    });
  }
  window.__rvMaxD = 1.2;
  camera.position.set(0, 0.15, 2.6); controls.target.set(0, 0, 0); controls.update();
  empty.style.display = "none";
}

async function instantBuild() {
  if (!file) { statusEl.textContent = "Add a photo first."; return; }
  const btn = $("instant"); btn.disabled = true;
  statusEl.textContent = "Building model (no GPU)…";
  try {
    const fd = new FormData();
    fd.append("image", file); fd.append("material", "auto"); fd.append("mode", "single");
    const r = await fetch("/api/ai/product3d?refine=25", { method: "POST", headers: headers(), body: fd });
    const spec = await r.json();
    if (!r.ok) throw new Error(spec.error || "build failed");
    renderParametric(spec);
    statusEl.textContent = "Instant model ready — drag to rotate, or record a clip.";
  } catch (e) { statusEl.textContent = "Error: " + (e.message || e); }
  finally { btn.disabled = false; }
}

async function recordClip() {
  const btn = $("record"); btn.disabled = true;
  try {
    const stream = renderer.domElement.captureStream(30);
    const mime = MediaRecorder.isTypeSupported("video/webm;codecs=vp9") ? "video/webm;codecs=vp9" : "video/webm";
    const rec = new MediaRecorder(stream, { mimeType: mime });
    const chunks = []; rec.ondataavailable = (e) => chunks.push(e.data);
    const done = new Promise((res) => { rec.onstop = res; });
    controls.autoRotate = true; rec.start();
    setTimeout(() => rec.stop(), 6000);
    await done;
    const blob = new Blob(chunks, { type: "video/webm" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "reavector-360.webm"; a.click();
    statusEl.textContent = "360 clip saved (webm).";
  } catch (e) { statusEl.textContent = "Record failed: " + (e.message || e); }
  finally { btn.disabled = false; }
}

$("instant").addEventListener("click", instantBuild);
$("record").addEventListener("click", recordClip);

$("go").addEventListener("click", async () => {
  if (!file) { statusEl.textContent = "Add a photo first."; return; }
  const btn = $("go"); btn.disabled = true;
  try {
    const job = await generate({ task: "image2_3d", model: modelSel.value, file, prompt: "", steps: Number(steps.value), onStage: (s) => { statusEl.textContent = s; stageTxt.textContent = s; }, onTick: tick });
    meta.textContent = "done";
    const url = new URL("/api/ai/bridge/artifacts/" + job.artifact, location.origin).href;
showGlb(url, job.artifact);
        const a = document.createElement("a"); a.href = url; a.download = job.artifact; a.click();
        countEl.textContent = "0s"; fillEl.style.width = "100%"; statusEl.textContent = "Done."; setTimeout(() => { prog.hidden = true; }, 900);
  } catch (e) {
    statusEl.textContent = "Error: " + (e.message || e); prog.hidden = true;
  } finally { btn.disabled = false; }
});