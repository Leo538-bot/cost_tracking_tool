#!/usr/bin/env sh
# Erzeugt eine .env mit frischen Zufallswerten.
# Aufruf:  ./setup.sh
set -eu

cd "$(dirname "$0")"

if [ -e .env ]; then
    echo "FEHLER: .env existiert bereits."
    echo "Es wird nichts ueberschrieben -- sonst waeren deine bisherigen"
    echo "Zugangsdaten weg und alle muessten sich neu anmelden."
    echo
    echo "Wenn du wirklich neu anfangen willst:  mv .env .env.alt && ./setup.sh"
    exit 1
fi

# Zufall bevorzugt aus openssl, sonst direkt aus dem Kernel.
random_secret() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 32
    else
        head -c 32 /dev/urandom | base64
    fi
}

# .env enthaelt Geheimnisse -- nur fuer den Besitzer lesbar anlegen.
umask 077

cat > .env <<INNER
# Von setup.sh erzeugt. Diese Datei enthaelt Geheimnisse und gehoert
# nicht ins Git -- .gitignore schliesst sie bereits aus.

POSTGRES_PASSWORD=$(random_secret)
JWT_SECRET=$(random_secret)

POSTGRES_USER=tripcost
POSTGRES_DB=tripcost

# Port, unter dem die App im Browser erreichbar ist.
WEB_PORT=8080

# Wie lange ein Handy angemeldet bleibt, in Tagen.
SESSION_DAYS=90

# Interaktive API-Doku. Auf einem oeffentlichen Server aus lassen.
DOCS_ENABLED=false

# Cloudflare Tunnel: Token eintragen und mit
#   docker compose --profile tunnel up -d
# starten. Siehe README.
CLOUDFLARE_TUNNEL_TOKEN=
INNER

echo "OK: .env angelegt (Rechte: $(stat -c '%a' .env 2>/dev/null || stat -f '%Lp' .env))"
echo
echo "Weiter mit:"
echo "  docker compose up -d --build"
echo
echo "Danach im Browser:  http://localhost:${WEB_PORT:-8080}"
