// Shell cache so the app opens offline; notifications are shown from the page through this registration.
const CACHE = "txalerts-v1";
const SHELL = ["./", "index.html", "styles.css", "app.js", "content/responses.json", "manifest.webmanifest", "icon.svg"];

self.addEventListener("install", e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));

self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (u.origin !== location.origin) return;           // backend calls are never cached
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const id = e.notification.data && e.notification.data.id;
  e.waitUntil(self.clients.matchAll({type: "window", includeUncontrolled: true}).then(cs => {
    if (cs.length) { cs[0].focus(); cs[0].postMessage({open: id}); }
    else self.clients.openWindow("./index.html#" + encodeURIComponent(id || ""));
  }));
});
