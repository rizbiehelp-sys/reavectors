/* Load guard for the 3D Studio.
 *
 * A classic (non-module) script so it always runs even if the ES module graph
 * fails to load. If the module hasn't signalled readiness shortly after load,
 * show a clear message instead of a silently-dead "drop an SVG or PNG" area.
 */
setTimeout(function () {
  if (window.__reavectors3dReady) return;
  var s = document.getElementById("status");
  if (s) {
    s.textContent = "3D engine failed to load. Hard-refresh (Ctrl+F5 / Cmd+Shift+R). "
      + "If it persists, open the browser DevTools Console and send the error text.";
    s.style.color = "#fe564b";
  }
  var d = document.getElementById("drop");
  if (d) d.title = "3D engine failed to load";
}, 4000);
