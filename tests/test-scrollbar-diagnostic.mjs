/**
 * Scrollbar Diagnostic Test
 * 
 * Connects to the debug API and compares monitor vs task terminal
 * buffer/viewport state to determine why scrollbar works on monitor
 * but not on tasks.
 * 
 * Usage: node tests/test-scrollbar-diagnostic.mjs <token>
 */

const TOKEN = process.argv[2];
if (!TOKEN) { console.error("Usage: node test-scrollbar-diagnostic.mjs <debug-token>"); process.exit(1); }
const BASE = "http://127.0.0.1:9876";

async function api(method, path, body) {
  const opts = { method, headers: { "X-Debug-Token": TOKEN, "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(`${BASE}${path}`, opts);
  return r.json();
}

async function evalJS(code) {
  const r = await api("POST", "/eval", { code });
  return r.result;
}

function log(label, data) {
  console.log(`\n=== ${label} ===`);
  console.log(typeof data === "string" ? data : JSON.stringify(data, null, 2));
}

async function run() {
  console.log("Scrollbar Diagnostic Test");
  console.log("=".repeat(60));

  // 1. Check how many xterm instances exist and their states
  log("Step 1: Find all xterm terminals", "");
  const terminals = await evalJS(`
    const results = [];
    // Method 1: look for xterm elements
    document.querySelectorAll(".xterm").forEach((el, i) => {
      const r = el.getBoundingClientRect();
      const vp = el.querySelector(".xterm-viewport");
      const screen = el.querySelector(".xterm-screen");
      results.push({
        idx: i,
        visible: r.height > 0 && r.width > 0,
        rect: { top: Math.round(r.top), left: Math.round(r.left), w: Math.round(r.width), h: Math.round(r.height) },
        vpScrollH: vp?.scrollHeight,
        vpClientH: vp?.clientHeight,
        vpScrollTop: vp?.scrollTop,
        vpOverscroll: vp ? getComputedStyle(vp).overscrollBehavior : null,
        screenH: screen?.offsetHeight,
      });
    });
    // Method 2: check __xtermDebug
    const t = window.__xtermDebug;
    let debugTerm = null;
    if (t) {
      const buf = t.buffer?.active;
      const nbuf = t.buffer?.normal;
      const abuf = t.buffer?.alternate;
      debugTerm = {
        cols: t.cols, rows: t.rows,
        activeType: buf === nbuf ? "normal" : "alt",
        activeBaseY: buf?.baseY,
        activeBufLines: buf?.length,
        activeViewportY: buf?.viewportY,
        normalBaseY: nbuf?.baseY,
        normalBufLines: nbuf?.length,
        altBaseY: abuf?.baseY,
        altBufLines: abuf?.length,
        scrollback: t.options?.scrollback,
        hasViewport: !!t._core?._viewport,
        hasQueueSync: !!t._core?._viewport?.queueSync,
        cellHeight: t._core?._renderService?.dimensions?.css?.cell?.height,
      };
    }
    return { xtermElements: results.length, elements: results, debugTerm };
  `);
  log("Terminals found", terminals);

  // 2. Check the actual scroll-area and slider heights
  log("Step 2: Scroll DOM state", "");
  const scrollState = await api("GET", "/xterm-scroll").catch(() => ({ error: "endpoint failed" }));
  log("Scroll DOM", scrollState);

  // 3. Check xterm internal state
  log("Step 3: xterm internal state", "");
  const xtermState = await api("GET", "/xterm-debug").catch(() => ({ error: "endpoint failed" }));
  log("xterm internals", xtermState);

  // 4. Check what happens with queueSync
  log("Step 4: Try queueSync fix", "");
  const fixResult = await api("POST", "/xterm-fix", { strategy: "queueSync" }).catch(e => ({ error: e.message }));
  log("queueSync result", fixResult);

  // 5. Check PTY buffer for alt screen sequences
  log("Step 5: Check for alt screen sequences in PTY buffer", "");
  const altCheck = await evalJS(`
    const t = window.__xtermDebug;
    if (!t) return "no terminal";
    // Can't check PTY buffer from renderer, but can check terminal modes
    return {
      activeBufferType: t.buffer?.active === t.buffer?.normal ? "normal" : "alt",
      normalBuffer: {
        baseY: t.buffer?.normal?.baseY,
        length: t.buffer?.normal?.length,
        // Check first and last few lines of normal buffer
        firstLine: t.buffer?.normal?.getLine(0)?.translateToString()?.substring(0, 80),
        lastLine: t.buffer?.normal?.getLine(t.buffer?.normal?.length - 1)?.translateToString()?.substring(0, 80),
      },
      altBuffer: {
        baseY: t.buffer?.alternate?.baseY,
        length: t.buffer?.alternate?.length,
        firstLine: t.buffer?.alternate?.getLine(0)?.translateToString()?.substring(0, 80),
        lastLine: t.buffer?.alternate?.getLine(t.buffer?.alternate?.length - 1)?.translateToString()?.substring(0, 80),
      },
    };
  `);
  log("Buffer state", altCheck);

  // 6. Compare: what does the viewport _sync() calculation look like?
  log("Step 6: Simulate viewport sync math", "");
  const syncMath = await evalJS(`
    const t = window.__xtermDebug;
    if (!t) return "no terminal";
    const vp = t._core?._viewport;
    const buf = t.buffer?.active;
    const cellH = t._core?._renderService?.dimensions?.css?.cell?.height || 0;
    const vpEl = t.element?.querySelector(".xterm-viewport");
    const scrollArea = t.element?.querySelector(".xterm-scroll-area");
    
    // This is what _sync() does internally:
    const scrollHeight = buf ? buf.length * cellH : 0;
    const termHeight = t.rows * cellH;
    const hasScroll = scrollHeight > termHeight;
    
    return {
      bufferLines: buf?.length,
      rows: t.rows,
      cellHeight: cellH ? Math.round(cellH * 100) / 100 : 0,
      calculatedScrollH: Math.round(scrollHeight),
      calculatedTermH: Math.round(termHeight),
      hasScrollback: hasScroll,
      ratio: cellH ? (buf?.length / t.rows).toFixed(2) : "no cellH",
      // What the DOM currently shows
      domVpScrollH: vpEl?.scrollHeight,
      domVpClientH: vpEl?.clientHeight,
      domScrollAreaH: scrollArea?.style?.height,
      domScrollAreaComputed: scrollArea ? scrollArea.offsetHeight : null,
      // The thumb height would be: clientH / scrollH * clientH
      thumbRatio: vpEl ? (vpEl.clientHeight / (vpEl.scrollHeight || 1)).toFixed(3) : null,
    };
  `);
  log("Viewport sync math", syncMath);

  // 7. Try resize-bump fix and measure before/after
  log("Step 7: Try resize-bump to force sync", "");
  const resizeFix = await api("POST", "/xterm-fix", { strategy: "resize-bump" }).catch(e => ({ error: e.message }));
  log("resize-bump result", resizeFix);

  // 8. After resize-bump, re-check state
  await new Promise(r => setTimeout(r, 500));
  log("Step 8: State after resize-bump", "");
  const afterFix = await evalJS(`
    const t = window.__xtermDebug;
    if (!t) return "no terminal";
    const buf = t.buffer?.active;
    const vpEl = t.element?.querySelector(".xterm-viewport");
    return {
      activeType: buf === t.buffer?.normal ? "normal" : "alt",
      baseY: buf?.baseY,
      bufLines: buf?.length,
      rows: t.rows,
      vpScrollH: vpEl?.scrollHeight,
      vpClientH: vpEl?.clientHeight,
      vpScrollTop: vpEl?.scrollTop,
    };
  `);
  log("After resize-bump", afterFix);

  // Summary
  console.log("\n" + "=".repeat(60));
  console.log("DIAGNOSIS:");
  if (xtermState?.activeBufferType === "alternate") {
    console.log("• Terminal is in ALT SCREEN (Ink TUI active)");
    console.log("• Alt screen has ZERO scrollback by design");
    console.log("• Scrollbar correctly shows 100% (nothing to scroll)");
    console.log("• Normal buffer underneath has: baseY=" + xtermState?.normalBaseY + " lines=" + xtermState?.normalBufLines);
    console.log("• When TUI exits alt screen, normal buffer restores → scrollbar should work");
  } else {
    console.log("• Terminal is in NORMAL buffer");
    console.log("• baseY=" + xtermState?.baseY + " bufLines=" + xtermState?.bufferLines + " rows=" + xtermState?.rows);
    if (xtermState?.baseY > 0) {
      console.log("• Has scrollback — scrollbar SHOULD work");
      if (syncMath?.domVpScrollH <= syncMath?.domVpClientH) {
        console.log("• BUG: DOM scrollHeight <= clientHeight despite scrollback!");
        console.log("• viewport._sync() is not updating scroll-area height");
      }
    } else {
      console.log("• No scrollback — scrollbar correctly shows 100%");
    }
  }
}

run().catch(e => { console.error("FATAL:", e.message); process.exit(1); });
