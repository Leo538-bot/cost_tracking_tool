#!/usr/bin/env bash
# Startet TripCost. Ein Kommando, alles inklusive:
#   ./start.sh
#
# Legt beim ersten Mal die .env mit Zufallswerten an, sucht einen freien Port,
# baut die Images und wartet, bis die App wirklich antwortet.
set -euo pipefail

cd "$(dirname "$0")"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31mAbbruch:\033[0m %s\n\n' "$*" >&2; exit 1; }

# --- 1. Voraussetzungen ----------------------------------------------------

say "1/5  Voraussetzungen prüfen"

command -v docker >/dev/null 2>&1 || die \
"Docker ist nicht installiert.
  Installationsanleitung: https://docs.docker.com/engine/install/"

if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    die \
"Es ist nur das alte docker-compose (v1) installiert, das reicht nicht.
  Installiere das Compose-Plugin v2:
    sudo apt-get install docker-compose-plugin
  Danach prüfen mit:  docker compose version"
else
    die \
"Docker Compose fehlt.
  Installieren mit:  sudo apt-get install docker-compose-plugin"
fi
ok "$($DC version | head -1)"

if ! docker info >/dev/null 2>&1; then
    die \
"Der Docker-Daemon antwortet nicht. Entweder läuft er nicht, oder dein
  Benutzer darf ihn nicht ansprechen.

  Läuft er?          sudo systemctl start docker
  Rechte fehlen?     sudo usermod -aG docker \"\$USER\"
                     Danach einmal ab- und wieder anmelden.

  (Alternativ ginge 'sudo ./start.sh' -- dann gehören die erzeugten
   Dateien allerdings root.)"
fi
ok "Docker-Daemon erreichbar"

# Schreibrechte im Projektverzeichnis -- sonst scheitert erst die .env.
if [ ! -w . ]; then
    die \
"Kein Schreibrecht in $(pwd).
  Einmalig geraderücken mit:
    sudo chown -R \"\$USER\":\"\$USER\" \"$(pwd)\""
fi
ok "Schreibrechte vorhanden"

# --- 2. Konfiguration ------------------------------------------------------

say "2/5  Konfiguration"

random_secret() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 32
    else
        head -c 32 /dev/urandom | base64 | tr -d '\n'
    fi
}

if [ -f .env ]; then
    ok ".env vorhanden, bleibt unverändert"
else
    umask 077
    cat > .env <<INNER
# Von start.sh erzeugt. Enthält Geheimnisse -- nicht ins Git (ist ignoriert).

POSTGRES_PASSWORD=$(random_secret)
JWT_SECRET=$(random_secret)

POSTGRES_USER=tripcost
POSTGRES_DB=tripcost

# Port und Bindeadresse. 127.0.0.1 = nur lokal (richtig für den Cloudflare
# Tunnel). Für Zugriff aus dem LAN: WEB_BIND=0.0.0.0
WEB_PORT=8080
WEB_BIND=127.0.0.1

# Wie lange ein Handy angemeldet bleibt, in Tagen.
SESSION_DAYS=90

# Interaktive API-Doku. Auf einem öffentlichen Server aus lassen.
DOCS_ENABLED=false

# Cloudflare Tunnel -- siehe README.
CLOUDFLARE_TUNNEL_TOKEN=
INNER
    ok ".env angelegt mit frischen Zufallswerten (Rechte 600)"
fi

# --- 3. Freien Port suchen -------------------------------------------------

say "3/5  Port"

port_busy() {
    # Erfolgreicher Verbindungsaufbau heißt: da lauscht schon jemand.
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3>&- && return 0
    return 1
}

WEB_PORT="$(grep -E '^WEB_PORT=' .env | tail -1 | cut -d= -f2- | tr -d ' \r')"
WEB_PORT="${WEB_PORT:-8080}"

# Läuft die App selbst schon auf dem Port? Dann ist er nicht "belegt".
OURS="$($DC ps --format '{{.Service}}' 2>/dev/null | grep -c '^web$' || true)"

if [ "$OURS" -eq 0 ] && port_busy "$WEB_PORT"; then
    warn "Port $WEB_PORT ist belegt, suche einen freien"
    NEW_PORT=""
    for candidate in $(seq $((WEB_PORT + 1)) $((WEB_PORT + 40))); do
        if ! port_busy "$candidate"; then NEW_PORT="$candidate"; break; fi
    done
    [ -n "$NEW_PORT" ] || die "Kein freier Port zwischen $((WEB_PORT+1)) und $((WEB_PORT+40)) gefunden."
    # In der .env festschreiben, damit der Port über Neustarts stabil bleibt.
    if grep -qE '^WEB_PORT=' .env; then
        sed -i.bak "s/^WEB_PORT=.*/WEB_PORT=$NEW_PORT/" .env && rm -f .env.bak
    else
        printf 'WEB_PORT=%s\n' "$NEW_PORT" >> .env
    fi
    WEB_PORT="$NEW_PORT"
    ok "Nutze stattdessen Port $WEB_PORT (in .env eingetragen)"
elif [ "$OURS" -gt 0 ]; then
    ok "TripCost läuft bereits auf Port $WEB_PORT, wird aktualisiert"
else
    ok "Port $WEB_PORT ist frei"
fi

# --- 4. Bauen und starten --------------------------------------------------

say "4/5  Images bauen und starten (beim ersten Mal dauert das ein paar Minuten)"

if ! $DC up -d --build; then
    printf '\n'
    die \
"Der Start ist fehlgeschlagen. Die letzten Zeilen oben sagen meist warum.

  Häufigste Ursache auf kleinen Servern: zu wenig Arbeitsspeicher beim
  Bauen des Frontends. Prüfen mit 'free -m'; unter ~1 GB frei hilft
  temporärer Swap:
    sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
    sudo mkswap /swapfile && sudo swapon /swapfile

  Vollständige Logs:  $DC logs"
fi

# --- 5. Warten, bis die App wirklich antwortet -----------------------------

say "5/5  Warten, bis die App antwortet"

DEADLINE=$(( $(date +%s) + 180 ))
while :; do
    STATUS="$(docker inspect --format '{{.State.Health.Status}}' \
        "$($DC ps -q api 2>/dev/null)" 2>/dev/null || echo starting)"

    case "$STATUS" in
        healthy) ok "API läuft"; break ;;
        unhealthy)
            printf '\n'
            $DC logs --tail 25 api
            die "Die API ist nicht hochgekommen -- Logs siehe oben."
            ;;
    esac

    if [ "$(date +%s)" -ge "$DEADLINE" ]; then
        printf '\n'
        $DC logs --tail 25 api
        die "Zeitüberschreitung nach 3 Minuten. Logs siehe oben."
    fi
    printf '.'
    sleep 3
done

if command -v curl >/dev/null 2>&1; then
    CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$WEB_PORT/" || echo 000)"
    [ "$CODE" = "200" ] && ok "Weboberfläche antwortet" || warn "Weboberfläche antwortet mit HTTP $CODE"
fi

BIND="$(grep -E '^WEB_BIND=' .env | tail -1 | cut -d= -f2- | tr -d ' \r')"

cat <<DONE

  ────────────────────────────────────────────────────────
   TripCost läuft.

   Im Browser:  http://localhost:$WEB_PORT
DONE
if [ "${BIND:-127.0.0.1}" = "127.0.0.1" ]; then
cat <<DONE
   Der Port ist absichtlich nur lokal erreichbar. Von außen
   kommst du über den Cloudflare Tunnel dran (siehe README),
   für Zugriff aus dem LAN: WEB_BIND=0.0.0.0 in der .env.
DONE
fi
cat <<DONE

   Stoppen:     $DC down
   Logs:        $DC logs -f
  ────────────────────────────────────────────────────────

DONE
