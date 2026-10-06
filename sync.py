#!/usr/bin/env python3
"""Pinch: baut die GitHub-Pages-Website aus der Claude-Seite (Artifact).

Aufruf im Repository:  python3 sync.py PFAD/ZUR/HERUNTERGELADENEN/index.html

Die heruntergeladene Datei ist die Seite des Artifacts. Daraus entstehen hier index.html und,
für Fotos, die im Rezept selbst gespeichert sind, die Bilddateien (name.jpg und name-s.jpg).
Fotos, die im Artifact als Datei liegen (img/name.jpg), werden aus dem Ordner neben der
heruntergeladenen Datei übernommen, falls sie im Repository noch fehlen; sonst meldet das
Skript sie als FEHLT und lässt index.html unverändert. Fotos, die kein Rezept mehr verwendet,
werden gelöscht. Das Skript ändert nur Dateien in seinem eigenen Ordner.
"""
import base64, json, pathlib, re, shutil, sys

HEAD = '''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Pinch</title>
<meta name="description" content="Pinch – Konstantins Rezepte. Suchen, Portionen anpassen, Schritt für Schritt kochen.">
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
MANIFEST = {"name": "Pinch", "short_name": "Pinch", "start_url": "./", "scope": "./", "display": "standalone",
            "background_color": "#ffffff", "theme_color": "#0000ff",
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
            + '<script id="app-js">' + js + '</script>\n' + HISTORY + '</body>\n</html>\n')
    index = repo / 'index.html'
    changed = not index.exists() or index.read_text(encoding='utf-8') != page
    if changed:
        index.write_text(page, encoding='utf-8')
    manifest = repo / 'manifest.webmanifest'
    if not manifest.exists():
        manifest.write_text(json.dumps(MANIFEST, indent=1), encoding='utf-8')

    print('Rezepte: %d' % len(data))
    print('index.html: ' + ('aktualisiert' if changed else 'unverändert'))
    for name in written:
        print('Foto geschrieben: ' + name)
    for name in removed:
        print('Foto entfernt: ' + name)


if __name__ == '__main__':
    main()
