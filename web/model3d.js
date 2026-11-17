import * as THREE from "/vendor/three/three.module.js";
import { OrbitControls } from "/vendor/three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "/vendor/three/addons/loaders/GLTFLoader.js";
import { generate, registry, configured } from "/gen.js";

const $ = (id) => document.getElementById(id);
const viewport = $("viewport"), empty = $("empty"), statusEl = $("status"), meta = $("meta"), dl = $("dl");
const prog = $("prog"), countEl = $("count"), fillEl = $("fill"), stageTxt = $("stageTxt");
function tick({ remaining, pct }) { prog.hidden = false; countEl.textContent = Math.ceil(remaining) + "s"; fillEl.style.width = pct + "%"; }
const fileEl = $("file"), drop = $("drop"), modelSel = $("model"), steps = $("steps");
let file = null, MODELS = [];

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(viewport.clientWidth, viewport.clientHeight);
viewport.appendChild(renderer.domElement);
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x0b0f14);
const camera = new THREE.PerspectiveCamera(42, viewport.clientWidth / viewport.clientHeight, 0.01, 100);
camera.position.set(0, 0.2, 3);
const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xffffff, 0x223, 1.1));
const key = new THREE.DirectionalLight(0xffffff, 2); key.position.set(2, 3, 4); scene.add(key);
const group = new THREE.Group(); scene.add(group);
addEventListener("resize", () => {
  camera.aspect = viewport.clientWidth / viewport.clientHeight; camera.updateProjectionMatrix();
  renderer.setSize(viewport.clientWidth, viewport.clientHeight);
});
(function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();

steps.addEventListener("input", () => { $("stepsOut").textContent = steps.value; });
drop.addEventListener("click", () => fileEl.click());
fileEl.addEventListener("change", () => { file = fileEl.files[0]; if (file) statusEl.textContent = "Photo: " + file.name; });

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
    empty.style.display = "none";
    dl.style.display = "block";
    dl.innerHTML = `<a href="${url}" download="${name}">Download .glb</a>`;
  }, undefined, (e) => { statusEl.textContent = "GLB load failed: " + e; });
}

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