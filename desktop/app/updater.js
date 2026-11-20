// Keeping the app itself up to date, from Loft's releases on GitHub.
//
// On Windows and as an AppImage on Linux the new version downloads by itself, then the app asks:
// restart now, or when Loft is closed. macOS only lets apps signed by a paid Apple developer
// replace themselves, and .deb/.rpm installs belong to the system's package manager, so there it
// says a new version is out and opens the download page when asked.
//
// It looks a little after starting and then once a day; nothing about the library is sent.

const { app, dialog, net, shell } = require("electron");

const RELEASES = "https://github.com/Spinjitsudoom/Loft/releases/latest";
const LATEST = "https://api.github.com/repos/Spinjitsudoom/Loft/releases/latest";
const DAY = 24 * 60 * 60 * 1000;

const selfUpdating = process.platform === "win32" || (process.platform === "linux" && !!process.env.APPIMAGE);

function parse(v) {
  const m = /^v?(\d+)\.(\d+)\.(\d+)$/.exec(String(v || "").trim());
  return m ? m.slice(1).map(Number) : null;
}

function newer(candidate, than) {
  const a = parse(candidate), b = parse(than);
  if (!a || !b) return false;
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] > b[i];
  return false;
}

/** Start checking. `win()` gives the window to ask in; `settings` reads and writes saved choices. */
function startUpdates(win, settings) {
  if (!app.isPackaged) return { checkNow: () => {} };
  return selfUpdating ? withUpdater(win) : withNotice(win, settings);
}

function withUpdater(win) {
  const { autoUpdater } = require("electron-updater");
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = false;  // only once they've said so
  let asked = null;
  let manual = false;

  autoUpdater.on("update-downloaded", async (info) => {
    if (asked === info.version) return;
    asked = info.version;
    const { response } = await dialog.showMessageBox(win(), {
      type: "info",
      title: "Update ready",
      message: `Loft ${info.version} is ready to install.`,
      detail: "It takes a moment, and Loft opens again where you were.",
      buttons: ["Restart now", "When I close Loft"],
      defaultId: 0,
      cancelId: 1,
    });
    if (response === 0) autoUpdater.quitAndInstall(false, true);
    else autoUpdater.autoInstallOnAppQuit = true;
  });
  autoUpdater.on("update-not-available", () => {
    if (manual) dialog.showMessageBox(win(), { type: "info", message: `Loft ${app.getVersion()} is the newest version.` });
    manual = false;
  });
  autoUpdater.on("error", (e) => {
    if (manual) dialog.showMessageBox(win(), { type: "warning", message: "Loft couldn’t check for a new version.", detail: String(e?.message || e) });
    manual = false;
  });

  const check = () => autoUpdater.checkForUpdates().catch(() => {});
  setTimeout(check, 15_000);
  setInterval(check, DAY);
  return { checkNow: () => { manual = true; check(); } };
}

function withNotice(win, settings) {
  async function check(manual = false) {
    let version = "";
    try {
      const res = await net.fetch(LATEST, { headers: { Accept: "application/vnd.github+json" }, signal: AbortSignal.timeout(15_000) });
      const release = res.ok ? await res.json() : null;
      if (release && !release.draft && !release.prerelease) version = String(release.tag_name || "").replace(/^v/, "");
    } catch { /* offline: try again tomorrow */ }
    if (!version) {
      if (manual) dialog.showMessageBox(win(), { type: "warning", message: "Loft couldn’t check for a new version." });
      return;
    }
    if (!newer(version, app.getVersion())) {
      if (manual) dialog.showMessageBox(win(), { type: "info", message: `Loft ${app.getVersion()} is the newest version.` });
      return;
    }
    if (!manual && settings.read().skippedUpdate === version) return;  // they said Later to this one
    const { response } = await dialog.showMessageBox(win(), {
      type: "info",
      title: "New version",
      message: `Loft ${version} is out.`,
      detail: process.platform === "darwin"
        ? "Download it, then drag it into Applications in place of this one."
        : "Download it and install it the way you installed this one.",
      buttons: ["Download", "Later"],
      defaultId: 0,
      cancelId: 1,
    });
    if (response === 0) shell.openExternal(RELEASES);
    else settings.write({ skippedUpdate: version });
  }
  setTimeout(() => check(), 15_000);
  setInterval(() => check(), DAY);
  return { checkNow: () => check(true) };
}

module.exports = { startUpdates, newer };
