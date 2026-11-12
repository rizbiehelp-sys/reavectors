/* reavectors front-end: drag a transparent PNG, trace locally, download. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const drop = $("drop"), fileInput = $("file"), convertBtn = $("convert");
  const statusEl = $("status"), resultBox = $("resultBox"), emptyEl = $("empty");
  const sourceImg = $("sourceImg"), statsEl = $("stats");
  const style = $("style"), detail = $("detail"), detailOut = $("detailOut");
  const refine = $("refine"), refineSecs = $("refineSecs"), refineOut = $("refineOut");
  const progress = $("progress"), progressTitle = $("progressTitle"), progressDetail = $("progressDetail");
  const dl = { svg: $("dlSvg"), ai: $("dlAi"), eps: $("dlEps") };

  let currentFile = null;
  let currentSvg = "";
  let refineState = { match: null, engine: null };

  detail.addEventListener("input", () => (detailOut.textContent = detail.value));
  refineSecs.addEventListener("input", () => (refineOut.textContent = refineSecs.value));

  // Report which server build we're talking to (catches a stale running server).
  fetch("/api/health").then((r) => r.json()).then((h) => {
    const el = $("serverVersion");
    if (!el) return;
    if ((h.features || []).includes("refine")) {
      el.textContent = `server ${h.version}`;
    } else {
      el.textContent = `server ${h.version} (outdated — restart it)`;
      el.style.color = "var(--accent-2)";
    }
  }).catch(() => {
    const el = $("serverVersion");
    if (el) { el.textContent = "server offline"; el.style.color = "var(--accent-2)"; }
  });

  // -- input handling -----------------------------------------------------
  drop.addEventListener("click", () => fileInput.click());
  drop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
  });
  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) accept(fileInput.files[0]);
  });

  ["dragenter", "dragover"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); }));
  drop.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files[0];
    if (f) accept(f);
  });
  window.addEventListener("paste", (e) => {
    const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
    if (item) accept(item.getAsFile());
  });

  function accept(file) {
    if (!file || !(file.type || "").startsWith("image/")) {
      setStatus("Please choose an image file.", true);
      return;
    }
    currentFile = file;
    sourceImg.src = URL.createObjectURL(file);
    sourceImg.hidden = false;
    emptyEl.hidden = true;
    resultBox.innerHTML = "";
    currentSvg = "";
    setButtons(false);
    convertBtn.disabled = false;
    setStatus(`Loaded ${file.name} (${(file.size / 1024).toFixed(1)} KB). Ready.`);
  }

  // -- convert ------------------------------------------------------------
  convertBtn.addEventListener("click", doConvert);
  async function doConvert() {
    if (!currentFile) return;
    const useRefine = refine.checked;
    convertBtn.disabled = true;
    convertBtn.classList.add("busy");
    setButtons(false);

    const started = performance.now();
    refineState = { match: null, engine: null };
    showProgress("Refining…", "starting backend");
    const ticker = setInterval(() => {
      if (progress.hidden) return;
      const secs = ((performance.now() - started) / 1000).toFixed(1);
      progressDetail.textContent = refineState.match === null
        ? `${secs}s · starting backend…`
        : `${secs}s · match ${refineState.match}% · ${refineState.engine}`;
    }, 100);

    try {
      if (useRefine) {
        await streamRefine(started);
      } else {
        const res = await fetch("/api/vectorize?" + params(), {
          method: "POST",
          headers: { "Content-Type": currentFile.type || "application/octet-stream" },
          body: currentFile,
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "conversion failed");
        applyResult(data);
      }
    } catch (err) {
      setStatus("Error: " + err.message, true);
      hideProgress();
    } finally {
      clearInterval(ticker);
      convertBtn.disabled = !currentFile;
      convertBtn.classList.remove("busy");
    }
  }

  // Streams Server-Sent Events from /api/refine for live progress.
  async function streamRefine(started) {
    const res = await fetch("/api/refine?" + params(), {
      method: "POST",
      headers: { "Content-Type": currentFile.type || "application/octet-stream" },
      body: currentFile,
    });
    if (!res.ok || !res.body) {
      const j = await res.json().catch(() => ({}));
      throw new Error(j.error || "refine request failed");
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let finished = false;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let sep;
      while ((sep = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, sep);
        buf = buf.slice(sep + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        const evt = JSON.parse(line.slice(5).trim());
        if (evt.type === "progress") {
          refineState = { match: evt.match, engine: evt.engine };
          progressTitle.textContent = `Refining… pass ${evt.pass}`;
        } else if (evt.type === "done") {
          applyResult(evt);
          finished = true;
        } else if (evt.type === "error") {
          throw new Error(evt.error);
        }
      }
    }
    if (!finished) throw new Error("refine stream ended without a result");
  }

  function applyResult(data) {
    currentSvg = data.svg;
    resultBox.innerHTML = data.svg;
    sourceImg.hidden = true;
    setTab("result");
    renderStats(data);
    setButtons(true);
    hideProgress();
    const refined = data.match !== undefined
      ? ` refined ${data.passes}× in ${data.seconds}s, match ${data.match}%`
      : "";
    setStatus(`Done (${data.engine}) — ${data.colors} colours, ${data.figures} shapes${refined}.`);
  }

  function showProgress(title, detail) {
    progressTitle.textContent = title;
    progressDetail.textContent = detail;
    progress.hidden = false;
  }
  function hideProgress() { progress.hidden = true; }

  function renderStats(d) {
    const items = [
      `<li>engine <b>${d.engine}</b></li>`,
      `<li><b>${d.width}</b>&times;<b>${d.height}</b> px</li>`,
      `<li><b>${d.colors}</b> colours</li>`,
      `<li><b>${d.figures}</b> shapes</li>`,
      `<li><b>${d.subpaths}</b> subpaths</li>`,
    ];
    if (d.match !== undefined) {
      items.push(`<li>match <b>${d.match}%</b> (${d.passes} passes)</li>`);
    }
    (d.palette || []).slice(0, 12).forEach((hex) => {
      items.push(`<li><span class="swatch" style="background:${hex}"></span>${hex}</li>`);
    });
    statsEl.innerHTML = items.join("");
  }

  // -- downloads ----------------------------------------------------------
  Object.entries(dl).forEach(([fmt, btn]) =>
    btn.addEventListener("click", () => doDownload(fmt)));

  async function doDownload(fmt) {
    if (!currentFile) return;
    setStatus(`Preparing .${fmt}…`);
    try {
      const q = params();
      q.set("format", fmt);
      q.set("name", stripExt(currentFile.name));
      const res = await fetch("/api/export?" + q, {
        method: "POST",
        headers: { "Content-Type": currentFile.type || "application/octet-stream" },
        body: currentFile,
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.error || "export failed");
      }
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${stripExt(currentFile.name)}.${fmt}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      setStatus(`Saved ${a.download}.`);
    } catch (err) {
      setStatus("Error: " + err.message, true);
    }
  }

  // -- preview tabs -------------------------------------------------------
  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => setTab(t.dataset.view)));
  function setTab(view) {
    document.querySelectorAll(".tab").forEach((t) =>
      t.classList.toggle("active", t.dataset.view === view));
    if (view === "source") {
      sourceImg.hidden = !currentFile;
      resultBox.style.display = "none";
    } else {
      sourceImg.hidden = true;
      resultBox.style.display = currentSvg ? "grid" : "none";
    }
    emptyEl.hidden = !!currentFile;
  }

  // -- misc ---------------------------------------------------------------
  function params() {
    const p = new URLSearchParams({
      engine: "auto",
      style: style.value,
      detail: detail.value,
    });
    if (refine.checked) p.set("refine", refineSecs.value);
    return p;
  }
  function setButtons(on) { Object.values(dl).forEach((b) => (b.disabled = !on)); }
  function setStatus(msg, error) {
    statusEl.textContent = msg;
    statusEl.style.color = error ? "var(--accent-2)" : "var(--muted)";
  }
  const stripExt = (n) => n.replace(/\.[^.]+$/, "");

  setTab("result");
})();
