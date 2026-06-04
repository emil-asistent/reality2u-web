#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reality2u — generátor inzerátů.

Stáhne aktuální aktivní inzeráty z veřejného myBRIK portálu inzeraty.reality2u.cz
(stejný backend jako oficiální API) a NAFORMÁTUJE je do STÁVAJÍCÍCH šablon webu
reality2u.djai.cz — vzhled zůstává 1:1, mění se jen data.

  - nemovitosti.html        ... přegeneruje jen dynamické regiony (karty, počty,
                                filtr měst), zbytek stránky je byte-identický.
  - nemovitost-<id>.html    ... jedna detailová stránka na každý aktivní inzerát,
                                podle vzoru původní ručně dělané detailové šablony.

Statický shell (index, sluzby, o-nas, kontakt, kalkulacka, odhad, assets) se
beze změny kopíruje z TEMPLATE_DIR do OUT_DIR.

Spuštění:
    python3 tools/generate.py                # build do reality2u.djai.cz/
    python3 tools/generate.py --out DIR      # build jinam
    python3 tools/generate.py --offline      # použij /tmp cache (vývoj)

Cron (auto-refresh) volá tenhle skript a pak deploy.
"""
import argparse, html, json, os, re, shutil, sys, time, unicodedata, urllib.request, urllib.error

BASE      = "https://inzeraty.reality2u.cz"
LIST_URL  = BASE + "/?ajax=1&page={page}"
DET_URL   = BASE + "/?inzerat_id={id}"
UA        = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 reality2u-generator"

HERE        = os.path.dirname(os.path.abspath(__file__))
PROJECT     = os.path.dirname(HERE)
TEMPLATE_DIR = os.path.join(PROJECT, "source")                 # kanonické šablony + shell
OUT_DEFAULT  = os.path.join(PROJECT, "reality2u.djai.cz")      # nasazovaná kopie
CACHE_DIR    = "/tmp/reality2u_cache"

PIN = ('<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
       'stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>'
       '<circle cx="12" cy="10" r="3"/></svg>')
PIN14 = PIN.replace('width="12" height="12"', 'width="14" height="14"').replace(
        '9 13s-9-6-9-13', '9 13S3 17 3 10').replace('style="', 'style="') \
        if False else ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" style="vertical-align:-2px;flex-shrink:0">'
        '<path d="M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>')

GRADIENTS = [
    "linear-gradient(135deg,#1a3a5c,#2d6a8f)", "linear-gradient(135deg,#1e3d2f,#3a7a55)",
    "linear-gradient(135deg,#3d2a1e,#8a5a35)", "linear-gradient(135deg,#2a1e3d,#5a357a)",
    "linear-gradient(135deg,#1e2d3d,#3a5a7a)", "linear-gradient(135deg,#3d1e2a,#8a355a)",
    "linear-gradient(135deg,#1a2e4a,#2a5a8a)", "linear-gradient(135deg,#2e3d1a,#5a7a2a)",
    "linear-gradient(135deg,#3d3a1a,#8a7a35)", "linear-gradient(135deg,#1a3d3a,#2a7a6a)",
]

# ───────────────────────── stavy + čisté URL ─────────────────────────
STATUS_FILE  = os.path.join(PROJECT, "status.json")          # ruční přepisy stavů
ARCHIVE_FILE = os.path.join(PROJECT, "_known_offers.json")   # archiv pro auto-detekci prodaných
SOLD_KEEP    = 6                                              # kolik posledních prodaných ještě zobrazit

# stav -> (popisek, css třída badge)
STATUS_META = {
    "volne":       ("Volné",       "pb-volne"),
    "rezervovano": ("Rezervováno", "pb-rezervovano"),
    "prodano":     ("Prodáno",     "pb-prodano"),
}
# stav -> (barva pozadí, barva textu) pro detail
STATUS_COLOR = {
    "volne":       ("rgba(16,185,129,.95)", "#fff"),
    "rezervovano": ("rgba(245,166,35,.97)", "#fff"),
    "prodano":     ("rgba(74,85,104,.96)",  "#fff"),
}

def slugify(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return (re.sub(r"-+", "-", s)[:60].strip("-")) or "nemovitost"

def detail_slug(o):
    return f"nemovitost-{slugify(o['title'])}-{o['id']}"

def _clean_links(s, slug_by_id):
    # detail: existující -> slug; neexistující (staré/odebrané) -> výpis (žádné 404)
    s = re.sub(r"nemovitost-(\d+)\.html",
               lambda m: slug_by_id.get(int(m.group(1)), "nemovitosti"), s)
    s = re.sub(r"(?:\./)?index\.html", "./", s)
    s = re.sub(r"\b(nemovitosti|sluzby|o-nas|kontakt|kalkulacka|odhad)\.html", r"\1", s)
    return s

def cleanify(htmls, slug_by_id):
    """čisté URL (bez .html) ve všech odkazech; <script> bloky nechá být"""
    parts = re.split(r"(<script[\s\S]*?</script>)", htmls)
    for i in range(0, len(parts), 2):
        parts[i] = _clean_links(parts[i], slug_by_id)
    return "".join(parts)

def load_status():
    try:
        d = json.load(open(STATUS_FILE, encoding="utf-8"))
    except Exception:
        d = {}
    out = {}
    for k in ("rezervovano", "prodano", "volne", "skryto"):
        out[k] = set(int(x) for x in d.get(k, []) if str(x).isdigit())
    return out

# ───────────────────────── HTTP ─────────────────────────
def fetch(url, tries=3):
    last = None
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                        "X-Requested-With": "XMLHttpRequest"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:                       # noqa
            last = e; time.sleep(1.5 * (t + 1))
    raise SystemExit(f"FETCH FAIL {url}: {last}")

def fetch_detail(oid, offline=False):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cp = os.path.join(CACHE_DIR, f"{oid}.html")
    if offline and os.path.exists(cp):
        return open(cp, encoding="utf-8", errors="replace").read()
    htmls = fetch(DET_URL.format(id=oid))
    try:
        open(cp, "w", encoding="utf-8").write(htmls)
    except Exception:
        pass
    return htmls

# ───────────────────────── parse helpers ─────────────────────────
def clean(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or ""))).strip()

def esc(s):
    return html.escape(s or "", quote=False)

def cap_first(s):
    """velké první písmeno (zbytek nech být) — titulky z feedu bývají malými"""
    s = (s or "").strip()
    return s[:1].upper() + s[1:] if s else s

def derive_kind(title):
    """vrátí (transakce, typ_label) z titulku"""
    t = title.lower()
    trans = "Prodej" if t.startswith("prodej") else ("Pronájem" if t.startswith("pron") else
            ("Pronájem" if "měsíc" in t or "měsíc" in t else "Prodej"))
    if re.search(r"\bbyt", t):                       label = "Byt"
    elif re.search(r"ordinac|dílk?n|dílny|nebytov|kancel|obchodn|sklad|komerč", t): label = "Komerční"
    elif re.search(r"ateli[eé]r", t):                label = "Ateliér"
    elif re.search(r"pozem|parcel", t):              label = "Pozemek"
    elif re.search(r"chalup", t):                    label = "Chalupa"
    elif re.search(r"chat[ay]", t):                  label = "Chata"
    elif re.search(r"jednotk|apartm[aá]n|garsoni", t): label = "Apartmán"
    elif re.search(r"srub", t):                      label = "Rodinný dům"
    elif re.search(r"rodinn|\bdom[ua]\b|\brd\b|novostavb\w* (rodinn|patrov|dom)", t): label = "Rodinný dům"
    elif re.search(r"dům|domu", t):                  label = "Rodinný dům"
    else:                                            label = "Nemovitost"
    return trans, label

def disp_of(full):
    m = re.search(r"\b(\d\s*[,.]?5?\s*\+\s*kk|\d\s*\+\s*\d)\b", full, re.I)
    if m: return re.sub(r"\s+", "", m.group(1)).lower()
    if re.search(r"garsoni[eé]r", full, re.I): return "garsoniéra"
    if re.search(r"ateli[eé]r", full, re.I):   return "ateliér"
    return None

def _num(s):
    """'1 522' / '1.522' -> 1522 ; '19,35' -> 19"""
    s = re.sub(r"[,\.].*$", "", s)       # uřízni desetinnou část
    return int(re.sub(r"\D", "", s) or 0)

def plocha_of(full, title):
    # 1) číslo z titulku (nejspolehlivější) — "...117m2", "...117 m²"
    mt = re.search(r"(\d{2,4})\s*m\s*[²2]\b", title)
    if mt:
        return mt.group(1) + " m²"
    # 2) "Dispozici 3+1 o celkové výměře 106 m2" / "Dispozice 4+kk, cca 70 m2"
    m = re.search(r"dispozic\w*[\s,:]*\d(?:[,\.]\d)?\s*\+\s*\w{1,3}[\s,]*(?:o\s*)?(?:celkov\w+\s*)?"
                  r"(?:v[yý]m[eě][rř]e\s*|plo(?:ch|š)\w*\s*)?(?:cca\s*)?(\d{2,4})\s*m\s*[²2]", full, re.I)
    if m and 15 <= _num(m.group(1)) <= 1500:
        return m.group(1) + " m²"
    # 3) silná vazba na stavbu: užitná/obytná/podlahová/zastavěná plocha
    m = re.search(r"(?:u[žz]itn\w+|obytn\w+|podlahov\w+|zastav\w+)\s*plo(?:ch|š)\w*\s*"
                  r"(?:bytu\s*|domu\s*|jednotky\s*|[čc]in[íi]\s*)?(?:cca\s*)?(\d{2,4})\s*m\s*[²2]", full, re.I)
    if m and 15 <= _num(m.group(1)) <= 1500:
        return m.group(1) + " m²"
    # 4) "celková plocha/ploše N m2" — ale NE pokud jde o pozemek/zahradu/parcelu
    for m in re.finditer(r"celkov\w+\s*plo(?:ch|š)\w*\s*(?:cca\s*)?(\d{2,4})\s*m\s*[²2]", full, re.I):
        before = full[max(0, m.start() - 22):m.start()].lower()
        if any(w in before for w in ("pozem", "parcel", "zahrad")):
            continue
        if 15 <= _num(m.group(1)) <= 1500:
            return m.group(1) + " m²"
    return None

def pozemek_of(full):
    pats = (
        # "Pozemek o (celkové) rozloze/výměře/ploše 871 m2"
        r"(?:pozem\w+|parcel\w+)\s*(?:o\s*)?(?:celkov\w+\s*)?"
        r"(?:rozloze|v[yý]m[eě][rř]e|velikosti|plo(?:ch|š)\w*)\s*(?:cca\s*)?(\d[\d \.]{1,7}\d|\d{3,5})\s*m\s*[²2]",
        # "celkové ploše pozemku 1 522 m2" (opačný slovosled)
        r"plo(?:ch|š)\w*\s*pozemku\s*(?:cca\s*)?(\d[\d \.]{1,7}\d|\d{3,5})\s*m\s*[²2]",
    )
    for pat in pats:
        m = re.search(pat, full, re.I)
        if m:
            n = _num(m.group(1))
            if 80 <= n <= 100000:
                return f"{n:,}".replace(",", " ") + " m²"
    return None

def avail_of(full):
    m = re.search(r"[Vv]oln[ýáéa][^.]{0,25}?(\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4})", full)
    if m: return "Volné od " + re.sub(r"\s+", "", m.group(1))
    if re.search(r"\bihned\b|k nast[eě]hov|okam[zž]it", full, re.I): return "Ihned"
    return None

def initials(name):
    parts = [p for p in re.split(r"\s+", name) if p]
    return ("".join(p[0] for p in parts[:2]) or "R2").upper()

# ───────────────────────── offer model ─────────────────────────
def parse_offer(oid, det_html, short_loc):
    h = det_html
    m = re.search(r"text__left\">\s*<h1>(.*?)</h1>\s*<span>(.*?)</span>", h, re.S)
    title = cap_first(clean(m.group(1))) if m else f"Inzerát {oid}"
    address = clean(m.group(2)) if m else ""
    mp = re.search(r"text__right\">\s*<h1>(.*?)</h1>", h, re.S)
    price = clean(mp.group(1)) if mp else ""
    md = re.search(r"<h2>\s*POPIS\s*</h2>\s*<p>(.*?)</p>", h, re.S)
    popis_html = md.group(1) if md else ""
    # popis -> odstavce (děl na <br><br>/dvojitý zlom)
    chunks = re.split(r"(?:<br\s*/?>\s*){2,}", popis_html)
    paras = [clean(c) for c in chunks if clean(c)]
    if not paras:
        paras = [clean(popis_html)] if clean(popis_html) else []
    popis_flat = " ".join(paras)
    imgs = re.findall(r'data-src="([^"]+1182x591[^"]+)"', h)
    # fallback: vezmi cokoliv z cache/offers daného id
    if not imgs:
        imgs = list(dict.fromkeys(re.findall(rf'(https://[^"\'() ]+/cache/offers/{oid}/[^"\'() ]+)', h)))
    mlat = re.search(r"lat\s*=\s*([0-9.]+)", h); mlng = re.search(r"lng\s*=\s*([0-9.]+)", h)
    gps = (mlat.group(1) if mlat else None, mlng.group(1) if mlng else None)
    ma = re.search(r"makler__right\">\s*<h3>(.*?)</h3>\s*<a[^>]*phone[^>]*>(.*?)</a>\s*<a[^>]*mail[^>]*>(.*?)</a>", h, re.S)
    if ma:
        agent = (clean(ma.group(1)), clean(ma.group(2)), clean(ma.group(3)))
    else:
        agent = ("Tým reality2u", "722 967 163", "asistentka@reality2u.cz")

    trans, label = derive_kind(title)
    if "měsíc" in price.lower(): trans = "Pronájem"
    full = title + " " + popis_flat
    disp = disp_of(full)
    if disp == "ateliér" and label == "Ateliér":   # neopakuj typ jako dispozici
        disp = None
    if label == "Nemovitost" and disp and re.match(r"\d", disp):  # X+kk/X+1 bez jiného typu = byt
        label = "Byt"
    plocha = plocha_of(full, title)
    pozemek = pozemek_of(full)
    if label == "Pozemek" and not pozemek:
        pozemek = plocha; plocha = None
    avail = avail_of(full)
    short = short_loc or (address.split(",")[0].strip() if address else "ČR")

    return {
        "id": oid, "title": title, "address": address, "price": price,
        "trans": trans, "label": label, "short": short,
        "disp": disp, "plocha": plocha, "pozemek": pozemek, "avail": avail,
        "paras": paras, "imgs": imgs, "gps": gps, "agent": agent,
        "status": "volne",
    }

# ───────────────────────── list (ajax) ─────────────────────────
def collect_list(offline=False):
    """vrátí seznam (id, short_location, list_price) v pořadí jak je portál vrací"""
    out, seen = [], set()
    for page in range(1, 12):
        if offline:
            cp = os.path.join(CACHE_DIR, f"pg{page}.json")
            if not os.path.exists(cp):
                if page == 1: raise SystemExit("offline: chybí cache stránek")
                break
            data = json.load(open(cp, encoding="utf-8"))
        else:
            raw = fetch(LIST_URL.format(page=page))
            try:
                data = json.loads(raw)
            except Exception:
                break
            os.makedirs(CACHE_DIR, exist_ok=True)
            json.dump(data, open(os.path.join(CACHE_DIR, f"pg{page}.json"), "w"), ensure_ascii=False)
        content = data.get("content", "")
        cards = re.findall(
            r'inzerat_id=(\d+)".*?<h2>(.*?)</h2>\s*<span>(.*?)</span>.*?'
            r'description__right">\s*<h2>\s*(.*?)\s*</h2>', content, re.S)
        if not cards:
            break
        new = 0
        for cid, _t, loc, _p in cards:
            cid = int(cid)
            if cid in seen: continue
            seen.add(cid); new += 1
            out.append((cid, clean(loc)))
        if new == 0:
            break
    return out

# ───────────────────────── render: karta (grid) ─────────────────────────
def render_card(o, idx):
    grad = GRADIENTS[idx % len(GRADIENTS)]
    badge_cls = "pb-new" if o["trans"] == "Prodej" else "pb-rent"
    status = o.get("status", "volne")
    slabel, scls = STATUS_META.get(status, STATUS_META["volne"])
    img0 = o["imgs"][0] if o["imgs"] else ""
    snippet = (o["paras"][0] if o["paras"] else o["title"])
    snippet = snippet[:118].rstrip() + ("…" if len(snippet) > 118 else "")
    hypo = ('<a href="kalkulacka.html" class="btn-prop-hypo" onclick="event.stopPropagation()">Hypotéka</a>'
            if o["trans"] == "Prodej" and status != "prodano" else "")
    bg = f"url('{img0}') center/cover no-repeat,{grad}" if img0 else grad
    band = "" if status == "volne" else f'<div class="prop-status-band ps-{status}">{slabel.upper()}</div>'
    img_cls = "prop-img" + (" is-dim" if status == "prodano" else "")
    return f'''      <div class="prop-card reveal" data-status="{status}" onclick="window.location='./nemovitost-{o['id']}.html'">
        <div class="{img_cls}" style="background:{bg}">
          <div class="prop-badges"><span class="pbadge {badge_cls}">{o['trans']}</span><span class="pbadge {scls}">{slabel}</span></div>
          <button class="prop-fav" onclick="event.stopPropagation()">&#9825;</button>
          <div class="prop-price-tag">{esc(o['price'])}</div>{band}
        </div>
        <div class="prop-body">
          <div class="prop-type">{esc(o['label'])} &middot; {o['trans']}</div>
          <div class="prop-name">{esc(o['title'])}</div>
          <div class="prop-loc">{PIN} {esc(o['short'])}</div>
          <div class="prop-desc">{esc(snippet)}</div>
        </div>
        <div class="prop-actions">
          <a href="./nemovitost-{o['id']}.html" class="btn-prop-main" onclick="event.stopPropagation()">Zobrazit detail</a>
          {hypo}
        </div>
      </div>'''

# ───────────────────────── render: featured (homepage) ─────────────────────────
def render_featured(offers, n=3):
    """3 aktuální inzeráty do homepage sekce „Vybrané nemovitosti“ (vzhled 1:1)."""
    vis = [o for o in offers if o.get("status", "volne") == "volne"] or offers
    cards = []
    for i, o in enumerate(vis[:n]):
        grad = GRADIENTS[i % len(GRADIENTS)]
        img0 = o["imgs"][0] if o["imgs"] else ""
        bg = f"url('{img0}') center/cover no-repeat,{grad}" if img0 else grad
        badge_cls = "pb-new" if o["trans"] == "Prodej" else "pb-rent"
        snippet = (o["paras"][0] if o["paras"] else o["title"])
        snippet = snippet[:118].rstrip() + ("…" if len(snippet) > 118 else "")
        hypo = ('<a href="./kalkulacka.html" class="btn-prop-hypo" onclick="event.stopPropagation()">Hypotéka</a>'
                if o["trans"] == "Prodej" else "")
        cards.append(f'''      <div class="prop-card reveal" onclick="window.location='./nemovitost-{o['id']}.html'">
        <div class="prop-img" style="background:{bg}">
          <div class="prop-badges"><span class="pbadge {badge_cls}">{o['trans']}</span></div>
          <button class="prop-fav" onclick="event.stopPropagation()">&#9825;</button>
          <div class="prop-price-tag">{esc(o['price'])}</div>
        </div>
        <div class="prop-body">
          <div class="prop-type">{esc(o['label'])} &middot; {o['trans']}</div>
          <div class="prop-name">{esc(o['title'])}</div>
          <div class="prop-loc">{PIN} {esc(o['short'])}</div>
          <div class="prop-meta" style="font-size:.78rem;color:var(--text-mid);padding-top:.8rem;border-top:1px solid rgba(10,22,40,.07)">{esc(snippet)}</div>
        </div>
        <div class="prop-actions">
          <a href="./nemovitost-{o['id']}.html" class="btn-prop-main" onclick="event.stopPropagation()">Zobrazit detail</a>
          {hypo}
        </div>
      </div>''')
    return "\n".join(cards)

# ───────────────────────── render: listing page ─────────────────────────
def render_listing(template, offers, n_active=None):
    n = len(offers)
    if n_active is None:
        n_active = n
    n_sale = sum(1 for o in offers if o["trans"] == "Prodej")
    n_rent = n - n_sale
    cities = sorted({o["short"] for o in offers}, key=lambda s: s.lower())
    cards = "\n".join(render_card(o, i) for i, o in enumerate(offers))

    t = template
    # hero podtitul
    t = re.sub(r"<p>Prohlédněte si \d+ aktivních inzerátů[^<]*</p>",
               f"<p>Prohlédněte si {n_active} aktivních inzerátů — prodej i pronájem po celé ČR</p>", t)
    # filtr tlačítka
    t = re.sub(r'(data-filter="all">Vše )\(\d+\)', rf"\g<1>({n})", t)
    t = re.sub(r'(data-filter="prodej">Prodej )\(\d+\)', rf"\g<1>({n_sale})", t)
    t = re.sub(r'(data-filter="pronajem">Pronájem )\(\d+\)', rf"\g<1>({n_rent})", t)
    # results count
    t = re.sub(r'(id="resCount">)\d+ nemovitostí', rf"\g<1>{n} nemovitostí", t)
    # city select
    opts = "".join(f"<option>{esc(c)}</option>" for c in cities)
    t = re.sub(r'(<option value="">Všechny lokality</option>)\s*(?:<option>[^<]*</option>)*',
               r"\1\n      " + opts, t, count=1)
    # grid
    start = '<div class="prop-grid" id="propGrid">'
    i = t.index(start) + len(start)
    # konec gridu = "\n  </div>\n</div>" (uzavírá grid a .content)
    j = t.index("\n  </div>\n</div>", i)
    t = t[:i] + "\n" + cards + "\n  " + t[j + 1:]
    return t

# ───────────────────────── render: detail page ─────────────────────────
def stat_block(o):
    items = [("Dispozice", o["disp"]), ("Plocha", o["plocha"]),
             ("Pozemek", o["pozemek"]), ("Dostupnost", o["avail"])]
    items = [(k, v) for k, v in items if v]
    if len(items) < 2:
        items.append(("Typ", o["label"]))
        items.append(("Lokalita", o["short"]))
        items = items[:3]
    hstats = "".join(
        f'<div class="hstat"><div class="hstat-val">{esc(v)}</div>'
        f'<div class="hstat-lbl">{k}</div></div>' for k, v in items)
    ICONS = {
        "Dispozice": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M3 9h6M3 15h6"/>',
        "Plocha":    '<path d="M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z"/>',
        "Pozemek":   '<polygon points="3 11 12 2 21 11"/><path d="M9 21V12h6v9"/>',
        "Dostupnost":'<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
        "Typ":       '<path d="M3 21h18M5 21V7l8-4v18M19 21V11l-6-4"/>',
        "Lokalita":  '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
    }
    params = "".join(
        f'<div class="param-item"><div class="param-ico"><svg width="16" height="16" '
        f'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">{ICONS[k]}</svg></div>'
        f'<div><div class="param-lbl">{k}</div><div class="param-val">{esc(v)}</div></div></div>'
        for k, v in items)
    return hstats, params

def render_gallery(o):
    imgs = o["imgs"]
    if not imgs:
        return ('<div style="margin-bottom:2.5rem"><div style="aspect-ratio:16/9;border-radius:14px;'
                f'background:{GRADIENTS[o["id"]%len(GRADIENTS)]}"></div></div>')
    main = imgs[0]
    grad = GRADIENTS[o["id"] % len(GRADIENTS)]
    thumbs = imgs[1:9]
    th = "".join(
        f'<div class="gthumb" onclick="setMain(\'{u}\',{i+1})" style="background:url(\'{u}\') '
        f'center/cover no-repeat;aspect-ratio:16/10;border-radius:8px;cursor:zoom-in;transition:all .2s;'
        f'border:2px solid transparent" onmouseover="this.style.borderColor=\'var(--teal)\'" '
        f'onmouseout="this.style.borderColor=\'transparent\'"></div>'
        for i, u in enumerate(thumbs))
    more = (f'<div style="text-align:center;margin-top:.5rem"><button onclick="openLightbox(0)" '
            f'style="background:transparent;border:1px solid rgba(10,22,40,.15);border-radius:8px;'
            f'padding:.4rem 1rem;font-size:.78rem;color:var(--text-mid);cursor:pointer">'
            f'Zobrazit všech {len(imgs)} fotek</button></div>') if len(imgs) > 1 else ""
    return (f'<div style="margin-bottom:2.5rem"><div id="mainImgWrap" onclick="openLightbox(0)" '
            f'style="cursor:zoom-in;border-radius:14px;overflow:hidden;margin-bottom:.6rem;'
            f'aspect-ratio:16/9;background:url(\'{main}\') center/cover no-repeat,{grad}"></div>'
            f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem">{th}</div>{more}</div>')

def render_similar(o, offers):
    others = [x for x in offers if x["id"] != o["id"] and x["trans"] == o["trans"]]
    others += [x for x in offers if x["id"] != o["id"] and x["trans"] != o["trans"]]
    pick = others[:3]
    cells = []
    for s in pick:
        img = s["imgs"][0] if s["imgs"] else ""
        grad = GRADIENTS[s["id"] % len(GRADIENTS)]
        bg = f"url('{img}') center/cover no-repeat,{grad}" if img else grad
        chips = "".join(
            f'<span style="background:var(--cream);border-radius:5px;padding:.15rem .45rem;'
            f'font-size:.68rem;font-weight:600;color:var(--navy)">{esc(v)}</span>'
            for v in [s["disp"], s["plocha"]] if v)
        title = s["title"][:46].rstrip()
        cells.append(
            f'<a href="./nemovitost-{s["id"]}.html" class="sim-card"><div style="height:160px;'
            f'background:{bg};border-radius:12px 12px 0 0"></div><div style="padding:.9rem 1rem 1rem">'
            f'<div style="font-size:.67rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;'
            f'color:var(--teal2);margin-bottom:.2rem">{esc(s["label"])}</div>'
            f'<div style="font-family:Poppins,sans-serif;font-weight:700;font-size:.88rem;line-height:1.3;'
            f'margin-bottom:.3rem;color:var(--navy)">{esc(title)}</div>'
            f'<div style="font-size:.75rem;color:var(--text-mid);margin-bottom:.3rem">{PIN14} {esc(s["short"])}</div>'
            f'<div style="display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:.4rem">{chips}</div>'
            f'<div style="font-family:Poppins,sans-serif;font-weight:800;font-size:1rem;color:var(--navy)">'
            f'{esc(s["price"])}</div></div></a>')
    if not cells:
        return ""
    return ('<div class="reveal" style="margin-top:2.5rem"><h2 style="font-family:Poppins,sans-serif;'
            'font-weight:700;font-size:1.3rem;margin-bottom:1.2rem;padding-bottom:.5rem;border-bottom:2px solid var(--cream)">'
            'Podobné nemovitosti</h2><div class="sim-grid">'
            + "".join(cells) + "</div></div>")

def render_detail(o, offers):
    name, phone, mail = o["agent"]
    phone_tel = "+420" + re.sub(r"\D", "", phone)
    hstats, params = stat_block(o)
    paras = "".join(
        f'<p style="font-size:1.06rem;line-height:1.85;color:var(--text-mid);margin-bottom:1rem">{esc(p)}</p>'
        for p in o["paras"]) or '<p style="font-size:1.06rem;line-height:1.85;color:var(--text-mid)">Pro více informací nás kontaktujte.</p>'
    gallery = render_gallery(o)
    similar = render_similar(o, offers)
    imgs_js = ", ".join(json.dumps(u) for u in o["imgs"])
    status = o.get("status", "volne")
    slabel, _ = STATUS_META.get(status, STATUS_META["volne"])
    sbg, sfg = STATUS_COLOR[status]
    hypo = ('<a href="kalkulacka.html" style="display:flex;align-items:center;gap:.5rem;'
            'background:rgba(245,166,35,.12);border:1px solid rgba(245,166,35,.3);border-radius:9px;'
            'padding:.7rem;color:var(--gold);text-decoration:none;font-weight:600;font-size:.83rem;'
            'margin-top:.5rem;justify-content:center">Spočítat hypotéku &#x2192;</a>'
            ) if o["trans"] == "Prodej" and status != "prodano" else ""
    status_badge = (f'<span style="background:{sbg};color:{sfg};padding:.25rem .7rem;border-radius:6px;'
                    f'font-size:.7rem;font-weight:700">{slabel}</span>')
    if status == "prodano":
        status_banner = (f'<div style="background:{sbg};color:{sfg};border-radius:10px;padding:.85rem 1.2rem;'
                         f'margin-bottom:1.4rem;font-weight:600;font-size:.92rem">Tato nemovitost je již '
                         f'<strong>prodaná</strong> — zobrazení pro referenci.</div>')
    elif status == "rezervovano":
        status_banner = (f'<div style="background:{sbg};color:{sfg};border-radius:10px;padding:.85rem 1.2rem;'
                         f'margin-bottom:1.4rem;font-weight:600;font-size:.92rem">Tato nemovitost je aktuálně '
                         f'<strong>rezervovaná</strong>. Máte-li zájem, ozvěte se — situace se může změnit.</div>')
    else:
        status_banner = ""
    badge = o["trans"]
    return DETAIL_TPL.format(
        title=esc(o["title"]), badge=badge, label=esc(o["label"]),
        short=esc(o["short"]), price=esc(o["price"]),
        hstats=hstats, gallery=gallery, params=params, paras=paras, similar=similar,
        agent=esc(name), initials=initials(name), phone=esc(phone), phone_tel=phone_tel,
        mail=esc(mail), hypo=hypo, imgs_js=imgs_js,
        status_badge=status_badge, status_banner=status_banner)

# ───────────────────────── shared chrome (z 1849) ─────────────────────────
NAV = '''<nav id="navbar">
  <a href="./index.html" class="nav-logo">
    <img src="./assets/logo.png" alt="Reality2u" class="nav-logo-img">
  </a>
  <ul class="nav-links" id="navLinks">
    <li><a href="./nemovitosti.html">Nabídka</a></li>
    <li><a href="./sluzby.html">Služby</a></li>
    <li><a href="./o-nas.html">O nás</a></li>
    <li><a href="./kontakt.html">Kontakt</a></li>
    <li><a href="https://money2u.cz" target="_blank">Financování</a></li>
  </ul>
  <div class="nav-ctas">
    <a href="./kontakt.html" class="btn btn-teal">Kontaktovat makléře</a>
  </div>
  <div class="hamburger" id="hamburger" onclick="toggleMenu()">
    <span></span><span></span><span></span>
  </div>
<button id="menuClose" onclick="closeMenu()">&#10005;</button>
</nav>'''

FOOTER = '''<footer>
  <div class="footer-grid">
    <div class="footer-brand">
      <a href="index.html" class="logo">
        <span class="logo-main"><span class="reality">reality</span><span class="twou">2u</span></span>
        <span class="logo-sub">Součást skupiny money2u</span>
      </a>
      <p>Váš spolehlivý realitní partner v Brně a okolí.</p>
    </div>
    <div class="footer-col footer-col-hide">
      <h4>Nemovitosti</h4>
      <ul>
        <li><a href="nemovitosti.html">Všechny nabídky</a></li>
        <li><a href="nemovitosti.html">Prodej</a></li>
        <li><a href="nemovitosti.html">Pronájem</a></li>
      </ul>
    </div>
    <div class="footer-col">
      <h4>Menu</h4>
      <ul>
        <li><a href="index.html">Úvod</a></li>
        <li><a href="nemovitosti.html">Nabídka</a></li>
        <li><a href="sluzby.html">Služby</a></li>
        <li><a href="o-nas.html">O nás</a></li>
        <li><a href="kontakt.html">Kontakt</a></li>
        <li><a href="https://money2u.cz" target="_blank">money2u.cz</a></li>
      </ul>
    </div>
    <div class="footer-col footer-col-hide">
      <h4>Kontakt</h4>
      <ul>
        <li><a href="#">Tolstého 35, Brno</a></li>
        <li><a href="tel:+420799794670">+420 799 794 670</a></li>
        <li><a href="mailto:info@reality2u.cz">info@reality2u.cz</a></li>
      </ul>
    </div>
  </div>
  <div class="footer-bottom">
    <p>© 2026 reality2u s.r.o. Všechna práva vyhrazena.</p>
    <p><a href="https://money2u.cz" target="_blank">Součást skupiny money2u</a></p>
  </div>
</footer>

<style>
footer{{background:#060e1a;padding:4rem 5% 2rem;border-top:1px solid rgba(153,198,195,.1);font-family:'Inter',sans-serif}}
footer .footer-grid{{max-width:1200px;margin:0 auto;display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:3rem;margin-bottom:3rem}}
footer .footer-brand p{{color:rgba(255,255,255,.55);font-size:.9rem;margin-top:.8rem;line-height:1.7}}
footer .logo{{text-decoration:none;display:block;margin-bottom:.5rem}}
footer .logo-main{{display:block;font-family:'Poppins',sans-serif;font-weight:900;font-size:1.5rem}}
footer .logo-main .reality{{color:#fff}}
footer .logo-main .twou{{color:#99C6C3}}
footer .logo-sub{{display:block;font-size:.72rem;color:rgba(255,255,255,.4);letter-spacing:.05em;margin-top:.15rem}}
footer .footer-col h4{{font-family:'Poppins',sans-serif;font-size:.85rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#99C6C3;margin-bottom:1rem}}
footer .footer-col ul{{list-style:none;padding:0;margin:0}}
footer .footer-col ul li{{margin-bottom:.5rem}}
footer .footer-col ul li a{{color:rgba(255,255,255,.6);font-size:.9rem;text-decoration:none;transition:color .2s}}
footer .footer-col ul li a:hover{{color:#99C6C3}}
footer .footer-bottom{{max-width:1200px;margin:0 auto;padding-top:1.5rem;border-top:1px solid rgba(255,255,255,.08);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem}}
footer .footer-bottom p{{font-size:.82rem;color:rgba(255,255,255,.4);margin:0}}
footer .footer-bottom a{{color:#99C6C3}}
@media(max-width:768px){{footer .footer-grid{{grid-template-columns:1fr 1fr;gap:2rem}}footer .footer-col-hide{{display:none}}}}
@media(max-width:500px){{footer .footer-grid{{grid-template-columns:1fr}}footer .footer-col-hide{{display:none}}}}
</style>

<script>
function toggleMenu(){{var m=document.getElementById('navLinks');var btn=document.getElementById('menuClose');if(!m)return;var isOpen=m.classList.contains('open');if(isOpen){{m.classList.remove('open');if(btn)btn.classList.remove('visible');document.body.style.overflow='';}}else{{m.classList.add('open');if(btn)btn.classList.add('visible');document.body.style.overflow='hidden';}}}}
function closeMenu(){{var m=document.getElementById('navLinks');var btn=document.getElementById('menuClose');if(m)m.classList.remove('open');if(btn)btn.classList.remove('visible');document.body.style.overflow='';}}
document.addEventListener('DOMContentLoaded',function(){{document.querySelectorAll('#navLinks a').forEach(function(a){{a.addEventListener('click',closeMenu);}});}});
</script>'''

# detailová šablona (1:1 dle nemovitost-1849.html, jen makléř bez cloudflare-email obfuskace)
DETAIL_TPL = '''<!DOCTYPE html>
<html lang="cs">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — reality2u</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700;800;900&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
#navbar{{position:fixed;top:0;left:0;right:0;z-index:900;height:72px;display:flex;align-items:center;justify-content:space-between;padding:0 5%;background:rgba(10,22,40,.97);backdrop-filter:blur(20px);transition:background .3s}}
.nav-logo{{display:flex;align-items:center;gap:10px;text-decoration:none}}
.nav-logo-img{{height:120px;width:auto;object-fit:contain;mix-blend-mode:screen}}
.nav-links{{display:flex;gap:2rem;list-style:none;margin:0;padding:0}}
.nav-links a{{color:rgba(255,255,255,.8);text-decoration:none;font-size:.9rem;font-weight:700;transition:color .2s}}
.nav-links a:hover{{color:var(--teal)}}
.nav-ctas{{display:flex;gap:.6rem;align-items:center}}
.btn-teal{{background:linear-gradient(135deg,var(--teal),var(--teal2));color:var(--navy);font-weight:700}}
.hamburger{{display:none;flex-direction:column;gap:5px;cursor:pointer;padding:.3rem}}
.hamburger span{{width:22px;height:2px;background:#fff;border-radius:2px;transition:all .3s}}
@media(max-width:700px){{.nav-links,.nav-ctas{{display:none}}.hamburger{{display:flex}}}}
:root{{--navy:#0A1628;--navy2:#122040;--teal:#99C6C3;--teal2:#7caaa7;--gold:#F5A623;--cream:#F8F6F0;--white:#fff;--text-mid:rgba(10,22,40,.6)}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
body{{font-family:'Inter',sans-serif;background:#f0f2f5;color:var(--navy);overflow-x:hidden}}
.btn{{display:inline-flex;align-items:center;padding:.5rem 1.1rem;border-radius:8px;font-size:.85rem;font-weight:600;cursor:pointer;text-decoration:none;border:none;transition:all .2s;font-family:Inter,sans-serif;white-space:nowrap}}
.btn-teal{{background:linear-gradient(135deg,var(--teal),var(--teal2));color:var(--navy);font-weight:700}}
.btn-teal:hover{{box-shadow:0 4px 16px rgba(153,198,195,.4);transform:translateY(-1px)}}
.detail-wrap{{max-width:1400px;margin:0 auto;padding:96px 5% 4.5rem;display:grid;grid-template-columns:1fr 380px;gap:3rem;align-items:start}}
.detail-main{{min-width:0}}
.detail-text{{max-width:920px}}
.hstat-row{{display:flex;flex-wrap:wrap;gap:1.2rem;margin:1rem 0 1.5rem;padding:1.2rem 1.5rem;background:#fff;border-radius:14px;box-shadow:0 2px 12px rgba(10,22,40,.06)}}
.hstat{{text-align:center;min-width:72px}}
.hstat-val{{font-family:Poppins,sans-serif;font-weight:800;font-size:1.6rem;color:var(--navy);line-height:1.1}}
.hstat-lbl{{font-size:.68rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-mid);margin-top:.2rem}}
.param-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:.75rem;margin-bottom:2rem;max-width:920px}}
.param-item{{display:flex;align-items:center;gap:.8rem;background:#fff;border-radius:12px;padding:.9rem 1.1rem;box-shadow:0 1px 6px rgba(10,22,40,.05)}}
.param-ico{{color:var(--teal2);flex-shrink:0;display:flex}}
.param-lbl{{font-size:.66rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--text-mid)}}
.param-val{{font-family:Poppins,sans-serif;font-weight:700;font-size:1.02rem;color:var(--navy)}}
.contact-card{{background:var(--navy);border-radius:18px;padding:1.6rem;color:#fff}}
.agent-av{{width:50px;height:50px;border-radius:50%;background:linear-gradient(135deg,var(--teal),var(--teal2));display:flex;align-items:center;justify-content:center;font-family:Poppins,sans-serif;font-weight:800;font-size:1rem;color:var(--navy);flex-shrink:0}}
.inp{{width:100%;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);border-radius:9px;padding:.6rem .9rem;color:#fff;font-size:.83rem;font-family:Inter,sans-serif;outline:none;transition:border .2s;margin-bottom:.5rem}}
.inp:focus{{border-color:rgba(153,198,195,.5)}}
.inp::placeholder{{color:rgba(255,255,255,.3)}}
.sim-card{{display:block;background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(10,22,40,.08);transition:all .3s;text-decoration:none;overflow:hidden}}
.sim-card:hover{{transform:translateY(-4px);box-shadow:0 12px 32px rgba(10,22,40,.14)}}
.sim-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:1.2rem}}
.gthumb:hover{{opacity:.85}}
.lightbox{{position:fixed;inset:0;background:rgba(0,0,0,.95);z-index:9999;display:none;align-items:center;justify-content:center;flex-direction:column}}
.lightbox.open{{display:flex}}
.lb-img{{max-width:90vw;max-height:80vh;object-fit:contain;border-radius:12px}}
.lb-close,.lb-nav{{position:absolute;border:none;background:rgba(255,255,255,.12);color:#fff;cursor:pointer;border-radius:50%;width:44px;height:44px;font-size:1.4rem;display:flex;align-items:center;justify-content:center}}
.lb-close{{top:1.5rem;right:1.5rem;font-size:1.8rem}}
.lb-nav{{top:50%;transform:translateY(-50%)}}
.lb-prev{{left:1rem}}.lb-next{{right:1rem}}
footer{{background:#060e1a;padding:2.5rem 5% 1.5rem;border-top:1px solid rgba(153,198,195,.08)}}
.footer-inner{{display:grid;grid-template-columns:2fr 1fr 1fr;gap:2rem;max-width:1100px;margin:0 auto 1.8rem}}
.reveal{{opacity:0;transform:translateY(20px);transition:opacity .55s ease,transform .55s ease}}
.reveal.visible{{opacity:1;transform:none}}
@media(max-width:980px){{.detail-wrap{{grid-template-columns:1fr;gap:2rem;padding:88px 5% 3.5rem}}.detail-text{{max-width:none}}.param-grid{{max-width:none}}}}
@media(max-width:600px){{.hstat-row{{gap:.9rem 1.4rem;padding:1.1rem 1.2rem}}.hstat-val{{font-size:1.35rem}}.param-grid{{grid-template-columns:1fr}}.sim-grid{{grid-template-columns:1fr}}}}
@media(max-width:700px){{
  #navLinks{{display:none;position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:9999;flex-direction:column;align-items:center;justify-content:center;background:#99C6C3 !important;list-style:none;padding:0;margin:0;}}
  #navLinks.open{{display:flex !important;}}
  #navLinks li{{width:90%;text-align:center;border-bottom:1px solid rgba(13,31,58,.2);}}
  #navLinks a,#navLinks a.active,#navLinks a:hover{{display:block;padding:20px 0;font-size:clamp(2rem,9vw,3.5rem) !important;color:#0D1F3A !important;font-weight:900 !important;text-decoration:none !important;letter-spacing:-.02em;opacity:1 !important;}}
  #navLinks a:hover{{opacity:.6 !important;}}
  .hamburger{{display:flex !important;}}
  .nav-ctas{{display:none !important;}}
  #menuClose{{display:none;position:fixed;top:24px;right:24px;z-index:10000;background:none;border:none;cursor:pointer;font-size:2.2rem;color:#0D1F3A;font-weight:900;line-height:1;padding:0;}}
  #menuClose.visible{{display:block !important;}}
}}
#menuClose{{display:none;}}
.nav-links a {{ font-size: 1rem !important; font-weight: 700 !important; position: relative; }}
.nav-links a::after {{ content: ''; position: absolute; bottom: -4px; left: 0; right: 0; height: 2px; background: #99C6C3; border-radius: 2px; transform: scaleX(0); transition: transform .2s; }}
.nav-links a:hover {{ color: #99C6C3 !important; }}
.nav-links a:hover::after {{ transform: scaleX(1); }}
.btn-teal {{ font-size: .95rem !important; padding: .7rem 1.5rem !important; }}
</style>
</head>
<body>
{nav}
<div class="detail-wrap">
  <div class="detail-main">
    <div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.8rem;flex-wrap:wrap">
      <span style="background:rgba(153,198,195,.9);color:var(--navy);padding:.25rem .7rem;border-radius:6px;font-size:.7rem;font-weight:700">{badge}</span>
      {status_badge}
      <span style="font-size:.78rem;color:var(--text-mid)"><a href="./index.html" style="color:var(--teal2);text-decoration:none">Domů</a> / <a href="./nemovitosti.html" style="color:var(--teal2);text-decoration:none">Nabídka</a> / {label}</span>
    </div>
    <h1 style="font-family:Poppins,sans-serif;font-weight:800;font-size:clamp(1.7rem,3.4vw,2.5rem);line-height:1.2;color:var(--navy);margin-bottom:.5rem">{title}</h1>
    <p style="font-size:.95rem;color:var(--text-mid);margin-bottom:.5rem">{pin} {short}</p>
    <div style="font-family:Poppins,sans-serif;font-weight:900;font-size:2.4rem;color:var(--navy);margin-bottom:.2rem">{price}</div>
    <div style="height:.5rem"></div>
    <div class="hstat-row reveal">{hstats}</div>
    {status_banner}
    {gallery}
    <div class="param-grid reveal">{params}</div>
    <div class="reveal detail-text" style="margin-bottom:1.8rem">
      <h2 style="font-family:Poppins,sans-serif;font-weight:700;font-size:1.3rem;margin-bottom:1rem;padding-bottom:.5rem;border-bottom:2px solid var(--cream)">Popis nemovitosti</h2>
      {paras}
    </div>
    <div style="background:var(--cream);border-radius:10px;padding:1rem 1.2rem;margin-bottom:2rem;font-size:.74rem;color:var(--text-mid);line-height:1.7">
      Tato nabídka není veřejný příslib dle § 1733 občanského zákoníku. Z nabídky nikomu nevzniká nárok na uzavření smlouvy.
    </div>
    {similar}
  </div>
  <div style="position:sticky;top:84px">
    <div class="contact-card">
      <div style="font-family:Poppins,sans-serif;font-weight:700;font-size:.9rem;margin-bottom:1rem;color:rgba(255,255,255,.8)">Kontaktovat makléře</div>
      <div style="display:flex;align-items:center;gap:.75rem;margin-bottom:1.1rem">
        <div class="agent-av">{initials}</div>
        <div><div style="font-weight:700;font-size:.92rem">{agent}</div><div style="font-size:.72rem;color:rgba(255,255,255,.45)">Makléř · reality2u</div></div>
      </div>
      <a href="tel:{phone_tel}" style="display:flex;align-items:center;gap:.5rem;background:rgba(153,198,195,.15);border:1px solid rgba(153,198,195,.25);border-radius:9px;padding:.7rem;color:var(--teal);text-decoration:none;font-weight:600;font-size:.85rem;margin-bottom:.5rem">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13 19.79 19.79 0 0 1 1.61 4.39 2 2 0 0 1 3.6 2.18h3a2 2 0 0 1 2 1.72c.13 1 .37 1.97.7 2.91a2 2 0 0 1-.45 2.11L7.91 9.91a16 16 0 0 0 6.18 6.18l.99-.99a2 2 0 0 1 2.11-.45c.94.33 1.91.57 2.91.7A2 2 0 0 1 22 16.92z"/></svg>
        {phone}
      </a>
      <a href="mailto:{mail}" style="display:flex;align-items:center;gap:.5rem;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08);border-radius:9px;padding:.7rem;color:rgba(255,255,255,.65);text-decoration:none;font-size:.82rem;margin-bottom:1rem">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
        {mail}
      </a>
      <input class="inp" placeholder="Vaše jméno" id="cf-name">
      <input class="inp" placeholder="Telefon nebo email" id="cf-contact">
      <textarea class="inp" rows="3" placeholder="Zpráva..." id="cf-msg" style="resize:none"></textarea>
      <button onclick="sendInq()" style="width:100%;background:linear-gradient(135deg,var(--teal),var(--teal2));color:var(--navy);border:none;border-radius:9px;padding:.75rem;font-weight:700;font-size:.88rem;cursor:pointer;font-family:Inter,sans-serif">Odeslat poptávku</button>
      {hypo}
    </div>
    <div style="background:#fff;border-radius:14px;padding:1.2rem;margin-top:.8rem;font-size:.79rem;color:var(--text-mid);line-height:1.85;box-shadow:0 2px 12px rgba(10,22,40,.06)">
      <strong style="color:var(--navy);font-weight:700;font-size:.85rem">reality2u s.r.o.</strong><br>
      {pin} Tolstého 35, 616 00 Brno<br>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-2px;flex-shrink:0"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 12 19.79 19.79 0 0 1 1.63 3.4 2 2 0 0 1 3.6 1.21h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L7.91 8.2a16 16 0 0 0 5.89 5.89l.95-.95a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 21.27 15.5z"/></svg> <a href="tel:+420722967163" style="color:var(--teal2);text-decoration:none">+420 722 967 163</a><br>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-2px;flex-shrink:0"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg> <a href="mailto:asistentka@reality2u.cz" style="color:var(--teal2);text-decoration:none">asistentka@reality2u.cz</a><br>
      IČO: 04690915
    </div>
  </div>
</div>
<div class="lightbox" id="lb">
  <button class="lb-close" onclick="closeLb()">&#x2715;</button>
  <button class="lb-nav lb-prev" onclick="lbNav(-1)">&#x2039;</button>
  <img class="lb-img" id="lbImg" src="" alt="">
  <button class="lb-nav lb-next" onclick="lbNav(1)">&#x203A;</button>
  <div style="color:rgba(255,255,255,.4);font-size:.75rem;margin-top:.7rem" id="lbCnt"></div>
</div>
<script>
const obs=new IntersectionObserver(e=>e.forEach(x=>{{if(x.isIntersecting)x.target.classList.add('visible')}}),{{threshold:.1}});
document.querySelectorAll('.reveal').forEach(el=>obs.observe(el));
const IMGS=[{imgs_js}];
let cur=0;
function openLightbox(i){{if(!IMGS.length)return;cur=i;document.getElementById('lb').classList.add('open');updLb()}}
function closeLb(){{document.getElementById('lb').classList.remove('open')}}
function lbNav(d){{cur=(cur+d+IMGS.length)%IMGS.length;updLb()}}
function updLb(){{document.getElementById('lbImg').src=IMGS[cur];document.getElementById('lbCnt').textContent=(cur+1)+' / '+IMGS.length}}
function setMain(src,idx){{document.getElementById('mainImgWrap').style.backgroundImage="url('"+src+"')";cur=idx}}
document.getElementById('lb').addEventListener('click',e=>{{if(e.target===e.currentTarget)closeLb()}})
document.addEventListener('keydown',e=>{{if(e.key==='Escape')closeLb();if(e.key==='ArrowLeft')lbNav(-1);if(e.key==='ArrowRight')lbNav(1)}})
function sendInq(){{
  const n=document.getElementById('cf-name').value.trim();
  const c=document.getElementById('cf-contact').value.trim();
  if(!n||!c){{alert('Vyplňte prosím jméno a kontakt.');return}}
  alert('Děkujeme, '+n+'! {agent} vás bude kontaktovat co nejdříve.');
  ['cf-name','cf-contact','cf-msg'].forEach(id=>document.getElementById(id).value='')
}}
window.addEventListener('scroll',()=>document.getElementById('navbar').classList.toggle('scrolled',window.scrollY>30));
</script>
<script id="nav-active">
(function(){{var page=location.pathname.split('/').pop()||'index.html';document.querySelectorAll('.nav-links a').forEach(function(a){{var href=a.getAttribute('href').replace('./','');if(href===page)a.classList.add('active');}});}})();
</script>
{footer}
</body>
</html>'''

# vlož sdílené chrome do detailové šablony (pin se používá vícekrát)
DETAIL_TPL = DETAIL_TPL.replace("{nav}", NAV).replace("{footer}", FOOTER).replace("{pin}", PIN14)

# ───────────────────────── build ─────────────────────────
SHELL_KEEP = ["index.html", "sluzby.html", "o-nas.html", "kontakt.html",
              "kalkulacka.html", "odhad.html", "vercel.json"]

def build(out_dir, offline=False):
    print(f"[1/5] seznam aktivních inzerátů…")
    lst = collect_list(offline=offline)
    print(f"      → {len(lst)} inzerátů: {', '.join(str(i) for i,_ in lst)}")

    print(f"[2/5] stahuju detaily…")
    active = []
    for oid, loc in lst:
        h = fetch_detail(oid, offline=offline)
        o = parse_offer(oid, h, loc)
        active.append(o)
        print(f"      ✓ {oid:>5}  {o['trans']:8} {o['label']:12} disp={str(o['disp']):>9} "
              f"plocha={str(o['plocha']):>7} img={len(o['imgs']):>2}  {o['short']}")

    # ── stavy: volné (feed) / rezervované (ruční) / prodané (auto-archiv zmizelých) ──
    print(f"[3/5] stavy inzerátů…")
    ov = load_status()
    active_ids = {o["id"] for o in active}
    visible = []
    for o in active:
        if o["id"] in ov["skryto"]:
            continue
        o["status"] = ("prodano" if o["id"] in ov["prodano"] else
                       "rezervovano" if o["id"] in ov["rezervovano"] else "volne")
        visible.append(o)
    # archiv pro auto-detekci prodaných (co zmizí z feedu = prodáno)
    try:
        archive = json.load(open(ARCHIVE_FILE, encoding="utf-8"))
    except Exception:
        archive = {}
    now = time.time()
    for o in active:
        archive[str(o["id"])] = {"ts": now, "offer": o}
    sold = []
    for k, v in archive.items():
        oid = int(k)
        if oid in active_ids or oid in ov["skryto"]:
            continue
        so = dict(v.get("offer", {})); so["status"] = "prodano"
        if so.get("id"): sold.append((v.get("ts", 0), so))
    sold.sort(key=lambda x: -x[0])
    sold_show = [o for _, o in sold[:SOLD_KEEP]]
    keep = active_ids | {o["id"] for o in sold_show}
    archive = {k: v for k, v in archive.items() if int(k) in keep}

    render_offers = visible + sold_show
    nv = sum(1 for o in visible if o["status"] == "volne")
    nr = sum(1 for o in visible if o["status"] == "rezervovano")
    np = sum(1 for o in visible if o["status"] == "prodano")
    print(f"      volné={nv}  rezervované={nr}  prodané(ruční)={np}  prodané(archiv)={len(sold_show)}")

    slug_by_id = {o["id"]: detail_slug(o) for o in render_offers}

    os.makedirs(out_dir, exist_ok=True)
    print(f"[4/5] shell + assets → {out_dir}")
    src_assets = os.path.join(TEMPLATE_DIR, "assets")
    if os.path.isdir(src_assets):
        shutil.copytree(src_assets, os.path.join(out_dir, "assets"), dirs_exist_ok=True)
    for f in SHELL_KEEP:
        s = os.path.join(TEMPLATE_DIR, f)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(out_dir, f))

    # homepage: „Vybrané nemovitosti“ = 3 aktuální inzeráty z feedu (vzhled 1:1)
    idx_path = os.path.join(out_dir, "index.html")
    if os.path.exists(idx_path):
        ih = open(idx_path, encoding="utf-8").read()
        feat = render_featured(visible)
        if "<!--FEATURED-->" in ih:
            ih = ih.replace("<!--FEATURED-->", feat)
        else:
            # fallback: nahraď obsah .prop-grid na homepage (start tag → nejbližší uzávěr na 4 mezery)
            st = '<div class="prop-grid">'
            a = ih.find(st)
            if a != -1:
                a += len(st)
                b = ih.find("\n    </div>", a)
                if b != -1:
                    ih = ih[:a] + "\n" + feat + "\n  " + ih[b + 1:]
        open(idx_path, "w", encoding="utf-8").write(ih)

    print(f"[5/5] generuju nemovitosti.html + {len(render_offers)} detailů (čisté URL)")
    template = open(os.path.join(TEMPLATE_DIR, "nemovitosti.html"), encoding="utf-8").read()
    listing = render_listing(template, render_offers, n_active=len(visible))
    open(os.path.join(out_dir, "nemovitosti.html"), "w", encoding="utf-8").write(listing)

    # smaž staré detaily (numeric i slug), zapiš nové slug soubory
    for f in os.listdir(out_dir):
        if re.match(r"nemovitost-.*\.html$", f):
            os.remove(os.path.join(out_dir, f))
    for o in render_offers:
        page = render_detail(o, visible)   # podobné nemovitosti = z aktivních
        open(os.path.join(out_dir, slug_by_id[o["id"]] + ".html"), "w", encoding="utf-8").write(page)

    # čisté URL ve VŠECH stránkách (shell + generované)
    for f in os.listdir(out_dir):
        if f.endswith(".html"):
            p = os.path.join(out_dir, f)
            s = open(p, encoding="utf-8").read()
            open(p, "w", encoding="utf-8").write(cleanify(s, slug_by_id))

    # snapshot (pro change-detection v refresh.sh) + archiv
    snap = [{k: v for k, v in o.items() if k != "paras"} | {"paras_n": len(o["paras"])}
            for o in render_offers]
    json.dump(snap, open(os.path.join(out_dir, "_offers.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(archive, open(ARCHIVE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n✅ HOTOVO — {len(render_offers)} stránek do {out_dir}  "
          f"(volné {nv}, rezervované {nr}, prodané {np + len(sold_show)})")
    return render_offers

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    build(a.out, offline=a.offline)

if __name__ == "__main__":
    main()
