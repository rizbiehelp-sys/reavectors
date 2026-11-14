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
import { GLTFLoader } from "/vendor/three/addons/loaders/GLTFLoader.js";

const $ = (id) => document.getElementById(id);
const statusEl = $("status"), drop = $("drop"), photoInput = $("photo");
const labelInput = $("label"), backInput = $("back"), sideInput = $("side");
const modeSel = $("mode"), extraWrapper = $("extraWrapper"), materialSel = $("material");
const wrapEl = $("wrap"), rotEl = $("rot"), wrapOut = $("wrapOut"), rotOut = $("rotOut");
const refineEl = $("refine"), refineOut = $("refineOut");
const wireEl = $("wire"), gridEl = $("grid"), bgEl = $("bg");
const buildBtn = $("build"), resetBtn = $("resetCam"), exportBtn = $("exportGlb");
const emptyEl = $("empty"), viewport = $("viewport"), meshStats = $("meshStats");
const overlay = $("progress3d"), overlayText = $("overlayText"), report = $("report");
const overlaySub = $("overlaySub"), barFill = $("barFill");
const hModel = $("hModel"), hType = $("hType"), hPbr = $("hPbr");
const hGenerate = $("hGenerate"), hStatus = $("hStatus"), hBar = $("hBar"), hDownload = $("hDownload");
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
refineEl.addEventListener("input", () => { refineOut.textContent = refineEl.value + " s"; });
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
  hGenerate.disabled = false;
  statusEl.textContent = `Loaded ${file.name}. ${modeSel.value === "high_fidelity" ? "Add back/side views, then reconstruct." : "Ready — reconstruct."}`;
}

// ---------------------------------------------------------------------------
// hosted Hunyuan Pro (3D AI Studio) - paid credits, opt-in on the server
// ---------------------------------------------------------------------------
hGenerate.addEventListener("click", () => generateHosted());

async function generateHosted() {
  if (!photoFile) return;
  hGenerate.disabled = true;
  hBar.style.width = "0%";
  hDownload.style.display = "none";
  hStatus.textContent = "Submitting to Hunyuan Pro…";
  try {
    const fd = new FormData();
    fd.append("image", photoFile);
    if (backInput.files[0]) fd.append("back", backInput.files[0]);
    if (sideInput.files[0]) fd.append("side", sideInput.files[0]);
    fd.append("model", hModel.value);
    fd.append("generate_type", hType.value);
    fd.append("enable_pbr", hPbr.checked ? "1" : "0");
    const headers = {};
    if (API_KEY) headers["X-API-Key"] = API_KEY;
    const res = await fetch("/api/ai/product3d/hosted", { method: "POST", headers, body: fd });
    const sub = await res.json();
    if (!res.ok) throw new Error(sub.error || `HTTP ${res.status}`);
    hStatus.textContent = `Queued (${sub.model}, ~${sub.credits} credits). Pro takes 3–6 min…`;
    pollHosted(sub.task_id);
  } catch (err) {
    hStatus.textContent = "Hosted error: " + (err.message || err);
    hGenerate.disabled = false;
  }
}

async function pollHosted(taskId) {
  const headers = {};
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  for (let i = 0; i < 90; i++) {
    await new Promise((r) => setTimeout(r, 6000));
    try {
      const r = await fetch(`/api/ai/product3d/hosted/${encodeURIComponent(taskId)}`, { headers });
      const s = await r.json();
      if (!r.ok) throw new Error(s.error || `HTTP ${r.status}`);
      if (typeof s.progress === "number") hBar.style.width = `${s.progress}%`;
      hStatus.textContent = `${s.status} · ${s.progress ?? 0}%`;
      if (s.status === "FINISHED") {
        const asset = (s.results || []).find((x) => x.asset_type === "3D_MODEL") || (s.results || [])[0];
        if (!asset || !asset.asset) throw new Error("no asset returned");
        await loadHostedGlb(asset.asset);
        hStatus.textContent = "Hunyuan Pro result loaded — rotate/zoom, or download.";
        hBar.style.width = "100%";
        hGenerate.disabled = false;
        return;
      }
      if (s.status === "FAILED" || s.failure_reason) {
        throw new Error(s.failure_reason || "generation failed");
      }
    } catch (err) {
      hStatus.textContent = "Hosted error: " + (err.message || err);
      hGenerate.disabled = false;
      return;
    }
  }
  hStatus.textContent = "Timed out waiting for the hosted job.";
  hGenerate.disabled = false;
}

function loadHostedGlb(assetUrl) {
  // fetch through our SSRF-guarded proxy (same-origin, no CORS issues)
  const proxy = `/api/ai/product3d/hosted/asset?url=${encodeURIComponent(assetUrl)}`;
  hDownload.href = proxy;
  hDownload.style.display = "inline-block";
  return new Promise((resolve, reject) => {
    new GLTFLoader().load(proxy, (gltf) => {
      disposeGroup(productGroup);
      productGroup.add(gltf.scene);
      // frame the model
      const box = new THREE.Box3().setFromObject(gltf.scene);
      const size = box.getSize(new THREE.Vector3());
      const center = box.getCenter(new THREE.Vector3());
      gltf.scene.position.sub(center);
      const maxd = Math.max(size.x, size.y, size.z) || 1;
      camera.position.set(0, maxd * 0.15, maxd * 2.2);
      controls.target.set(0, 0, 0); controls.update();
      emptyEl.hidden = true;
      meshStats.textContent = "Hunyuan Pro GLB";
      resolve();
    }, undefined, reject);
  });
}

// ---------------------------------------------------------------------------
// request
// ---------------------------------------------------------------------------
// read a Server-Sent Events stream and dispatch each parsed JSON event
async function readSSE(res, onEvent) {
  const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data:")) { try { onEvent(JSON.parse(line.slice(5).trim())); } catch (e) { /* keepalive */ } }
      }
    }
  }
}

async function buildProduct() {
  if (!photoFile || building) return;
  const budget = Number(refineEl.value) || 30;
  building = true; buildBtn.disabled = true;
  overlayText.textContent = "Starting…"; overlaySub.textContent = `0 s / ${budget} s`;
  barFill.style.width = "0%"; overlay.hidden = false;
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
    const res = await fetch(`/api/ai/product3d?stream=1&refine=${budget}`, { method: "POST", headers, body: fd });
    if (!res.ok || !res.body) throw new Error(await res.text() || `HTTP ${res.status}`);

    let spec = null, errMsg = null;
    await readSSE(res, (ev) => {
      if (ev.type === "progress") {
        overlayText.textContent = ev.stage || "Working…";
        overlaySub.textContent = `${(ev.elapsed ?? 0)} s / ${(ev.budget ?? budget)} s`;
        barFill.style.width = (ev.pct || 0) + "%";
      } else if (ev.type === "done") {
        spec = ev.spec; barFill.style.width = "100%";
      } else if (ev.type === "error") {
        errMsg = ev.error || "failed";
      }
    });
    if (errMsg) throw new Error(errMsg);
    if (!spec) throw new Error("no result returned");

    currentSpec = spec;
    thumbCut.src = spec.previews.cutout;
    thumbLabel.src = spec.label.image;
    await renderProduct(spec);
    showReport(spec);
    exportBtn.disabled = false;
    const wk = spec.work || {};
    statusEl.textContent = `Reconstructed a ${spec.package.type} · confidence ${spec.quality.confidence} · ${wk.used_s ?? "?"}s (${wk.cutout_iterations ?? "?"} matting passes).`;
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
    <p class="muted">Refined ${spec.work?.cutout_iterations ?? "?"} matting passes in ${spec.work?.used_s ?? "?"}s
       · profile ${spec.work?.profile_points ?? "?"} pts · fit RMSE ${spec.work?.profile_fit_rmse ?? "?"}
       · label confidence ${spec.label.confidence ?? "?"}</p>
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
