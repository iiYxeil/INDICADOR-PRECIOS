// Service worker: la app abre al instante y funciona sin conexión con los últimos datos guardados.
const CACHE = 'ciclo-btc-v2';
const SHELL = ['./', 'index.html', 'data.js', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png',
  'https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  // APIs en directo (Binance, bitcoin-data...): siempre a la red
  if (url.origin !== location.origin && !url.href.includes('cdn.jsdelivr.net') && !url.href.includes('fonts.g')) return;
  // página y datos: primero la red (lo más nuevo), si no hay conexión, la copia guardada
  if (url.origin === location.origin && (url.pathname.endsWith('/') || url.pathname.endsWith('.html') || url.pathname.endsWith('data.js'))) {
    e.respondWith(fetch(e.request, {cache: 'no-cache'}).then(r => { const cp = r.clone(); caches.open(CACHE).then(c => c.put(e.request, cp)); return r; })
      .catch(() => caches.match(e.request).then(r => r || caches.match('index.html'))));
    return;
  }
  // resto (librería de gráficas, iconos, fuentes): primero la copia guardada
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).then(res => { const cp = res.clone(); caches.open(CACHE).then(c => c.put(e.request, cp)); return res; })));
});
