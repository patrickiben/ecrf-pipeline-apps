// launch.js: starts one eCRF app entirely in the visitor's browser with stlite (Streamlit on Pyodide).
//
// Each page (docs/app/<app>.html, rendered by tools/sync_browser_apps.py) carries its settings as JSON in
// <script id="stlite-config">: the pinned stlite module, the Pyodide build it is made for, the app's .py file
// and synthetic data (byte-identical copies under docs/app/, checked in CI), the wheels to preload and the
// requirements. The files are fetched from this site, written into the in-browser file system and run
// there; there is no server, and the page's Content-Security-Policy only lets it connect to this site and
// the CDN.
//
// ECRF_HOSTED=1 turns on the apps' own public-demo lock: the bundled synthetic cut is forced, every upload
// and path input is disabled, a banner says so, and the audit records hosted_mode=true.

const $ = (id) => document.getElementById(id);
const absolute = (path) => new URL(path, document.baseURI).href;
const RUN_LOCALLY = "Reloading the page usually helps after a network error. To use your own files, run the app locally (see the README on GitHub).";
let settled = false;

function setStep(text) {
  if (!settled && text) $("boot-step").textContent = text;
}

function ready() {
  if (settled) return;
  settled = true;
  $("boot").hidden = true;
  document.body.classList.add("app-ready");
}

// One readable line from an error (a Python traceback's last "...Error: ..." line, for example).
function brief(err) {
  const text = String((err && err.message) || err || "unknown error").trim();
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const pick = [...lines].reverse().find((l) => /\w(Error|Exception)\b|Failed/.test(l)) || lines[0] || text;
  return pick.length > 200 ? `${pick.slice(0, 197)}...` : pick;
}

function fail(reason) {
  if (settled) return;
  settled = true;
  document.body.classList.add("app-failed");
  $("boot-text").textContent = "The app could not start in this browser.";
  $("boot-step").textContent = "The screenshot below shows its results on the bundled synthetic data.";
  const box = $("boot-error");
  box.textContent = `${reason} ${RUN_LOCALLY}`;
  box.hidden = false;
}

// Pyodide 314 runs Python in a module worker (Chrome 80+, Safari 15+, Firefox 114+).
function supportsModuleWorkers() {
  let asked = false;
  try {
    const url = URL.createObjectURL(new Blob([""], { type: "text/javascript" }));
    const w = new Worker(url, { get type() { asked = true; return "module"; } });
    w.terminate();
    URL.revokeObjectURL(url);
  } catch {
    return false;
  }
  return asked;
}

// The app is up once its first render reaches the page (its title). The timer is a backstop so the
// notice never stays over a live app; it starts when Python reports it has loaded.
function waitForFirstRender(root) {
  const rendered = () => root.querySelector('[data-testid="stMain"] h1, [data-testid="stHeading"]');
  const observer = new MutationObserver(() => {
    if (rendered()) { observer.disconnect(); ready(); }
  });
  observer.observe(root, { childList: true, subtree: true });
  if (rendered()) { observer.disconnect(); ready(); }
  return (ms) => setTimeout(() => { observer.disconnect(); ready(); }, ms);
}

async function main() {
  const cfg = JSON.parse($("stlite-config").textContent);
  if (typeof WebAssembly !== "object" || !supportsModuleWorkers()) {
    return fail("It needs WebAssembly and module workers, which this browser does not provide; a current Chrome, Edge, Firefox or Safari does.");
  }
  setTimeout(() => setStep("Still starting. On a slow connection or an older device the first visit can take a minute or more."), 45000);

  let stlite;
  try {
    stlite = await import(cfg.stlite);
  } catch (e) {
    return fail(`The in-browser runtime did not load from the CDN (${brief(e)}).`);
  }

  const root = $("root");
  const files = {};
  for (const path of [cfg.entry, ...cfg.data]) files[path] = { url: absolute(path) };
  setStep("Loading Python.");
  const controller = stlite.mount(
    {
      entrypoint: cfg.entry,
      files,
      requirements: cfg.requirements,
      // Preloaded before micropip runs, so Streamlit's dependency check finds them installed and nothing
      // is fetched from PyPI.
      prebuiltPackageNames: cfg.wheels.map(absolute),
      pyodideUrl: cfg.pyodide,
      env: { ECRF_HOSTED: "1" },
      streamlitConfig: {
        "browser.gatherUsageStats": false,
        "client.toolbarMode": "viewer",
      },
      disableProgressToasts: true,   // progress shows in the notice above the app instead
    },
    root,
  );

  // The kernel's load events are not part of stlite's documented API, so each use is guarded; without
  // them the notice simply stays up until the first render.
  const backstop = waitForFirstRender(root);
  const kernel = controller && controller._kernel;
  if (kernel && typeof kernel.addEventListener === "function") {
    kernel.addEventListener("loadProgress", (e) => setStep(String((e && e.detail) || "")));
    kernel.addEventListener("loadError", (e) => {
      fail(`Python failed to start (${brief(e && e.detail)}).`);
    });
    kernel.addEventListener("loadFinished", () => { setStep("Running the app."); backstop(20000); });
  } else {
    backstop(180000);
  }
}

main().catch((e) => fail(`Unexpected error (${brief(e)}).`));
