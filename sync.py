#!/usr/bin/env python3
"""Pinch: baut die GitHub-Pages-Website aus der Claude-Seite (Artifact).

Aufruf im Repository:  python3 sync.py PFAD/ZUR/HERUNTERGELADENEN/index.html

Die heruntergeladene Datei ist die Seite des Artifacts. Daraus entstehen hier index.html, sw.js
(damit die Website ohne Netz nutzbar bleibt), je Rezept eine kleine Seite r/<id>/index.html mit Titel
und Foto für die Vorschau geteilter Links und, für Fotos, die im Rezept selbst gespeichert sind,
die Bilddateien (name.jpg und name-s.jpg).
Fotos, die im Artifact als Datei liegen (img/name.jpg), werden aus dem Ordner neben der
heruntergeladenen Datei übernommen, falls sie im Repository noch fehlen; sonst meldet das
Skript sie als FEHLT und lässt index.html unverändert. Fotos, die kein Rezept mehr verwendet,
werden gelöscht. Das Skript ändert nur Dateien in seinem eigenen Ordner.
"""
import base64, html, json, pathlib, re, shutil, sys

SITE = 'https://konstantinsalvamoser.github.io/pinch/'

HEAD = '''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Pinch</title>
<meta name="description" content="Pinch – Konstantins Rezepte. Suchen, Portionen anpassen, Schritt für Schritt kochen.">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Pinch">
<meta property="og:title" content="Pinch – Konstantins Rezepte">
<meta property="og:description" content="Suchen, Portionen anpassen, Schritt für Schritt kochen.">
<meta property="og:image" content="https://konstantinsalvamoser.github.io/pinch/icon-512.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Pinch">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)">
<link rel="apple-touch-icon" href="icon-180.png">
<link rel="icon" type="image/png" sizes="192x192" href="icon-192.png">
<link rel="manifest" href="manifest.webmanifest">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
<style>img{max-width:100%}[hidden]{display:none!important}</style>
'''
HISTORY = '''<script>
// Nur für die eigenständige Website: Rezepte bekommen eine eigene Adresse (…#udon) und die Zurück-Taste funktioniert.
(()=>{
 const show=navigate;
 navigate=id=>{
  show(id);
  const hash=activeRecipe?'#'+activeRecipe.id:'';
  try{if((location.hash||'')!==hash)history.pushState(null,'',hash||location.pathname+location.search);}catch{}
 };
 addEventListener('popstate',()=>{let id='';try{id=decodeURIComponent(location.hash.slice(1));}catch{}show(id);});
})();
</script>
'''
OFFLINE = '''<script>
// Nur für die eigenständige Website: Unter r/<id>/ liegt je Rezept eine Seite für die Link-Vorschau; Teilen nutzt dann diese Adresse.
window.PINCH_PREVIEW=true;
</script>
<script>
// Nur für die eigenständige Website: sw.js legt die Seite und die Fotos im Gerät ab, damit sie ohne Netz nutzbar bleibt.
if('serviceWorker' in navigator)addEventListener('load',()=>{
 navigator.serviceWorker.register('sw.js').then(()=>navigator.serviceWorker.ready).then(reg=>{
  const photos=[...new Set(recipes.flatMap(r=>[r,...r.variants]).map(o=>o.photo).filter(p=>typeof p==='string'&&!p.startsWith('data:')))];
  if(reg.active)reg.active.postMessage({type:'photos',small:photos.map(thumb),all:[...photos,...photos.map(thumb)]});
 }).catch(()=>{});
});
</script>
'''
SW = r'''// Pinch: hält die Website ohne Netz nutzbar. Diese Datei schreibt sync.py; nicht von Hand ändern.
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
'''
PREVIEW = '''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} – Pinch</title>
<meta name="description" content="{text}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Pinch">
<meta property="og:title" content="{name}">
<meta property="og:description" content="{text}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{image}">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="{target}">
<noscript><meta http-equiv="refresh" content="0;url={target}"></noscript>
<style>html,body{{height:100%}}body{{margin:0;display:grid;place-items:center;background:#0000ff;color:#ffffff;font:600 18px -apple-system,BlinkMacSystemFont,Helvetica,Arial,sans-serif}}a{{color:inherit}}</style>
</head>
<body>
<a href="{target}">{name} auf Pinch öffnen</a>
<script>
// Menschen landen sofort im Rezept; Vorschau-Dienste (WhatsApp, iMessage, Slack …) bleiben hier und lesen Titel und Foto.
if(!/bot|crawl|spider|facebookexternalhit|whatsapp|telegram|slack|discord|preview|embed/i.test(navigator.userAgent))location.replace({target_js});
</script>
</body>
</html>
'''


def minutes_text(minutes):
    if not minutes:
        return ''
    hours, rest = divmod(int(minutes), 60)
    return ('%d Std.' % hours + (' %d Min.' % rest if rest else '')) if hours else '%d Min.' % rest


def preview_page(recipe, rid):
    # Seite für die Link-Vorschau eines Rezepts: Titel, kurze Beschreibung, Foto; leitet Menschen ins Rezept weiter.
    variant = (recipe.get('variants') or [{}])[0]
    facts = [minutes_text(recipe.get('time')), ('%s Portionen' % variant['portions']) if variant.get('portions') else '']
    text = ' · '.join(part for part in [recipe.get('tag') or '', ', '.join(f for f in facts if f)] if part) or 'Rezept auf Pinch'
    target = SITE + '#' + rid
    return PREVIEW.format(name=html.escape(str(recipe.get('name') or 'Rezept')), text=html.escape(text),
                          url=html.escape(SITE + 'r/' + rid + '/'), image=html.escape(SITE + (recipe.get('photo') or 'icon-512.png')),
                          target=html.escape(target), target_js=json.dumps(target).replace('<', '\\u003c'))


MANIFEST = {"name": "Pinch", "short_name": "Pinch", "start_url": "./", "scope": "./", "display": "standalone",
            "background_color": "#0000ff", "theme_color": "#0000ff",
            "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}]}
THUMB = 520   # längste Seite der kleinen Vorschau (name-s.jpg)


def block(src, open_tag):
    """Inhalt eines <style>/<script>-Blocks; beim Skript zählt das letzte schließende Tag."""
    start = src.index(open_tag) + len(open_tag)
    close = '</style>' if open_tag.startswith('<style') else '</script>'
    end = src.rindex(close) if 'app-js' in open_tag else src.index(close, start)
    return src[start:end]


def safe_name(text):
    return re.sub(r'[^a-z0-9-]+', '-', text.lower()).strip('-') or 'rezept'


def as_jpeg(raw, mime):
    """Liefert (Foto, kleine Vorschau) als JPEG-Bytes. Ohne Pillow ist beides die Originaldatei."""
    try:
        import io
        from PIL import Image
    except ImportError:
        if mime != 'image/jpeg':
            raise SystemExit('Für dieses Foto (' + mime + ') wird Pillow gebraucht: pip install pillow')
        return raw, raw
    image = Image.open(io.BytesIO(raw))
    if image.mode != 'RGB':
        flat = Image.new('RGB', image.size, '#ffffff')
        flat.paste(image.convert('RGBA'), mask=image.convert('RGBA').split()[3])
        image = flat
    full = raw
    if mime != 'image/jpeg':
        out = io.BytesIO(); image.save(out, 'JPEG', quality=85); full = out.getvalue()
    image.thumbnail((THUMB, THUMB))
    out = io.BytesIO(); image.save(out, 'JPEG', quality=80)
    return full, out.getvalue()


def write_if_new(path, content, written):
    if not (path.exists() and path.read_bytes() == content):
        path.write_bytes(content)
        written.append(path.name)


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    source = pathlib.Path(sys.argv[1]).resolve()
    repo = pathlib.Path(__file__).resolve().parent
    src = source.read_text(encoding='utf-8')
    try:
        css = block(src, '<style id="app-css">')
        data = json.loads(block(src, '<script id="recipes-data" type="application/json">'))
        js = block(src, '<script id="app-js">')
    except ValueError:
        raise SystemExit('Die Datei sieht nicht nach der Pinch-Seite aus; nichts geändert.')
    if not isinstance(data, list) or not data or 'function navigate(' not in js:
        raise SystemExit('Die Datei sieht nicht nach der Pinch-Seite aus; nichts geändert.')

    missing, written, used = [], [], set()
    for recipe in data:
        rid = safe_name(str(recipe.get('id', '')))
        for n, owner in enumerate([recipe] + list(recipe.get('variants', []))):
            photo = owner.get('photo')
            if not photo:
                continue
            if photo.startswith('data:'):
                mime, _, payload = photo[5:].partition(';base64,')
                name = rid + ('' if n == 0 else '-v%d' % n) + '.jpg'
                full, small = as_jpeg(base64.b64decode(payload), mime)
                write_if_new(repo / name, full, written)
                write_if_new(repo / (name[:-4] + '-s.jpg'), small, written)
                owner['photo'] = name
            elif re.fullmatch(r'img/[A-Za-z0-9._-]+\.jpg', photo):
                name = photo[4:]
                for part in (name, name[:-4] + '-s.jpg'):
                    if not (repo / part).exists():
                        beside = source.parent / 'img' / part
                        if beside.exists():
                            shutil.copyfile(beside, repo / part)
                            written.append(part)
                        else:
                            missing.append('img/' + part)
                owner['photo'] = name
            else:
                raise SystemExit('Unerwarteter Foto-Eintrag bei ' + rid + '; nichts geändert.')

    for name in missing:
        print('FEHLT: ' + name)
    if missing:
        raise SystemExit('Fotos fehlen; index.html wurde nicht geändert.')

    # Fotos gelöschter Rezepte entfernen: jede .jpg im Ordner, die kein Rezept mehr verwendet.
    for recipe in data:
        for owner in [recipe] + list(recipe.get('variants', [])):
            if owner.get('photo'):
                used.update((owner['photo'], owner['photo'][:-4] + '-s.jpg'))
    removed = [f.name for f in sorted(repo.glob('*.jpg')) if f.name not in used]
    for name in removed:
        (repo / name).unlink()

    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    page = (HEAD + '<style id="app-css">' + css + '</style>\n</head>\n<body>\n'
            + '<script id="recipes-data" type="application/json">' + payload + '</script>\n'
            + '<script id="app-js">' + js + '</script>\n' + HISTORY + OFFLINE + '</body>\n</html>\n')
    index = repo / 'index.html'
    changed = not index.exists() or index.read_text(encoding='utf-8') != page
    if changed:
        index.write_text(page, encoding='utf-8')
    # Vorschauseiten: je Rezept r/<id>/index.html; Ordner gelöschter Rezepte verschwinden wieder.
    previews, wanted = 0, set()
    for recipe in data:
        rid = safe_name(str(recipe.get('id', '')))
        if rid != str(recipe.get('id', '')):
            continue   # Adressen mit Sonderzeichen würden im Anker nicht zum Rezept führen
        wanted.add(rid)
        target = repo / 'r' / rid / 'index.html'
        text = preview_page(recipe, rid)
        if not target.exists() or target.read_text(encoding='utf-8') != text:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
            previews += 1
    if (repo / 'r').is_dir():
        for folder in sorted((repo / 'r').iterdir()):
            if folder.is_dir() and folder.name not in wanted and sorted(f.name for f in folder.iterdir()) in (['index.html'], []):
                shutil.rmtree(folder)
    worker = repo / 'sw.js'
    worker_changed = not worker.exists() or worker.read_text(encoding='utf-8') != SW
    if worker_changed:
        worker.write_text(SW, encoding='utf-8')
    manifest = repo / 'manifest.webmanifest'
    manifest_text = json.dumps(MANIFEST, indent=1)
    if not manifest.exists() or manifest.read_text(encoding='utf-8') != manifest_text:
        manifest.write_text(manifest_text, encoding='utf-8')

    print('Rezepte: %d' % len(data))
    print('index.html: ' + ('aktualisiert' if changed else 'unverändert'))
    print('sw.js: ' + ('aktualisiert' if worker_changed else 'unverändert'))
    print('Vorschauseiten: %d Rezepte, %d neu geschrieben' % (len(wanted), previews))
    for name in written:
        print('Foto geschrieben: ' + name)
    for name in removed:
        print('Foto entfernt: ' + name)


if __name__ == '__main__':
    main()
