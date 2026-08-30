FROM node:20-alpine AS build

WORKDIR /app

# Less network chatter during install, and a hard heap ceiling: on a small
# server an unbounded node gets killed by the OOM killer, which surfaces as a
# confusing "Exit handler never called" instead of a real error message.
ENV NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NODE_OPTIONS=--max-old-space-size=512

COPY package.json package-lock.json* ./
# `npm ci` needs a lockfile; fall back to install so a fresh clone still builds.
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

# npm can exit 0 after an install that did not finish. Catch that here, rather
# than two layers later as an unexplained "sh: tsc: not found".
RUN test -x node_modules/.bin/tsc || { \
        echo "-----------------------------------------------------------"; \
        echo "Abhaengigkeiten wurden nicht vollstaendig installiert."; \
        echo "Haeufigste Ursache: zu wenig Arbeitsspeicher."; \
        echo "Pruefe 'free -m' und lege ggf. Swap an - siehe README."; \
        echo "-----------------------------------------------------------"; \
        exit 1; \
    }

COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build


FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost/ >/dev/null || exit 1
