#!/usr/bin/env bash
# Startet TripCost. Ein Kommando, alles inklusive:
#   ./start.sh            normal starten bzw. aktualisieren
#   ./start.sh --fresh    Container wegwerfen und ohne Cache neu bauen
#                         (Daten in den Volumes bleiben erhalten)
#
# Legt beim ersten Mal die .env mit Zufallswerten an, sucht einen freien Port,
# baut die Images und wartet, bis die App wirklich antwortet.
set -euo pipefail

cd "$(dirname "$0")"

FRESH=0
[ "${1:-}" = "--fresh" ] && FRESH=1

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

if [ "$FRESH" -eq 1 ]; then
    warn "--fresh: Container werden entfernt und ohne Cache neu gebaut"
    $DC down --remove-orphans >/dev/null 2>&1 || true
    $DC build --no-cache || die "Neubau fehlgeschlagen -- Meldung siehe oben."
else
    # Reste eines misslungenen Laufs wegräumen. Wichtig: ein Dienst, der beim
    # Start abbricht (nginx bei nicht auflösbarem Upstream etwa), landet auf
    # "exited" und nie auf "unhealthy" -- beide Fälle müssen weg, sonst bleibt
    # der alte Container liegen und meldet denselben Fehler weiter.
    for svc in web api db; do
        cid="$($DC ps -aq "$svc" 2>/dev/null || true)"
        [ -n "$cid" ] || continue
        running="$(docker inspect --format '{{.State.Running}}' "$cid" 2>/dev/null || echo false)"
        health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo none)"
        if [ "$running" != "true" ] || [ "$health" = "unhealthy" ]; then
            warn "$svc lag als ${health/none/gestoppt} herum, wird neu erzeugt"
            docker rm -f "$cid" >/dev/null 2>&1 || true
        fi
    done

    # Ein Container gleichen Namens, den Compose nicht kennt, blockiert `up`
    # mit einem Namenskonflikt. Der gehört zu einem früheren Versuch -- weg.
    for name in web api db; do
        cname="$(basename "$(pwd)" | tr '[:upper:]' '[:lower:]')-${name}-1"
        if docker inspect "$cname" >/dev/null 2>&1 && [ -z "$($DC ps -aq "$name" 2>/dev/null)" ]; then
            warn "Verwaister Container $cname wird entfernt"
            docker rm -f "$cname" >/dev/null 2>&1 || true
        fi
    done
fi

if ! $DC up -d --build; then
    printf '\n'
    die \
"Der Start ist fehlgeschlagen. Die letzten Zeilen oben sagen meist warum.

  Häufigste Ursache auf kleinen Servern: zu wenig Arbeitsspeicher beim
  Bauen des Frontends. Prüfen mit 'free -m'; unter ~1 GB frei hilft
  temporärer Swap:
    sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
    sudo mkswap /swapfile && sudo swapon /swapfile

  Steht oben ein Namenskonflikt ("container name is already in use"),
  liegt noch ein Container eines früheren Versuchs herum:
    docker compose down --remove-orphans
    ./start.sh

  Vollständige Logs:  $DC logs"
fi

# --- 5. Warten, bis die App wirklich antwortet -----------------------------

say "5/5  Warten, bis die App antwortet"

wait_healthy() {
    local svc="$1" deadline=$(( $(date +%s) + 180 )) cid status
    while :; do
        cid="$($DC ps -q "$svc" 2>/dev/null || true)"
        if [ -z "$cid" ]; then
            printf '\n'
            $DC logs --tail 30 "$svc" 2>/dev/null || true
            die "Der Container '$svc' läuft nicht -- Logs siehe oben."
        fi

        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo starting)"
        case "$status" in
            healthy|none) ok "$svc läuft"; return 0 ;;
            unhealthy)
                printf '\n'
                # Die Logs des Dienstes sagen fast immer direkt, was fehlt.
                $DC logs --tail 30 "$svc"
                die "'$svc' ist nicht gesund geworden -- Logs siehe oben."
                ;;
        esac

        if [ "$(date +%s)" -ge "$deadline" ]; then
            printf '\n'
            $DC logs --tail 30 "$svc"
            die "Zeitüberschreitung beim Warten auf '$svc'. Logs siehe oben."
        fi
        printf '.'
        sleep 3
    done
}

# Beide prüfen: eine gesunde API nützt nichts, wenn nginx davor nicht läuft.
wait_healthy api
wait_healthy web

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
