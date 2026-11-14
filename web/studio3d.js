/* ReaVector 3D Studio — browser-only PNG/SVG -> 3D extrusion.
 *
 * No GPU and no AWS: SVG parsing + extrusion happen locally in the browser with
 * geometry from three.js (vendored under /vendor/three so the strict CSP holds).
 * A PNG is first turned into an SVG by the existing CPU vectorizer (/api/vectorize).
 */
import * as THREE from "/vendor/three/three.module.js";
import { OrbitControls } from "/vendor/three/addons/controls/OrbitControls.js";
import { SVGLoader } from "/vendor/three/addons/loaders/SVGLoader.js";
import { GLTFExporter } from "/vendor/three/addons/exporters/GLTFExporter.js";

const $ = (id) => document.getElementById(id);
const statusEl = $("status"), drop = $("drop"), fileInput = $("file"), emptyEl = $("empty");
const viewport = $("viewport"), meshStats = $("meshStats"), exportBtn = $("exportGlb");
const API_KEY = (document.querySelector('meta[name="reavectors-key"]')?.content || "").trim();

let renderer, scene, camera, controls, group, currentSvgText = "", currentMesh = null;
let sourceName = "model";

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
    if (file.type === "image/svg+xml" || /\.svg$/i.test(file.name)) {
      setStatus("Loading SVG…");
      currentSvgText = await file.text();
    } else if (/^image\//.test(file.type)) {
      setStatus("Vectorising PNG (CPU)…");
      currentSvgText = await vectorize(file);
    } else {
      throw new Error("Unsupported file — drop an SVG or an image.");
    }
    rebuild();
    exportBtn.disabled = false;
  } catch (err) {
    setStatus("Error: " + err.message, true);
  }
}

async function vectorize(file) {
  const headers = { "Content-Type": file.type || "application/octet-stream" };
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  const res = await fetch("/api/vectorize?engine=auto&style=logo", { method: "POST", headers, body: file });
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
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: false });
  } catch (e) {
    emptyEl.innerHTML = "WebGL is not available in this browser.";
    return false;
  }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(viewport.clientWidth, viewport.clientHeight);
  viewport.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.background = new THREE.Color($("bg").value);

  camera = new THREE.PerspectiveCamera(45, viewport.clientWidth / viewport.clientHeight, 0.1, 5000);
  camera.position.set(120, 120, 180);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x223344, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(80, 140, 100);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x88bbff, 0.6);
  rim.position.set(-90, 40, -80);
  scene.add(rim);

  group = new THREE.Group();
  scene.add(group);

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

function buildFromSVG(svgText, opts) {
  const data = new SVGLoader().parse(svgText);
  const shapes = [];
  for (const p of data.paths) {
    try { for (const s of SVGLoader.createShapes(p)) shapes.push(s); } catch (_) { /* skip malformed path */ }
  }
  if (!shapes.length) throw new Error("no shapes found in the SVG");
  const material = new THREE.MeshStandardMaterial({
    color: new THREE.Color(opts.color),
    metalness: opts.metalness, roughness: opts.roughness,
    wireframe: opts.wire, side: THREE.DoubleSide,
  });
  let tri = 0;
  for (const shape of shapes) {
    const geo = new THREE.ExtrudeGeometry(shape, {
      depth: opts.depth, bevelEnabled: opts.bevel > 0,
      bevelThickness: opts.bevel, bevelSize: opts.bevel, bevelSegments: opts.bevelSeg || 1,
      curveSegments: 12,
    });
    geo.scale(1, -1, 1);              // SVG Y is down
    geo.computeVertexNormals();
    tri += geo.attributes.position.count / 3;
    group.add(new THREE.Mesh(geo, material));
  }
  group.position.set(0, 0, 0);
  const box = new THREE.Box3().setFromObject(group);
  const center = box.getCenter(new THREE.Vector3());
  group.children.forEach((m) => m.position.sub(center));
  return { shapes: shapes.length, triangles: Math.round(tri) };
}

function rebuild() {
  if (!initThree()) return;
  setStatus("Building 3D geometry…");
  try {
    disposeGroup();
    const opts = {
      depth: +$("depth").value, bevel: +$("bevel").value, bevelSeg: +$("bevelSeg").value,
      color: $("color").value, metalness: +$("metal").value, roughness: +$("rough").value,
      wire: $("wire").checked,
    };
    const stats = buildFromSVG(currentSvgText, opts);
    fitCamera();                                    // also creates the grid
    if (gridHelper) gridHelper.visible = $("grid").checked;
    emptyEl.hidden = true;
    meshStats.textContent = `${stats.shapes} shapes · ${stats.triangles.toLocaleString()} triangles`;
    setStatus("Ready. Drag to orbit, scroll to zoom, right-drag to pan.");
  } catch (err) {
    setStatus("Error: " + err.message, true);
  }
}

let gridHelper;
function ensureGrid() {
  if (gridHelper) return;
  gridHelper = new THREE.GridHelper(400, 40, 0x2a313c, 0x1d232c);
  scene.add(gridHelper);
}

function fitCamera() {
  ensureGrid();
  const box = new THREE.Box3().setFromObject(group);
  if (box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z) * 0.5 || 1;
  const dist = radius / Math.tan((camera.fov * Math.PI) / 360) * 1.9;
  const dir = new THREE.Vector3(0.9, 0.8, 1.2).normalize();
  camera.position.copy(dir.multiplyScalar(dist));
  camera.near = dist / 100; camera.far = dist * 100; camera.updateProjectionMatrix();
  controls.target.set(0, 0, 0);
  controls.update();
}

// ---------------------------------------------------------------------------
// controls
// ---------------------------------------------------------------------------
const bind = (id, out) => { const el = $(id), o = out && $(out); if (o) el.addEventListener("input", () => (o.textContent = el.value)); el.addEventListener("change", rebuild); };
bind("depth", "depthOut"); bind("bevel", "bevelOut"); bind("bevelSeg", "bevelSegOut");
bind("color"); bind("metal", "metalOut"); bind("rough", "roughOut");
$("wire").addEventListener("change", rebuild);
$("grid").addEventListener("change", () => { if (gridHelper) gridHelper.visible = $("grid").checked; });
$("bg").addEventListener("input", () => { if (scene) scene.background = new THREE.Color($("bg").value); });
$("resetCam").addEventListener("click", fitCamera);
exportBtn.addEventListener("click", exportGLB);

// ---------------------------------------------------------------------------
// export
// ---------------------------------------------------------------------------
function exportGLB() {
  if (!group || !group.children.length) return;
  setStatus("Exporting GLB…");
  new GLTFExporter().parse(group, (buf) => {
    const blob = new Blob([buf], { type: "model/gltf-binary" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${sourceName}.glb`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    setStatus("Saved " + a.download);
  }, (err) => setStatus("GLB export failed: " + err.message, true), { binary: true });
}

// ---------------------------------------------------------------------------
// misc
// ---------------------------------------------------------------------------
function setStatus(msg, error) { statusEl.textContent = msg; statusEl.style.color = error ? "var(--accent-2)" : "var(--muted)"; }
window.addEventListener("pagehide", () => { try { renderer?.dispose(); } catch (_) {} });
