// Loft for Windows, macOS and Linux: a window onto your Loft library.
//
// The first time, it asks for the server's address (start.html), checks there's a Loft server
// there and remembers it. After that it opens straight onto the server's web app.
//
// Opening with no connection: Loft's web app keeps its own files with a service worker, which
// browsers only allow on secure (https) addresses. A home server is usually plain http, so the app
// tells Chromium to treat that one address as secure; from the next start it opens offline too,
// onto the books downloaded in it.

const { app, BrowserWindow, ipcMain, Menu, net, session, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { startUpdates } = require("./updater");

app.setName("Loft");
if (process.platform === "win32") app.setAppUserModelId("app.loft.desktop");

const START = path.join(__dirname, "start.html");
const settingsFile = () => path.join(app.getPath("userData"), "settings.json");
let win = null;
let updates = { checkNow: () => {} };

function readSettings() {
  try { return JSON.parse(fs.readFileSync(settingsFile(), "utf8")); } catch { return {}; }
}

function writeSettings(patch) {
  const next = { ...readSettings(), ...patch };
  fs.mkdirSync(path.dirname(settingsFile()), { recursive: true });
  fs.writeFileSync(settingsFile(), JSON.stringify(next, null, 2));
  return next;
}

// Must be set before the app is ready: the saved server counts as a secure address (see the top).
{
  const saved = readSettings().server;
  try {
    if (saved && new URL(saved).protocol === "http:") {
      app.commandLine.appendSwitch("unsafely-treat-insecure-origin-as-secure", new URL(saved).origin);
    }
  } catch { /* a bad saved address: the start screen will ask again */ }
}

/** What was typed ("192.168.1.20:4545") as a full address, or null. */
function normalize(input) {
  let s = String(input || "").trim();
  if (!s) return null;
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(s)) s = `http://${s}`;
  try {
    const u = new URL(s);
    if (!/^https?:$/.test(u.protocol) || !u.hostname) return null;
    return `${u.origin}${u.pathname.replace(/\/(index\.html)?$/, "")}`;
  } catch {
    return null;
  }
}

/** Null if a Loft server answers at `url`, else a message to show. */
async function check(url) {
  try {
    const res = await net.fetch(`${url}/api/ping`, { cache: "no-store", signal: AbortSignal.timeout(7000) });
    const body = res.ok ? await res.json().catch(() => null) : null;
    return body?.app === "loft" ? null : `${url.replace(/^https?:\/\//, "")} answered, but it isn’t a Loft server.`;
  } catch {
    return `Couldn’t reach ${url.replace(/^https?:\/\//, "")}. Check the address, and that the server is running and on the same network.`;
  }
}

function showStart(error = "") {
  const server = (readSettings().server || "").replace(/^https?:\/\//, "");
  win.loadFile(START, { query: { server, error } });
}

function openServer() {
  const { server } = readSettings();
  if (!server) return showStart();
  win.loadURL(`${server}/`);
}

const serverOrigin = () => {
  try { return new URL(readSettings().server).origin; } catch { return null; }
};

function createWindow() {
  const saved = readSettings().bounds;
  win = new BrowserWindow({
    width: saved?.width ?? 1280,
    height: saved?.height ?? 860,
    x: saved?.x,
    y: saved?.y,
    minWidth: 360,
    minHeight: 500,
    title: "Loft",
    backgroundColor: "#14110f",
    autoHideMenuBar: true,
    icon: path.join(__dirname, "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  if (saved?.maximized) win.maximize();

  const remember = () => {
    if (!win || win.isMinimized()) return;
    writeSettings({ bounds: { ...(win.isMaximized() ? readSettings().bounds : win.getBounds()), maximized: win.isMaximized() } });
  };
  win.on("close", remember);

  // Links to anywhere else open in the browser.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    const origin = serverOrigin();
    if (url.startsWith("file:") || (origin && url.startsWith(origin))) return;
    e.preventDefault();
    if (/^https?:/i.test(url)) shell.openExternal(url);
  });
  // The server can't be reached and the app wasn't kept for offline: back to the start screen.
  win.webContents.on("did-fail-load", (_e, code, _desc, url, isMainFrame) => {
    if (!isMainFrame || code === -3 || url.startsWith("file:")) return; // -3: a load replaced by another
    showStart(`Couldn’t reach ${(readSettings().server || "").replace(/^https?:\/\//, "")}. Is the server running? Try again, or enter another address.`);
  });
  // The page title is the library's name: keep the window's in step.
  win.webContents.on("page-title-updated", (e, title) => { e.preventDefault(); win.setTitle(title || "Loft"); });
  openServer();
}

function buildMenu() {
  // The menu bar stays hidden (Alt shows it); its shortcuts work either way.
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    ...(process.platform === "darwin" ? [{ role: "appMenu" }] : []),
    { label: "Loft", submenu: [
      { label: "Change server…", click: () => showStart() },
      { label: "Check for updates…", click: () => updates.checkNow() },
      { type: "separator" },
      { role: "quit" },
    ] },
    { role: "editMenu" },
    { label: "View", submenu: [
      { role: "reload" },
      { role: "togglefullscreen" },
      { type: "separator" },
      { role: "zoomIn" }, { role: "zoomOut" }, { role: "resetZoom" },
      { type: "separator" },
      { role: "toggleDevTools" },
    ] },
  ]));
}

ipcMain.handle("loft:connect", async (_e, input) => {
  const url = normalize(input);
  if (!url) return "That doesn’t look like a server address. Try something like 192.168.1.20:4545.";
  const problem = await check(url);
  if (problem) return problem;
  writeSettings({ server: url });
  win.loadURL(`${url}/`);
  return null;
});
ipcMain.on("loft:get-server", (e) => { e.returnValue = readSettings().server || ""; });
ipcMain.on("loft:change-server", () => showStart());

// One Loft at a time: opening it again brings the window forward.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!win) return;
    if (win.isMinimized()) win.restore();
    win.focus();
  });
  app.whenReady().then(() => {
    // Nothing the page asks for beyond full screen and copying.
    session.defaultSession.setPermissionRequestHandler((_wc, permission, done) => {
      done(["fullscreen", "clipboard-sanitized-write"].includes(permission));
    });
    buildMenu();
    createWindow();
    updates = startUpdates(() => win, { read: readSettings, write: writeSettings });
  });
  app.on("window-all-closed", () => app.quit());
  // Keep the sign-in (and the rest of the cookie jar) on disk, however the app is closed:
  // logging out or shutting down sends a terminate signal, which would otherwise skip that.
  app.on("before-quit", () => { session.defaultSession.cookies.flushStore().catch(() => {}); });
  for (const signal of ["SIGTERM", "SIGINT"]) process.on(signal, () => app.quit());
}
