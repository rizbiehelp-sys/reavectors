/* ReaVector Product 3D Studio - product photo -> parametric 3D (LatheGeometry).
 *
 * What this IS:   a *parametric* packaging reconstruction measured from a real
 *                 product photo, with the ORIGINAL label artwork perspective-
 *                 corrected and wrapped as a texture. Body / neck / cap / label
 *                 are separate components. Exports GLB.
 * What this is NOT: generative. Brand names, logos and text are NEVER invented -
 *                 they come from the user's photo or supplied label asset.
 *                 AI surface reconstruction (TripoSR / SF3D) needs the GPU worker.
 */
import * as THREE from "/vendor/three/three.module.js";
import { OrbitControls } from "/vendor/three/addons/controls/OrbitControls.js";
import { GLTFExporter } from "/vendor/three/addons/exporters/GLTFExporter.js";

const $ = (id) => document.getElementById(id);
const statusEl = $("status"), drop = $("drop"), photoInput = $("photo");
const labelInput = $("label"), backInput = $("back"), sideInput = $("side");
const modeSel = $("mode"), extraWrapper = $("extraWrapper"), materialSel = $("material");
const wrapEl = $("wrap"), rotEl = $("rot"), wrapOut = $("wrapOut"), rotOut = $("rotOut");
const wireEl = $("wire"), gridEl = $("grid"), bgEl = $("bg");
const buildBtn = $("build"), resetBtn = $("resetCam"), exportBtn = $("exportGlb");
const emptyEl = $("empty"), viewport = $("viewport"), meshStats = $("meshStats");
const overlay = $("progress3d"), overlayText = $("overlayText"), report = $("report");
const thumbOrig = $("thumbOrig"), thumbCut = $("thumbCut"), thumbLabel = $("thumbLabel");
const API_KEY = (document.querySelector('meta[name="reavectors-key"]')?.content || "").trim();

let renderer, scene, camera, controls, grid, productGroup, envTex;
let currentSpec = null, photoFile = null, origUrl = null, building = false;

const raf = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
const showOverlay = (t) => { overlayText.textContent = t; overlay.hidden = false; };
const hideOverlay = () => { overlay.hidden = true; };

// ---------------------------------------------------------------------------
// input
// ---------------------------------------------------------------------------
drop.addEventListener("click", () => photoInput.click());
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); photoInput.click(); } });
photoInput.addEventListener("change", () => photoInput.files[0] && setPhoto(photoInput.files[0]));
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); }));
drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) setPhoto(f); });
modeSel.addEventListener("change", () => { extraWrapper.hidden = modeSel.value !== "high_fidelity"; });
[wrapEl, rotEl].forEach((el) => el.addEventListener("input", () => {
  wrapOut.textContent = wrapEl.value + "\u00b0"; rotOut.textContent = rotEl.value + "\u00b0";
  if (currentSpec) renderProduct(currentSpec);
}));
materialSel.addEventListener("change", () => { if (currentSpec) renderProduct(currentSpec); });
wireEl.addEventListener("change", () => { if (productGroup) productGroup.traverse((o) => { if (o.isMesh && o.material) o.material.wireframe = wireEl.checked; }); });
gridEl.addEventListener("change", () => { if (grid) grid.visible = gridEl.checked; });
bgEl.addEventListener("input", () => { if (scene) scene.background = new THREE.Color(bgEl.value); });
buildBtn.addEventListener("click", () => buildProduct());
resetBtn.addEventListener("click", () => resetCamera());
exportBtn.addEventListener("click", () => exportGlb());

function setPhoto(file) {
  photoFile = file;
  if (origUrl) URL.revokeObjectURL(origUrl);
  origUrl = URL.createObjectURL(file);
  thumbOrig.src = origUrl;
  buildBtn.disabled = false;
  statusEl.textContent = `Loaded ${file.name}. ${modeSel.value === "high_fidelity" ? "Add back/side views, then reconstruct." : "Ready — reconstruct."}`;
}

// ---------------------------------------------------------------------------
// request
// ---------------------------------------------------------------------------
async function buildProduct() {
  if (!photoFile || building) return;
  building = true; buildBtn.disabled = true;
  showOverlay("Measuring silhouette + rectifying label…");
  await raf();
  try {
    const fd = new FormData();
    fd.append("image", photoFile);
    if (labelInput.files[0]) fd.append("label", labelInput.files[0]);
    if (modeSel.value === "high_fidelity") {
      if (backInput.files[0]) fd.append("back", backInput.files[0]);
      if (sideInput.files[0]) fd.append("side", sideInput.files[0]);
    }
    fd.append("material", materialSel.value);
    fd.append("mode", modeSel.value);
    const headers = {};
    if (API_KEY) headers["X-API-Key"] = API_KEY;
    const res = await fetch("/api/ai/product3d", { method: "POST", headers, body: fd });
    const spec = await res.json();
    if (!res.ok) throw new Error(spec.error || `HTTP ${res.status}`);
    currentSpec = spec;
    thumbCut.src = spec.previews.cutout;
    thumbLabel.src = spec.label.image;
    await renderProduct(spec);
    showReport(spec);
    exportBtn.disabled = false;
    statusEl.textContent = `Reconstructed a ${spec.package.type} · confidence ${spec.quality.confidence}.`;
  } catch (err) {
    statusEl.textContent = "Error: " + (err.message || err);
  } finally {
    hideOverlay(); building = false; buildBtn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// three.js
// ---------------------------------------------------------------------------
function initThree() {
  renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(viewport.clientWidth, viewport.clientHeight);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  viewport.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.background = new THREE.Color(bgEl.value);

  camera = new THREE.PerspectiveCamera(42, viewport.clientWidth / viewport.clientHeight, 0.01, 100);
  camera.position.set(0, 0.15, 2.4);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.08;
  controls.minDistance = 0.6; controls.maxDistance = 12; controls.target.set(0, 0, 0);

  scene.add(new THREE.HemisphereLight(0xffffff, 0x223, 1.0));
  const key = new THREE.DirectionalLight(0xffffff, 2.0); key.position.set(2, 3, 4); scene.add(key);
  const rim = new THREE.DirectionalLight(0xbfd8ff, 1.0); rim.position.set(-3, 1, -2); scene.add(rim);

  // simple studio environment so glossy/glass surfaces get reflections
  const c = document.createElement("canvas"); c.width = 32; c.height = 128;
  const g = c.getContext("2d").createLinearGradient(0, 0, 0, 128);
  g.addColorStop(0, "#dfe9f5"); g.addColorStop(0.5, "#8fa4bd"); g.addColorStop(1, "#2a3444");
  const cx = c.getContext("2d"); cx.fillStyle = g; cx.fillRect(0, 0, 32, 128);
  envTex = new THREE.CanvasTexture(c);
  envTex.mapping = THREE.EquirectangularReflectionMapping;
  scene.environment = envTex;

  grid = new THREE.GridHelper(6, 24, 0x2a3444, 0x1b2230);
  grid.position.y = -0.55; scene.add(grid);

  productGroup = new THREE.Group(); scene.add(productGroup);
  addEventListener("resize", onResize); onResize();
  (function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();
}
function onResize() {
  if (!renderer) return;
  camera.aspect = viewport.clientWidth / viewport.clientHeight; camera.updateProjectionMatrix();
  renderer.setSize(viewport.clientWidth, viewport.clientHeight);
}
function resetCamera() { camera.position.set(0, 0.15, 2.4); controls.target.set(0, 0, 0); controls.update(); }

function disposeGroup(grp) {
  grp.traverse((o) => {
    if (o.isMesh) { o.geometry?.dispose(); if (o.material?.map && o.material.map !== envTex) o.material.map.dispose(); o.material?.dispose(); }
  });
  grp.clear();
}

function bodyMaterial(spec) {
  const [r, g, b] = spec.materials.body_color || [200, 200, 200];
  const color = new THREE.Color(r / 255, g / 255, b / 255);
  const kind = materialSel.value !== "auto" ? materialSel.value : spec.materials.body;
  if (kind === "glass") {
    const lite = color.clone().lerp(new THREE.Color(0xffffff), 0.5);
    return new THREE.MeshPhysicalMaterial({ color: lite, metalness: 0, roughness: 0.06, transmission: 0.94, ior: 1.45, thickness: 0.6, transparent: true, side: THREE.DoubleSide, envMap: envTex, envMapIntensity: 1.2 });
  }
  if (kind === "metal") return new THREE.MeshStandardMaterial({ color, metalness: 0.94, roughness: 0.28, envMap: envTex, envMapIntensity: 1.0 });
  return new THREE.MeshStandardMaterial({ color, metalness: 0.0, roughness: 0.42, envMap: envTex, envMapIntensity: 0.7 });
}

async function loadTex(dataUrl) {
  const img = new Image(); img.crossOrigin = "anonymous";
  await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = dataUrl; });
  const t = new THREE.CanvasTexture(img); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  return t;
}

async function renderProduct(spec) {
  disposeGroup(productGroup);
  const m = spec.model;
  const wrap = THREE.MathUtils.degToRad(Number(wrapEl.value));
  const rot = THREE.MathUtils.degToRad(Number(rotEl.value));
  const wire = wireEl.checked;
  const bmat = bodyMaterial(spec); bmat.wireframe = wire;

  // body (lathe through the measured profile)
  const pts = spec.profile.map((p) => new THREE.Vector2(Math.max(0.0006, p[0]), p[1]));
  const bodyMesh = new THREE.Mesh(new THREE.LatheGeometry(pts, 128), bmat);
  productGroup.add(bodyMesh);

  // bottom disc (closed base)
  const bot = new THREE.Mesh(new THREE.CircleGeometry(spec.profile[0][0], 64),
    new THREE.MeshStandardMaterial({ color: bmat.color, metalness: 0.1, roughness: 0.6, side: THREE.DoubleSide }));
  bot.rotation.x = Math.PI / 2; bot.position.y = -0.5; productGroup.add(bot);

  // cap (metal), sized from the neck
  const capR = Math.max(m.neck_radius * 1.5, m.body_radius * 0.3), capH = 0.075;
  const cap = new THREE.Mesh(new THREE.CylinderGeometry(capR, capR, capH, 64),
    new THREE.MeshStandardMaterial({ color: 0x9aa4ad, metalness: 0.95, roughness: 0.3, envMap: envTex, wireframe: wire }));
  cap.position.y = 0.5 + capH / 2; productGroup.add(cap);

  // label: original artwork wrapped on the body band (front-centred)
  try {
    const tex = await loadTex(spec.label.image);
    const band = m.label_band, h = Math.max(0.02, band.y1 - band.y0);
    const lr = m.body_radius * 1.004;
    const labelGeo = new THREE.CylinderGeometry(lr, lr, h, 128, 1, true, -wrap / 2 + rot, wrap);
    const labelMat = new THREE.MeshStandardMaterial({ map: tex, transparent: true, roughness: 0.55, metalness: 0.0, side: THREE.DoubleSide, wireframe: wire });
    const labelMesh = new THREE.Mesh(labelGeo, labelMat);
    labelMesh.position.y = (band.y0 + band.y1) / 2; productGroup.add(labelMesh);
  } catch (e) { /* label optional */ }

  emptyEl.hidden = true;
  const tris = renderer.info.render.triangles;
  meshStats.textContent = `${spec.package.type} · ${tris} tris`;
}

// ---------------------------------------------------------------------------
// report
// ---------------------------------------------------------------------------
function showReport(spec) {
  const q = spec.quality, mm = spec.materials;
  const sw = `rgb(${(mm.body_color || [200, 200, 200]).join(",")})`;
  const warns = q.warnings.map((w) => `<li>${w}</li>`).join("");
  report.innerHTML = `
    <h4>Model quality report</h4>
    <p>Package: <strong>${spec.package.type}</strong>${spec.package.has_neck ? " (neck/shoulder)" : ""} ·
       Confidence: <span class="badge ${q.confidence}">${q.confidence}</span> ·
       Symmetry: ${(q.symmetry * 100).toFixed(0)}% ·
       Label: <strong>${spec.label.source === "supplied_asset" ? "your asset (verbatim)" : "rectified from photo"}</strong> ·
       Body colour <span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:${sw};vertical-align:-2px"></span></p>
    <p class="muted">Material hint: ${mm.body} / ${mm.cap} — ${mm.note}</p>
    <ul>${warns}</ul>`;
  report.hidden = false;
}

// ---------------------------------------------------------------------------
// export
// ---------------------------------------------------------------------------
async function exportGlb() {
  if (!productGroup) return;
  exportBtn.disabled = true; showOverlay("Exporting GLB…");
  try {
    const gltf = await new Promise((res, rej) =>
      new GLTFExporter().parse(productGroup, res, rej, { binary: true, onlyVisible: true }));
    const blob = new Blob([gltf], { type: "model/gltf-binary" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = (currentSpec?.package?.type || "product") + "-reavector.glb";
    a.click(); URL.revokeObjectURL(a.href);
    statusEl.textContent = "GLB exported (original label texture embedded).";
  } catch (err) {
    statusEl.textContent = "Export failed: " + (err.message || err);
  } finally { hideOverlay(); exportBtn.disabled = false; }
}

initThree();
