/* Guarda Mis Finanzas para abrirla sin internet. Solo afecta a finanzas.html;
   tus datos no pasan por aqui: siguen en tu movil. */
const CACHE = 'finanzas-v1';
const PAGINA = new URL('finanzas.html', self.location).href;

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.add(PAGINA)));
});
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

/* Con internet carga la ultima version; sin internet, la guardada */
async function pagina(req) {
  const c = await caches.open(CACHE);
  try {
    const r = await Promise.race([fetch(req), new Promise((_, no) => setTimeout(no, 3500))]);
    if (r.ok) { c.put(PAGINA, r.clone()); return r; }
    throw new Error('sin respuesta');
  } catch (e) {
    return (await c.match(PAGINA)) || fetch(req);
  }
}
/* Tipografias: una vez descargadas, siempre desde el movil */
async function fuente(req) {
  const c = await caches.open(CACHE), g = await c.match(req);
  if (g) return g;
  const r = await fetch(req);
  if (r.ok || r.type === 'opaque') c.put(req, r.clone());
  return r;
}
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const u = new URL(e.request.url);
  if (e.request.mode === 'navigate' && u.href.split(/[?#]/)[0] === PAGINA) e.respondWith(pagina(e.request));
  else if (u.hostname === 'cdn.jsdelivr.net') e.respondWith(fuente(e.request));
});
