/* ViTrack离线界面缓存：只保存源码与图标；API、缩略图、帧和视频永不缓存。 */
const CACHE = "vitrack-shell-v2";
const SHELL = ["/", "/static/style.css", "/static/start.js", "/static/logger.js", "/static/camera.js",
  "/static/app.js", "/static/ipcam.js", "/static/interaction.js", "/static/box_smoother.js",
  "/static/manifest.webmanifest", "/static/icons/icon-192.png", "/static/icons/icon-512.png"];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith("vitrack-shell-") && key !== CACHE)
    .map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin ||
      url.pathname.startsWith("/api/") || url.pathname.startsWith("/outputs/") || url.pathname.startsWith("/ws/")) return;
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(() => caches.match("/")));
  } else if (SHELL.includes(url.pathname)) {
    event.respondWith(fetch(event.request).catch(() => caches.match(url.pathname)));
  }
});
