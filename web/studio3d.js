/* ReaVector 3D Studio - browser-only PNG/SVG -> 3D extrusion.
 *
 * What this IS:   a fast, offline extrusion of the shape's silhouette (a "cookie
 *                 cutter" 3D), now with the image's own colours and a loading UI.
 * What this is NOT: AI image-to-3D reconstruction (a true 3D bottle from one
 *                 photo) - that needs the GPU model (TripoSR), which is disabled.
 *
 * Performance: shapes are merged per colour (few draw calls), rebuilds are
 * debounced, and the heavy work yields to the browser so the spinner animates.
 */
import * as THREE from "/vendor/three/three.module.js";
import { OrbitControls } from "/vendor/three/addons/controls/OrbitControls.js";
import { SVGLoader } from "/vendor/three/addons/loaders/SVGLoader.js";
import { mergeGeometries } from "/vendor/three/addons/utils/BufferGeometryUtils.js";

const $ = (id) => document.getElementById(id);
const statusEl = $("status"), drop = $("drop"), fileInput = $("file"), emptyEl = $("empty");
const viewport = $("viewport"), meshStats = $("meshStats"), exportBtn = $("exportGlb");
const overlay = $("progress3d"), overlayText = $("overlayText");
const API_KEY = (document.querySelector('meta[name="reavectors-key"]')?.content || "").trim();

const QUALITY = { low: 3, medium: 6, high: 12 };
const MAX_SHAPES = 1200;

let renderer, scene, camera, controls, group, gridHelper;
let sourceSvg = "", sourceName = "model", building = false, rebuildTimer = null;

const raf = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));

// ---------------------------------------------------------------------------
// input
// ---------------------------------------------------------------------------
drop.addEventListener("click", () => fileInput.click());
drop.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
});
fileInput.addEventListener("change", () => fileInput.files[0] && handleFile(fileInput.files[0]));
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); }));
drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) handleFile(f); });

async function handleFile(file) {
  sourceName = (file.name || "model").replace(/\.[^.]+$/, "");
  try {
    let svg;
    if (file.type === "image/svg+xml" || /\.svg$/i.test(file.name)) {
      showOverlay("Loading SVG…");
      svg = await file.text();
    } else if (/^image\//.test(file.type)) {
      showOverlay("Vectorising PNG… (CPU)");
      await raf();
      svg = await vectorize(file);
    } else {
      throw new Error("Unsupported file - drop an SVG or an image (PNG/JPG).");
    }
    sourceSvg = svg;
    exportBtn.disabled = false;
    hideOverlay();
    await rebuild();
  } catch (err) {
    hideOverlay();
    setStatus("Error: " + err.message, true);
  }
}

async function vectorize(file) {
  const headers = { "Content-Type": file.type || "application/octet-stream" };
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  const colors = $("colors") ? $("colors").value : 8;
  const res = await fetch(`/api/vectorize?engine=auto&style=logo&colors=${colors}`, { method: "POST", headers, body: file });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "vectorize failed");
  if (!data.svg) throw new Error("no SVG returned");
  return data.svg;
}

// ---------------------------------------------------------------------------
// three.js scene
// ---------------------------------------------------------------------------
function initThree() {
  if (renderer) return true;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true });
  } catch (e) {
    emptyEl.innerHTML = "WebGL is not available in this browser.";
    return false;
  }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));   // cap DPR -> smoother
  renderer.setSize(viewport.clientWidth, viewport.clientHeight);
  viewport.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.background = new THREE.Color($("bg").value);
  camera = new THREE.PerspectiveCamera(45, viewport.clientWidth / viewport.clientHeight, 0.1, 10000);
  camera.position.set(120, 120, 180);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x223344, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(90, 150, 110); scene.add(key);
  const rim = new THREE.DirectionalLight(0x88bbff, 0.6); rim.position.set(-90, 40, -80); scene.add(rim);

  group = new THREE.Group();
  scene.add(group);
  gridHelper = new THREE.GridHelper(400, 40, 0x2a313c, 0x1d232c);
  gridHelper.visible = $("grid").checked;
  scene.add(gridHelper);

  window.addEventListener("resize", onResize);
  renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
  return true;
}

function onResize() {
  if (!renderer) return;
  const w = viewport.clientWidth, h = viewport.clientHeight;
  camera.aspect = w / h; camera.updateProjectionMatrix(); renderer.setSize(w, h);
}

function disposeGroup() {
  if (!group) return;
  group.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose());
  });
  group.clear();
}

// ---------------------------------------------------------------------------
// build
// ---------------------------------------------------------------------------
function build() {
  const curveSegments = QUALITY[$("quality").value] || 6;
  const useSource = $("srcColors").checked;
  const opts = {
    depth: +$("depth").value, bevel: +$("bevel").value, bevelSeg: +$("bevelSeg").value,
    metalness: +$("metal").value, roughness: +$("rough").value,
    wire: $("wire").checked, curveSegments,
    single: new THREE.Color($("color").value),
  };

  const data = new SVGLoader().parse(sourceSvg);
  // group shapes by fill colour so each colour becomes ONE merged mesh
  const byColor = new Map();
  let totalShapes = 0, skipped = 0;
  for (const p of data.paths) {
    const key = useSource && p.color ? "#" + p.color.getHexString() : "#" + opts.single.getHexString();
    let shapes;
    try { shapes = SVGLoader.createShapes(p); } catch (_) { continue; }
    for (const shape of shapes) {
      if (totalShapes >= MAX_SHAPES) { skipped++; continue; }
      totalShapes++;
      if (!byColor.has(key)) byColor.set(key, []);
      byColor.get(key).push(shape);
    }
  }
  if (!totalShapes) throw new Error("no shapes found in this SVG");

  for (const [hex, shapes] of byColor) {
    const geos = [];
    for (const shape of shapes) {
      const g = new THREE.ExtrudeGeometry(shape, {
        depth: opts.depth, curveSegments: opts.curveSegments,
        bevelEnabled: opts.bevel > 0, bevelThickness: opts.bevel, bevelSize: opts.bevel,
        bevelSegments: opts.bevelSeg || 1,
      });
      g.scale(1, -1, 1);            // SVG Y points down
      geos.push(g);
    }
    const merged = mergeGeometries(geos, false) || geos[0];
    geos.forEach((g) => { if (g !== merged) g.dispose(); });
    merged.computeVertexNormals();
    const mat = new THREE.MeshStandardMaterial({
      color: new THREE.Color(hex), metalness: opts.metalness, roughness: opts.roughness,
      wireframe: opts.wire, side: THREE.DoubleSide, flatShading: false,
    });
    group.add(new THREE.Mesh(merged, mat));
  }

  // centre on origin
  const box = new THREE.Box3().setFromObject(group);
  const c = box.getCenter(new THREE.Vector3());
  group.children.forEach((m) => m.position.sub(c));

  const tri = group.children.reduce((n, m) => n + (m.geometry.index ? m.geometry.index.count : m.geometry.attributes.position.count) / 3, 0);
  return { colors: byColor.size, shapes: totalShapes, triangles: Math.round(tri), skipped };
}

async function rebuild() {
  if (!sourceSvg) return;
  if (building) return;
  building = true;
  showOverlay("Building 3D geometry…");
  await raf();                       // let the overlay paint before the sync work
  try {
    if (!initThree()) return;
    disposeGroup();
    const stats = build();
    fitCamera();
    emptyEl.hidden = true;
    meshStats.textContent = `${stats.colors} colours · ${stats.shapes} shapes · ${stats.triangles.toLocaleString()} triangles`
      + (stats.skipped ? ` · ${stats.skipped} skipped (too detailed)` : "");
    setStatus("Ready - drag to orbit, scroll to zoom, right-drag to pan.");
  } catch (err) {
    setStatus("Error: " + err.message, true);
  } finally {
    building = false;
    hideOverlay();
  }
}

function scheduleRebuild() {
  clearTimeout(rebuildTimer);
  showOverlay("Updating…");
  rebuildTimer = setTimeout(rebuild, 120);   // debounce: don't rebuild per tick
}

function fitCamera() {
  const box = new THREE.Box3().setFromObject(group);
  if (box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z) * 0.5 || 1;
  const dist = (radius / Math.tan((camera.fov * Math.PI) / 360)) * 1.9;
  camera.position.copy(new THREE.Vector3(0.9, 0.8, 1.2).normalize().multiplyScalar(dist));
  camera.near = dist / 100; camera.far = dist * 100; camera.updateProjectionMatrix();
  controls.target.set(0, 0, 0);
  controls.update();
}

// ---------------------------------------------------------------------------
// controls
// ---------------------------------------------------------------------------
const bindLive = (id, out) => {
  const el = $(id), o = out && $(out);
  if (o) el.addEventListener("input", () => (o.textContent = el.value));
  el.addEventListener("input", scheduleRebuild);   // debounced
};
bindLive("depth", "depthOut"); bindLive("bevel", "bevelOut"); bindLive("bevelSeg", "bevelSegOut");
bindLive("metal", "metalOut"); bindLive("rough", "roughOut");
$("color").addEventListener("change", scheduleRebuild);
$("quality").addEventListener("change", scheduleRebuild);
$("colors").addEventListener("input", () => ($("colorsOut").textContent = $("colors").value));
$("srcColors").addEventListener("change", scheduleRebuild);
$("wire").addEventListener("change", scheduleRebuild);
$("grid").addEventListener("change", () => { if (gridHelper) gridHelper.visible = $("grid").checked; });
$("bg").addEventListener("input", () => { if (scene) scene.background = new THREE.Color($("bg").value); });
$("resetCam").addEventListener("click", fitCamera);
exportBtn.addEventListener("click", exportGLB);

// ---------------------------------------------------------------------------
// export
// ---------------------------------------------------------------------------
async function exportGLB() {
  if (!group || !group.children.length) return;
  showOverlay("Exporting .glb…");
  await raf();
  try {
    const { GLTFExporter } = await import("/vendor/three/addons/exporters/GLTFExporter.js");
    new GLTFExporter().parse(group, (buf) => {
      const blob = new Blob([buf], { type: "model/gltf-binary" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${sourceName}.glb`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      setStatus("Saved " + a.download);
    }, (err) => setStatus("GLB export failed: " + (err.message || err), true), { binary: true });
  } catch (e) {
    setStatus("GLB export unavailable: " + e.message, true);
  } finally {
    hideOverlay();
  }
}

// ---------------------------------------------------------------------------
// misc
// ---------------------------------------------------------------------------
function setStatus(msg, error) { statusEl.textContent = msg; statusEl.style.color = error ? "var(--accent-2)" : "var(--muted)"; }
function showOverlay(text) { overlayText.textContent = text; overlay.hidden = false; }
function hideOverlay() { overlay.hidden = true; }
window.addEventListener("pagehide", () => { try { renderer?.dispose(); } catch (_) {} });

window.__reavectors3dReady = true;
