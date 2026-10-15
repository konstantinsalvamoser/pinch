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

Schloss: Stehen in der Claude-Seite Zugänge (Block access-data), wird die Website verschlossen.
Rezepte stehen dann nur verschlüsselt in index.html, Fotos nur als name.jpg.enc; unverschlüsselte
Fotos werden aus dem Ordner entfernt. Öffentlich bleiben je Rezept Titel, Kurzbeschreibung und ein
kleines Foto für die Link-Vorschau (r/<id>/). Der Block access-data selbst (Schlüssel) kommt nie
auf die Website. Ohne Zugänge wird wie bisher offen gebaut und Verschlüsseltes wieder geöffnet.
Gebraucht wird dafür das Paket cryptography; fehlt es, installiert das Skript es mit pip.
"""
import base64, hashlib, hmac, html, json, pathlib, re, shutil, sys, zlib

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
// Mit Schloss ist die Rezeptliste erst nach der Anmeldung da; die Seite ruft pinchPhotos dann selbst noch einmal auf.
window.pinchPhotos=()=>{
 if(!('serviceWorker' in navigator)||!recipes.length)return;
 navigator.serviceWorker.ready.then(reg=>{
  const file=typeof photoFile==='function'?photoFile:p=>p;
  const photos=[...new Set(recipes.flatMap(r=>[r,...r.variants]).map(o=>o.photo).filter(p=>typeof p==='string'&&!p.startsWith('data:')))];
  if(reg.active)reg.active.postMessage({type:'photos',small:photos.map(thumb).map(file),all:[...photos,...photos.map(thumb)].map(file)});
 }).catch(()=>{});
};
if('serviceWorker' in navigator)addEventListener('load',()=>{navigator.serviceWorker.register('sw.js').then(()=>window.pinchPhotos()).catch(()=>{});});
</script>
'''
SW = r'''// Pinch: hält die Website ohne Netz nutzbar. Diese Datei schreibt sync.py; nicht von Hand ändern.
// Bei Änderungen am Verhalten die Nummer in CACHE erhöhen, dann legen die Geräte ihren Speicher neu an.
const CACHE='pinch-2';
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
// Ohne Netz und ohne gespeichertes großes Foto wird die kleine Vorschau gezeigt. Verschlüsselte Fotos (name.jpg.enc) laufen genauso.
async function photo(e,url){
 const hit=await caches.match(e.request);
 const fresh=fetch(e.request).then(res=>keep(e.request,res));
 e.waitUntil(fresh.catch(()=>{}));
 if(hit)return hit;
 try{return await fresh;}
 catch(err){
  const small=await caches.match(url.pathname.replace(/(-s)?\.jpg(\.enc)?$/,'-s.jpg$2'));
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
 else if(own&&/\.jpg(\.enc)?$/.test(url.pathname)&&!/\/r\//.test(url.pathname))e.respondWith(photo(e,url));
 else if(own||/^fonts\.(googleapis|gstatic)\.com$/.test(url.hostname))e.respondWith(asset(req));
});
// Die Seite meldet nach dem Laden ihre Fotos: kleine Vorschauen vorab speichern, Fotos gelöschter Rezepte entfernen.
self.addEventListener('message',e=>{
 const d=e.data;
 if(!d||d.type!=='photos'||!Array.isArray(d.small)||!Array.isArray(d.all))return;
 e.waitUntil((async()=>{
  const c=await caches.open(CACHE),used=new Set(d.all.map(p=>new URL(p,self.registration.scope).href));
  for(const req of await c.keys())if(/\.jpg(\.enc)?$/.test(new URL(req.url).pathname)&&!used.has(req.url))await c.delete(req);
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


def preview_page(recipe, rid, image):
    # Seite für die Link-Vorschau eines Rezepts: Titel, kurze Beschreibung, Foto; leitet Menschen ins Rezept weiter.
    variant = (recipe.get('variants') or [{}])[0]
    facts = [minutes_text(recipe.get('time')), ('%s Portionen' % variant['portions']) if variant.get('portions') else '']
    text = ' · '.join(part for part in [recipe.get('tag') or '', ', '.join(f for f in facts if f)] if part) or 'Rezept auf Pinch'
    target = SITE + '#' + rid
    return PREVIEW.format(name=html.escape(str(recipe.get('name') or 'Rezept')), text=html.escape(text),
                          url=html.escape(SITE + 'r/' + rid + '/'), image=html.escape(SITE + image),
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


def aes_gcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        import subprocess
        for extra in ([], ['--break-system-packages']):
            if subprocess.call([sys.executable, '-m', 'pip', 'install', '--quiet', 'cryptography'] + extra) == 0:
                break
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            raise SystemExit('Für das Schloss wird das Paket cryptography gebraucht (pip install cryptography); nichts geändert.')
    return AESGCM


def seal(key, plain):
    """Verschließt Daten: 12 Bytes Startwert + Geheimtext (AES-256-GCM). Der Startwert hängt vom Inhalt ab,
    damit Unverändertes bei jedem Lauf dieselbe Datei ergibt und git nichts Neues sieht."""
    iv = hmac.new(hmac.new(key, b'pinch-iv', hashlib.sha256).digest(), plain, hashlib.sha256).digest()[:12]
    return iv + aes_gcm()(key).encrypt(iv, plain, None)


def unseal(keys, box):
    """Öffnet mit dem ersten passenden Schlüssel; None, wenn keiner passt."""
    for key in keys:
        try:
            return aes_gcm()(key).decrypt(box[:12], box[12:], None)
        except Exception:
            continue
    return None


def read_access(src):
    """Zugänge aus der Claude-Seite: (Schlüssel [aktuell, frühere …], Zugänge, Runden). Ohne Block: ([], [], 0)."""
    tag = '<script id="access-data" type="application/json">'
    if tag not in src:
        return [], [], 0
    try:
        access = json.loads(block(src, tag)) or {}
        keys = [base64.b64decode(k) for k in [access.get('key')] + list(access.get('old') or []) if k]
        users = []
        for user in access.get('users') or []:
            ident, salt, wrap, uk = (str(user.get(f) or '') for f in ('id', 'salt', 'wrap', 'uk'))
            if not re.fullmatch(r'[0-9a-f]{20}', ident) or len(base64.b64decode(salt)) != 16 or len(base64.b64decode(wrap)) != 60 or len(base64.b64decode(uk)) != 32:
                raise ValueError(ident)
            users.append({'id': ident, 'salt': salt, 'wrap': wrap, 'uk': base64.b64decode(uk)})
        rounds = int(access.get('it') or 0)
    except Exception:
        raise SystemExit('Die Zugänge in der Seite sind nicht lesbar; nichts geändert.')
    if users and (not keys or any(len(k) != 32 for k in keys) or rounds < 100000):
        raise SystemExit('Die Zugänge in der Seite sind unvollständig; nichts geändert.')
    return keys, users, rounds


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

    # Nur vor dem Skript suchen: Im Skript selbst steht der Name des Blocks als Text.
    keys, users, rounds = read_access(src[:src.index('<script id="app-js">')])
    locked = bool(users)
    # Der Block access-data wird nie übernommen: Die Seite entsteht nur aus CSS, Rezepten und Skript.

    # Fotos: Klartext je Datei bestimmen. Reihenfolge: im Rezept gespeichert, neben der heruntergeladenen Datei,
    # unverschlüsselt im Ordner, verschlüsselt im Ordner (mit aktuellem oder früherem Schlüssel).
    missing, written, plain = [], [], {}

    def find(part):
        for path in (source.parent / 'img' / part, repo / part):
            if path.exists():
                return path.read_bytes()
        boxed = repo / (part + '.enc')
        return unseal(keys, boxed.read_bytes()) if boxed.exists() and keys else None

    for recipe in data:
        rid = safe_name(str(recipe.get('id', '')))
        for n, owner in enumerate([recipe] + list(recipe.get('variants', []))):
            photo = owner.get('photo')
            if not photo:
                continue
            if photo.startswith('data:'):
                mime, _, payload = photo[5:].partition(';base64,')
                name = rid + ('' if n == 0 else '-v%d' % n) + '.jpg'
                plain[name], plain[name[:-4] + '-s.jpg'] = as_jpeg(base64.b64decode(payload), mime)
            elif re.fullmatch(r'img/[A-Za-z0-9._-]+\.jpg', photo):
                name = photo[4:]
                for part in (name, name[:-4] + '-s.jpg'):
                    if not locked and (repo / part).exists():
                        plain[part] = None   # offen und schon da: bleibt, wie es ist
                        continue
                    found = find(part)
                    if found is None:
                        missing.append('img/' + part)
                    plain[part] = found
            else:
                raise SystemExit('Unerwarteter Foto-Eintrag bei ' + rid + '; nichts geändert.')
            owner['photo'] = name

    for name in missing:
        print('FEHLT: ' + name)
    if missing:
        raise SystemExit('Fotos fehlen; index.html wurde nicht geändert.')

    # Fotos schreiben: verschlossen als name.jpg.enc, offen als name.jpg; alles andere dieser Art verschwindet.
    removed = []
    for part, content in sorted(plain.items()):
        if locked:
            write_if_new(repo / (part + '.enc'), seal(keys[0], content), written)
        elif content is not None:
            write_if_new(repo / part, content, written)
    keep = {part + '.enc' for part in plain} if locked else set(plain)
    for f in sorted(list(repo.glob('*.jpg')) + list(repo.glob('*.jpg.enc'))):
        if f.name not in keep:
            f.unlink()
            removed.append(f.name)

    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    if locked:
        b64 = lambda raw: base64.b64encode(raw).decode('ascii')
        lock = {'v': 1, 'it': rounds,
                'u': {u['id']: [u['salt'], u['wrap'], b64(seal(u['uk'], keys[0]))] for u in users},
                'd': b64(seal(keys[0], zlib.compress(payload.encode('utf-8'), 9)))}
        inner = ('<script id="recipes-data" type="application/json">[]</script>\n'
                 '<script>\n// Schloss: Rezepte und Fotos sind verschlüsselt; die Seite öffnet sie nach der Anmeldung.\nwindow.PINCH_LOCK='
                 + json.dumps(lock, separators=(',', ':')) + ';\n</script>\n')
    else:
        inner = '<script id="recipes-data" type="application/json">' + payload + '</script>\n'
    page = (HEAD + '<style id="app-css">' + css + '</style>\n</head>\n<body>\n' + inner
            + '<script id="app-js">' + js + '</script>\n' + HISTORY + OFFLINE + '</body>\n</html>\n')
    if locked:
        # Sicherung: Kein Schritt eines Rezepts und kein Schlüssel darf lesbar in der Seite stehen.
        secrets = [base64.b64encode(k).decode('ascii') for k in keys] + [base64.b64encode(u['uk']).decode('ascii') for u in users]
        steps = [step for r in data for v in r.get('variants', []) for step in v.get('steps', []) if len(step) > 30]
        if any(text in page for text in secrets + steps):
            raise SystemExit('Die verschlossene Seite enthielte lesbare Rezepte oder Schlüssel; nichts geändert.')
    index = repo / 'index.html'
    changed = not index.exists() or index.read_text(encoding='utf-8') != page
    if changed:
        index.write_text(page, encoding='utf-8')
    # Vorschauseiten: je Rezept r/<id>/index.html; Ordner gelöschter Rezepte verschwinden wieder.
    # Mit Schloss liegt das kleine Foto für die Vorschau offen daneben (vorschau.jpg); die großen Fotos bleiben verschlossen.
    previews, wanted = 0, set()
    for recipe in data:
        rid = safe_name(str(recipe.get('id', '')))
        if rid != str(recipe.get('id', '')):
            continue   # Adressen mit Sonderzeichen würden im Anker nicht zum Rezept führen
        wanted.add(rid)
        folder = repo / 'r' / rid
        target, shot = folder / 'index.html', folder / 'vorschau.jpg'
        image = recipe.get('photo') or 'icon-512.png'
        folder.mkdir(parents=True, exist_ok=True)
        if locked and recipe.get('photo'):
            image = 'r/' + rid + '/vorschau.jpg'
            small = plain[recipe['photo'][:-4] + '-s.jpg']
            if not (shot.exists() and shot.read_bytes() == small):
                shot.write_bytes(small)
        elif shot.exists():
            shot.unlink()
        text = preview_page(recipe, rid, image)
        if not target.exists() or target.read_text(encoding='utf-8') != text:
            target.write_text(text, encoding='utf-8')
            previews += 1
    if (repo / 'r').is_dir():
        for folder in sorted((repo / 'r').iterdir()):
            if folder.is_dir() and folder.name not in wanted and {f.name for f in folder.iterdir()} <= {'index.html', 'vorschau.jpg'}:
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
    print('Schloss: ' + ('an, %d Zugänge' % len(users) if locked else 'aus'))
    print('index.html: ' + ('aktualisiert' if changed else 'unverändert'))
    print('sw.js: ' + ('aktualisiert' if worker_changed else 'unverändert'))
    print('Vorschauseiten: %d Rezepte, %d neu geschrieben' % (len(wanted), previews))
    for name in written:
        print('Foto geschrieben: ' + name)
    for name in removed:
        print('Foto entfernt: ' + name)


if __name__ == '__main__':
    main()
