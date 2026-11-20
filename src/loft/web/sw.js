// Keeps Loft's own files on this device so the app opens with no connection, to read downloaded
// books. Browsers only allow this over https (or on this computer). Never touches /api: books,
// pages and the library always come from the server, or from downloads (offline.js).
const CACHE = "loft-shell-v3";
const SHELL = ["./", "style.css", "fonts/fonts.css", "fonts/literata.woff2", "fonts/literata-italic.woff2",
  "fonts/instrument-sans.woff2", "vendor/page-flip.browser.js", "manifest.webmanifest", "icons/icon.svg",
  ...["add", "admin", "api", "arrange", "book", "check", "cover", "downloads", "edit", "fill", "filled", "flow", "titles", "grid", "home",
    "login", "main", "notifications", "offline", "requests", "discussion", "prefs", "reader", "settings", "shelfmenu", "stacks", "trail", "updates", "zoom"].map((n) => `js/${n}.js`)];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // The server first, so an update shows at once; this device's copy when it can't be reached.
  e.respondWith(fetch(e.request).then((res) => {
    if (res.ok) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy));
    }
    return res;
  }).catch(() => caches.match(e.request).then((hit) => hit || caches.match("./"))));
});
