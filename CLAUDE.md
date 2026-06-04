# Reality2u

## What This Is
SaaS pro analýzu rodinných domů v ČR - jak je rozdělit na max. malých bytů, kalkulace nákladů na rekonstrukci, výnosů z pronájmu a generování nabídek.

## Current State
- Status: IN PROGRESS
- Last session: 2026-06-01
- Web reality2u.cz napojen na živý feed inzerátů (myBRIK) + auto-refresh

## Tech Stack
- Statický web, nasazen na Vercelu (projekt `reality2you-web`) → domény reality2u.cz, reality2u.djai.cz
- Generátor inzerátů: Python (`tools/generate.py`), bez závislostí

## Datový feed inzerátů (myBRIK / SAB servis)
- Zdroj: veřejný endpoint `https://inzeraty.reality2u.cz/?ajax=1` (seznam+GPS) a `?inzerat_id=ID` (detail)
- Generátor stáhne aktivní inzeráty a NAFORMÁTUJE je do stávajících šablon → vzhled 1:1, čerstvá data
- Endpoint NEMÁ CORS → data se formátují při buildu, ne klientsky
- Detaily: dispozice/plocha/pozemek se parsují z titulku+popisu (best-effort)

## Key Files
- `tools/generate.py` -- generátor: feed → stávající vzhled (listing + detaily)
- `tools/refresh.sh` -- auto-refresh (ruční spuštění z repa)
- **Auto-refresh běží na home serveru** `emil@100.87.36.51:/home/emil/reality2u-autorefresh/` (cron `0 */4 * * *`, skript `refresh.sh`, deploy přes vercel CLI + token v `.vercel_token`). Sem se syncuje generate.py + source/ + status.json při změnách kódu.
- `~/reality2u-autorefresh/` (Mac) + `cz.reality2u.refresh.plist.disabled` -- starý launchd job, **vypnutý** (přesunuto na server)
- `source/` -- kanonické šablony + statický shell (index, sluzby, …)
- `reality2u.djai.cz/` -- nasazovaná kopie (zrcadlo `public/`)
- `deploy/` -- alternativní Coolify/Docker config (nepoužito, web jede na Vercelu)

## Deployments
- Production: **reality2u.cz** (Vercel, projekt reality2you-web), aliasy reality2u.djai.cz / reality2u.kurdiovsti.cz
- Pozn.: domény *.djai.cz aktuálně neresolvují (DNS CNAME na Cloudflare nenastaveno) — veřejně jede reality2u.cz
- Auto-refresh: launchd 4×/den přegeneruje z feedu a nasadí jen když se inzeráty změní

## Session Log
### 2026-06-01 -- Mobil fix + dynamická homepage + úklid
- **Mobil „Podobné nemovitosti":** sekce na detailu měla natvrdo inline `grid-template-columns:repeat(3,1fr)` bez media query → na mobilu 3 karty vedle sebe. Fix v `generate.py`: třída `.sim-grid` (PC 3 sloupce) + `@media(max-width:600px){.sim-grid{grid-template-columns:1fr}}`.
- **Homepage „Vybrané nemovitosti" je teď dynamická:** v `source/index.html` jsou 3 napevno vložené karty (staré ID 1841/1847/1849, 2 už prodané) nahrazeny markerem `<!--FEATURED-->`; `render_featured()` v `generate.py` ho při buildu naplní 3 aktuálními volnými inzeráty z feedu (vzhled 1:1, čisté slug URL). Auto-refresh je drží čerstvé. **→ vyřešen open thread o starých kartách.**
- **Úklid:** smazána stray složka `emil@100.87.36eality2u-autorefresh/` (přesná duplicita `source/`, vznikla překlepem ve scp bez dvojtečky).
- **Kapitalizace titulků:** `cap_first()` v `generate.py` dává velké první písmeno titulkům z feedu (některé chodí malými, např. „prodej…") → projevuje se na kartách i detailech; slug nedotčen.
- Vše přegenerováno, zrcadleno do `reality2u.djai.cz/`, nasazeno na prod (Vercel) a `generate.py` + `source/` synced na home server (md5 ověřeno), aby cron změny nepřepsal. Ověřeno živě na reality2u.cz (3 karty, prokliky HTTP 200, mobil 1 sloupec).

### 2026-06-01 -- Napojení živého feedu inzerátů + auto-refresh
- Reverzně rozklíčován veřejný myBRIK endpoint (`inzeraty.reality2u.cz/?ajax=1` + `?inzerat_id`)
- Napsán generátor `tools/generate.py`: 26 aktivních inzerátů → stávající vzhled (listing + 26 detailů)
- Ověřeno workflow (26/26 ok, 0 high/medium) + vizuálně; nasazeno na prod reality2u.cz
- Auto-refresh přes launchd (`tools/refresh.sh`, deploy jen při změně dat)
- Layout fix: širší kontejnery (detail 1400px, listing 1440px), větší typografie, oprava přetékání mobilního search boxu (`source/nemovitosti.html` + DETAIL_TPL v generate.py)
- Stavy inzerátů: badge volné/rezervované/prodané na kartách i detailu + filtr stavu. Volné=feed default, prodané=auto-archiv (`_known_offers.json`, zmizí z feedu), rezervované=ruční `status.json`. Feed sám stav nenese.
- Čisté URL: `cleanUrls` na Vercelu + slug detaily `nemovitost-<slug>-<id>` (bez .html). cleanify() v generate.py přepisuje všechny odkazy.
- Auto-refresh přesunut z Macu na **home server** (cron, vercel CLI + token); Mac launchd vypnut. SSH na server z tohoto Macu už funguje (`ssh emil@100.87.36.51`).
- Pozn.: homepage `index.html` měla napevno staré „featured" karty (1841/1847/1849) — **vyřešeno 2026-06-01: homepage karty jsou teď dynamické z feedu (`render_featured`).**

### 2026-05-23 -- CLAUDE.md initialized
- Retrospektivně vytvořen CLAUDE.md pro project management

## Decisions
- Cílový trh: ČR (sreality.cz)
- Analýza: max. bytových jednotek z rodinného domu
- Kalkulace: náklady na rekonstrukci, rental yield, cílová marže

## Open Threads
- Demo website se sketchi/mockupy
- AI konfigurátor
