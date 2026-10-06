// Pinch: hält die Website ohne Netz nutzbar. Diese Datei schreibt sync.py; nicht von Hand ändern.
// Bei Änderungen am Verhalten die Nummer in CACHE erhöhen, dann legen die Geräte ihren Speicher neu an.
const CACHE='pinch-1';
const SHELL=['./','manifest.webmanifest','icon-180.png','icon-192.png','icon-512.png'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting()));});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));});
const keep=async(req,res)=>{if(res&&((res.ok&&!res.redirected)||res.type==='opaque')){const c=await caches.open(CACHE);await c.put(req,res.clone());}return res;};

// Die Seite selbst: zuerst das Netz, damit neue Rezepte ankommen; ohne Netz oder nach 4 Sekunden der gespeicherte Stand.
async function page(e){
 const c=await caches.open(CACHE),cached=await c.match('./');
 const fresh=fetch(e.request).then(res=>{if(res.ok&&!res.redirected)c.put('./',res.clone());return res;});
 e.waitUntil(fresh.catch(()=>{}));
 if(!cached)return fresh;
 return Promise.race([fresh.catch(()=>cached),new Promise(done=>setTimeout(()=>done(cached),4000))]);
}
// Fotos: sofort aus dem Speicher, im Hintergrund auffrischen (ein ersetztes Foto kommt so beim nächsten Öffnen an).
// Ohne Netz und ohne gespeichertes großes Foto wird die kleine Vorschau gezeigt.
async function photo(e,url){
 const hit=await caches.match(e.request);
 const fresh=fetch(e.request).then(res=>keep(e.request,res));
 e.waitUntil(fresh.catch(()=>{}));
 if(hit)return hit;
 try{return await fresh;}
 catch(err){
  const small=await caches.match(url.pathname.replace(/(-s)?\.jpg$/,'-s.jpg'));
  if(small)return small;
  throw err;
 }
}
// Icons, Manifest und die Schrift: aus dem Speicher, sonst aus dem Netz und merken.
async function asset(req){return (await caches.match(req))||keep(req,await fetch(req));}
self.addEventListener('fetch',e=>{
 const req=e.request;
 if(req.method!=='GET')return;
 const url=new URL(req.url),own=url.origin===location.origin;
 if(own&&req.mode==='navigate'){
  // Nur die Startseite wird gespeichert. Vorschauseiten (r/…) kommen aus dem Netz; ohne Netz öffnet sich stattdessen die Startseite.
  const start=new URL('./',self.registration.scope).pathname;
  if(url.pathname===start||url.pathname===start+'index.html')e.respondWith(page(e));
  else e.respondWith(fetch(req).catch(()=>caches.match('./').then(hit=>hit||Response.error())));
 }
 else if(own&&/\.jpg$/.test(url.pathname))e.respondWith(photo(e,url));
 else if(own||/^fonts\.(googleapis|gstatic)\.com$/.test(url.hostname))e.respondWith(asset(req));
});
// Die Seite meldet nach dem Laden ihre Fotos: kleine Vorschauen vorab speichern, Fotos gelöschter Rezepte entfernen.
self.addEventListener('message',e=>{
 const d=e.data;
 if(!d||d.type!=='photos'||!Array.isArray(d.small)||!Array.isArray(d.all))return;
 e.waitUntil((async()=>{
  const c=await caches.open(CACHE),used=new Set(d.all.map(p=>new URL(p,self.registration.scope).href));
  for(const req of await c.keys())if(/\.jpg$/.test(new URL(req.url).pathname)&&!used.has(req.url))await c.delete(req);
  for(const p of d.small){try{if(!(await c.match(p))){const res=await fetch(p);if(res.ok)await c.put(p,res);}}catch{}}
 })());
});
