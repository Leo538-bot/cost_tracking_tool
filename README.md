# TripCost

Gemeinsame Urlaubskosten erfassen, Kassenzettel ablegen und am Ende in möglichst
wenigen Überweisungen ausgleichen — wie Splitwise, aber auf deinem eigenen Server.

Läuft komplett in Docker: PostgreSQL, eine FastAPI-Anwendung und ein nginx, das
die Web-App ausliefert. Optional hängt ein Cloudflare Tunnel dran, damit deine
Freunde von unterwegs draufkommen.

---

## Schnellstart

```bash
git clone <dieses-repo>
cd cost_tracking_tool

cp .env.example .env
# Die beiden Pflichtwerte erzeugen:
echo "POSTGRES_PASSWORD=$(openssl rand -base64 32)" >> .env
echo "JWT_SECRET=$(openssl rand -base64 32)"        >> .env
# ... und die Platzhalterzeilen in .env wieder löschen.

docker compose up -d --build
```

Danach im Browser: **http://localhost:8080**

Auf „Neue Reise" tippen, Name und Gruppen-Passwort festlegen — fertig. Du bist
Admin dieser Reise.

Stoppen mit `docker compose down`. Die Daten bleiben in den Volumes
(`docker compose down -v` löscht sie wirklich).

---

## Wie deine Freunde reinkommen

Es gibt **ein gemeinsames Gruppen-Passwort** pro Reise. Das gibst du weiter —
über WhatsApp, persönlich, wie du magst. Deine Freunde öffnen die Seite, tippen
auf „Beitreten" und geben drei Dinge ein:

1. das **Reise-Kürzel** (steht bei dir unter „Gruppe", z. B. `mallorca-2026`)
2. ihren **Namen**
3. das **Gruppen-Passwort**

Danach bleibt das Handy angemeldet (standardmäßig 90 Tage) — kein erneutes
Einloggen bei jeder Ausgabe.

### Warum trotzdem niemand fremde Kosten eintragen kann

Ein gemeinsames Passwort allein sagt nicht, *wer* gerade tippt. Deshalb sind
zwei Sperren eingebaut:

**Namen gehören zu einem Gerät.** Wer sich zuerst als „Anna" anmeldet, bekommt
den Namen — inklusive einer Geräte-Kennung, die im Handy gespeichert wird. Meldet
sich später jemand anderes mit demselben Passwort als „Anna" an, wird das
abgelehnt. Niemand kann sich als jemand anderes ausgeben.

**Jede Änderung wird protokolliert.** Zu jeder Ausgabe ist gespeichert, wer sie
eingetragen hat und von welchem Gerät. Unter „Gruppe → Letzte Aktivitäten" siehst
du das komplett. Ändern oder löschen darf jeder nur die eigenen Einträge — außer
dir als Admin.

**Bei verlorenem oder neuem Handy:** Du als Admin gehst auf „Gruppe → Mitglieder"
und tippst bei der Person auf „Freigeben". Der Name wird frei, das alte Gerät
verliert den Zugang, und das neue Handy kann sich normal anmelden.

**Wenn jemand die Gruppe verlässt:** Unter „Gruppe → Gruppen-Passwort ändern"
setzt du ein neues Passwort. Alle bereits angemeldeten Handys bleiben angemeldet
— nur neue Anmeldungen brauchen das neue Passwort.

Falsche Passwörter sind auf 10 Versuche pro Viertelstunde und IP begrenzt, damit
das Passwort nicht durchprobiert werden kann.

---

## Was die App kann

**Ausgaben** — Betrag, wer bezahlt hat, wer mitzahlt, Datum, Kategorie. Drei
Aufteilungen stehen zur Wahl:

| Aufteilung | wofür |
|---|---|
| Gleichmäßig | der Normalfall — Restcent wird verteilt, nie verschluckt |
| Genaue Beträge | jeder hat etwas anderes bestellt |
| Nach Anteilen | ein Paar zahlt doppelt, jemand war nur halb dabei |

Bei 100 € auf drei Personen kommt **33,33 / 33,33 / 33,34** heraus — die Summe
stimmt immer exakt. Intern rechnet alles in Cent, es gibt keine Fließkomma-Fehler.

**Kassenzettel** — auf „Beleg" tippen, das Handy öffnet direkt die Kamera. Das
Bild wird serverseitig auf max. 2000 px verkleinert und als JPEG gespeichert; ein
4000×3000-Foto schrumpft dabei typisch von ~190 KB auf ~18 KB. Dabei werden alle
EXIF-Daten entfernt — **inklusive der GPS-Koordinaten**, die Handykameras sonst
mitspeichern. Belege sind nur für Mitglieder derselben Reise abrufbar.

**Salden & Ausgleich** — wer hat wie viel ausgelegt, wer schuldet wem. Daraus
berechnet die App die kürzeste Liste an Zahlungen (höchstens *n−1* statt jeder
mit jedem). Rückzahlungen trägst du mit einem Tipp ein.

---

## Öffentlich erreichbar machen (Cloudflare Tunnel)

Damit kommen deine Freunde von überall dran, ohne dass du einen Port im Router
öffnest. Der Tunnel baut die Verbindung von innen nach außen auf.

1. In Cloudflare **Zero Trust → Networks → Tunnels → Create a tunnel** anlegen.
2. Als Public Hostname deine Domain wählen und als Service **`http://web:80`**
   eintragen (nicht `localhost` — das ist der Container-Name im Compose-Netz).
3. Das angezeigte Token in die `.env` schreiben:

   ```
   CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoi...
   ```

4. Starten mit aktiviertem Profil:

   ```bash
   docker compose --profile tunnel up -d
   ```

Ohne `--profile tunnel` startet der Tunnel nicht — die App läuft dann nur lokal.

Cloudflare übernimmt dabei HTTPS. Wenn die App öffentlich erreichbar ist, ist das
Gruppen-Passwort die Hürde nach außen: nimm dann bitte ein längeres (drei, vier
zufällige Wörter reichen völlig) und nicht den Namen der Reise.

---

## Aufbau

```
├── docker-compose.yml     db + api + web (+ optional tunnel)
├── .env.example           Vorlage für die Konfiguration
├── backend/               FastAPI + SQLAlchemy + Pillow
│   ├── app/
│   │   ├── models.py      Datenbank-Tabellen
│   │   ├── splitting.py   Aufteilung & Schulden-Vereinfachung
│   │   ├── storage.py     Bildverarbeitung der Kassenzettel
│   │   ├── security.py    Passwort-Hashing (bcrypt) und Tokens
│   │   └── routers/       API-Endpunkte
│   └── tests/             84 Tests
└── frontend/              React + TypeScript, mobil zuerst
```

### Datenmodell

| Tabelle | Inhalt |
|---|---|
| `groups` | eine Reise, mit gehashtem Gruppen-Passwort und Währung |
| `members` | Teilnehmer, mit Gerätebindung und Admin-Flag |
| `expenses` | eine Ausgabe: Betrag in Cent, Zahler, Kategorie, Datum |
| `expense_shares` | wer von einer Ausgabe wie viel trägt |
| `receipts` | hochgeladene Belege (Dateien liegen im Volume, nicht in der DB) |
| `settlements` | echte Rückzahlungen zwischen zwei Personen |
| `audit_logs` | wer hat was wann von welchem Gerät geändert |

Das Schema wird beim ersten Start automatisch angelegt.

### Speicherorte

- `db_data` — die PostgreSQL-Datenbank
- `receipts` — die Beleg-Fotos

Ein Backup umfasst beide:

```bash
docker compose exec db pg_dump -U tripcost tripcost > backup.sql
docker run --rm -v cost_tracking_tool_receipts:/data -v "$PWD":/out \
  alpine tar czf /out/receipts.tar.gz -C /data .
```

---

## Entwicklung

```bash
# Backend-Tests
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q          # 84 Tests

# Frontend mit Hot Reload (API muss über Docker laufen)
cd frontend
npm install
npm run dev                            # http://localhost:5173
```

Die API-Dokumentation erzeugt FastAPI selbst: http://localhost:8080/docs

---

## Konfiguration

Alles über `.env` (Vorlage: `.env.example`):

| Variable | Standard | Bedeutung |
|---|---|---|
| `POSTGRES_PASSWORD` | — | **Pflicht.** Datenbank-Passwort, nur intern genutzt |
| `JWT_SECRET` | — | **Pflicht.** Signiert die Anmelde-Tokens |
| `WEB_PORT` | `8080` | Port, unter dem die App erreichbar ist |
| `SESSION_DAYS` | `90` | wie lange ein Handy angemeldet bleibt |
| `CORS_ORIGINS` | `http://localhost:8080` | nur für getrenntes Frontend nötig |
| `CLOUDFLARE_TUNNEL_TOKEN` | leer | siehe Abschnitt oben |

Änderst du `JWT_SECRET` nachträglich, müssen sich alle einmal neu anmelden.

### Sicherheit in Kurzform

- Gruppen-Passwörter liegen als bcrypt-Hash in der Datenbank, nie im Klartext.
- Anmelde-Tokens sind an ein Gerät gebunden; „Freigeben" entwertet das alte.
- Die Datenbank ist nicht nach außen freigegeben, nur die API erreicht sie.
- Der API-Container läuft als normaler Benutzer, nicht als root.
- Uploads werden neu kodiert statt durchgereicht — was kein Bild ist, fliegt raus.
- Jede Anfrage ist auf die eigene Reise beschränkt; fremde IDs werden abgewiesen.
