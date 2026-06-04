#!/usr/bin/env bash
# reality2u — auto-refresh: stáhne aktuální inzeráty, přegeneruje web do stávajícího
# vzhledu a (jen když se data změní) nasadí na Vercel prod (projekt reality2you-web →
# domény reality2u.cz / reality2u.djai.cz). Volá se z launchd/cronu.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

ORG="team_BGRPbbAtkna08wJLTgokBjIt"
PRJ="prj_6J0JERFsyeKZIItVQtu0EwV0LkxG"   # reality2you-web (reality2u.cz)
LOG="$ROOT/tools/refresh.log"
ts(){ date "+%Y-%m-%d %H:%M:%S"; }
echo "[$(ts)] === refresh start ===" >>"$LOG"

PREV="$ROOT/public/_offers.json"
PREV_BAK="/tmp/r2u_prev_offers.json"
[ -f "$PREV" ] && cp "$PREV" "$PREV_BAK" || rm -f "$PREV_BAK"

# 1) generuj přímo do public/ (zachová public/.vercel link)
if ! python3 tools/generate.py --out "$ROOT/public" >>"$LOG" 2>&1; then
  echo "[$(ts)] generátor SELHAL – nechávám předchozí verzi, nenasazuji" >>"$LOG"; exit 1
fi

# 2) zrcadli do repo kopie (bez .vercel)
mkdir -p "$ROOT/reality2u.djai.cz"
rsync -a --delete --exclude '.vercel' "$ROOT/public/" "$ROOT/reality2u.djai.cz/" >>"$LOG" 2>&1

# 3) ujisti se o Vercel linku
mkdir -p "$ROOT/public/.vercel"
printf '{"orgId":"%s","projectId":"%s"}\n' "$ORG" "$PRJ" > "$ROOT/public/.vercel/project.json"

# 4) nasaď jen když se data změnila
if [ -f "$PREV_BAK" ] && diff -q "$PREV_BAK" "$ROOT/public/_offers.json" >/dev/null 2>&1; then
  echo "[$(ts)] data beze změny – deploy přeskočen" >>"$LOG"
  echo "[$(ts)] === refresh done (no change) ===" >>"$LOG"; exit 0
fi

if command -v vercel >/dev/null 2>&1; then
  ( cd "$ROOT/public" && vercel deploy --prod --yes >>"$LOG" 2>&1 ) \
    && echo "[$(ts)] deploy OK (data se změnila)" >>"$LOG" \
    || echo "[$(ts)] vercel deploy SELHAL" >>"$LOG"
else
  echo "[$(ts)] vercel CLI chybí – deploy přeskočen" >>"$LOG"
fi
echo "[$(ts)] === refresh done ===" >>"$LOG"
