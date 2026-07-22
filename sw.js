const CACHE = "ciclo-btc-v12";
const SHELL = ["./index.html", "./manifest.json", "./icon.svg"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks =>
    Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);

  // data.json e o calendário NUNCA saem do cache: dado velho é pior que dado ausente.
  if (url.pathname.endsWith("data.json") || url.pathname.endsWith("chart.json") || url.hostname.includes("tradingview")) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }

  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
