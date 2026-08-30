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
./start.sh
```

Das war's. Das Skript prüft die Voraussetzungen, legt beim ersten Mal eine
`.env` mit frisch gewürfelten Geheimnissen an, sucht sich einen freien Port,
baut die Images und wartet, bis die App wirklich antwortet. Am Ende steht die
Adresse da, unter der du sie erreichst.

Ein zweiter Aufruf ist ungefährlich: eine vorhandene `.env` bleibt unangetastet,
die App wird nur neu gebaut und aktualisiert.

```bash
docker compose down      # stoppen, Daten bleiben erhalten
docker compose logs -f   # zuschauen
docker compose down -v   # stoppen UND alle Daten löschen
```

Wer lieber selbst Hand anlegt, nimmt `.env.example` als Vorlage und startet mit
`docker compose up -d --build`.

### Wenn etwas klemmt

`./start.sh` erklärt die meisten Fälle schon selbst. Die drei häufigsten:

**„Permission denied" beim Schreiben.** Das Verzeichnis gehört nicht dir:

```bash
sudo chown -R "$USER":"$USER" .
```

Setz kein `sudo` vor `./start.sh`. Bei `sudo befehl > datei` schreibt nicht
`sudo`, sondern deine eigene Shell in die Datei — die Umleitung wird ausgewertet,
bevor `sudo` überhaupt startet. Die erhöhten Rechte helfen also nicht.

**„Cannot connect to the Docker daemon".** Entweder läuft er nicht, oder dein
Benutzer darf ihn nicht ansprechen:

```bash
sudo systemctl start docker
sudo usermod -aG docker "$USER"   # danach einmal ab- und wieder anmelden
```

**Der Frontend-Build bricht ab.** Auf kleinen Servern fehlt beim Bauen
schlicht der Arbeitsspeicher; das Bauen braucht kurzzeitig rund 1 GB. Prüf mit
`free -m` und leg bei Bedarf Swap an:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

Danach `./start.sh` erneut. (Dauerhaft wird der Swap mit einem Eintrag
`/swapfile none swap sw 0 0` in `/etc/fstab`.)

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
verliert den Zugang, und das neue Handy kann sich normal anmelden. Die bereits
eingetragenen Kosten bleiben dabei unverändert — es ist derselbe Mitglieds-
Datensatz, nur an ein neues Gerät gebunden.

Ist die Sitzung nur abgelaufen und das Handy noch dasselbe, braucht es gar
nichts: die Geräte-Kennung überlebt das Abmelden, die Person meldet sich einfach
wieder an.

**Wenn jemand die Gruppe verlässt:** Unter „Gruppe → Gruppen-Passwort ändern"
setzt du ein neues Passwort. Alle bereits angemeldeten Handys bleiben angemeldet
— nur neue Anmeldungen brauchen das neue Passwort.

Falsche Passwörter sind auf 10 Versuche pro Viertelstunde und IP begrenzt, damit
das Passwort nicht durchprobiert werden kann.

### Der Notfall-Schlüssel

Alles oben setzt voraus, dass ein Admin erreichbar ist. Wenn **dir** das Handy
abhandenkommt, kann dich niemand freigeben — dafür gibt es den Notfall-Schlüssel.

Beim Anlegen der Reise wird er einmalig angezeigt, in der Form
`R5F9-A4ZH-84TK-VMGH`. Notiere ihn irgendwo außerhalb deines Handys. Er wird nur
als Hash gespeichert, wir können ihn dir also später nicht noch einmal zeigen.

Wenn du ausgesperrt bist: auf dem Anmelde-Bildschirm „Neues Handy? Zugang
wiederherstellen" antippen und Name, Gruppen-Passwort **und** Notfall-Schlüssel
eingeben. Du bist sofort wieder unter deinem Namen drin, mit Admin-Rechten und
allen Kosten. Groß-/Kleinschreibung und Bindestriche sind egal.

Ein paar Eigenschaften, die dabei wichtig sind:

- **Beides nötig.** Der Schlüssel allein reicht nicht, das Gruppen-Passwort muss
  zusätzlich stimmen.
- **Einmal gültig.** Nach dem Einsatz ist der alte Schlüssel tot und du bekommst
  sofort einen neuen angezeigt. Ein Schlüssel, der mal in einem Chat gelandet ist,
  lässt sich nicht wiederverwenden.
- **Nur bestehende Namen.** Man kann damit keinen neuen Namen erfinden, nur einen
  vorhandenen zurückholen.
- **Streng gedrosselt.** 5 Versuche pro Stunde und IP, statt der 10 pro
  Viertelstunde beim normalen Passwort.
- **Sichtbar im Protokoll.** Jede Verwendung steht unter „Letzte Aktivitäten".

Zettel verloren? Unter „Gruppe → Notfall-Schlüssel" erzeugst du einen neuen; der
alte wird dabei ungültig.

> Der Schlüssel ist stärker als das Gruppen-Passwort — wer ihn hat, kommt als
> Admin rein. Das Gruppen-Passwort teilst du bewusst, den Notfall-Schlüssel nie.

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

Deine Freunde kommen damit von überall dran, ohne dass du einen Port im Router
öffnest. Der Tunnel baut die Verbindung von innen nach außen auf, HTTPS macht
Cloudflare.

### Erst testen, ohne Domain und ohne Konto

```bash
docker compose --profile tunnel-quick up -d
docker compose logs -f tunnel-quick
```

In den Logs steht eine zufällige Adresse `https://....trycloudflare.com` — die
funktioniert sofort. Damit prüfst du, ob alles läuft, bevor du DNS anfasst. Die
Adresse verfällt mit dem Container, also nichts für den Dauerbetrieb.

Beenden mit `docker compose --profile tunnel-quick down`.

### Dauerhaft, mit eigener Domain

Voraussetzung: Eine Domain, die bei Cloudflare liegt (Nameserver zeigen auf
Cloudflare). Ohne Domain geht nur der Schnelltest oben.

1. Im Cloudflare-Dashboard auf **Networking → Tunnels → Create a tunnel**.
   (Tunnel sind seit Anfang 2026 im Haupt-Dashboard, nicht mehr nur unter
   Zero Trust.)
2. Namen vergeben, **Create Tunnel**. Als Umgebung **Docker** wählen. Im
   angezeigten Installationsbefehl steckt der Token — der lange Wert hinter
   `--token`. Nur den kopieren, ohne `--token` davor.

   > **Nicht die Tunnel-ID nehmen.** Im Dashboard steht auch eine ID in der Form
   > `6ff42ae2-765d-4adf-8112-31c55c1551ef`. Die ist hier falsch; cloudflared
   > antwortet damit mit `Provided Tunnel token is not valid.` Der richtige Wert
   > ist deutlich länger (~150 Zeichen) und beginnt mit `eyJ`.

3. Token in die `.env` eintragen — die Zeile steht dort schon leer bereit:

   ```
   CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoi...
   ```

   Token verlegt? Im Dashboard beim Tunnel unter **Overview → Refresh token**
   gibt es einen neuen; der alte verfällt dabei.

4. Tunnel starten:

   ```bash
   docker compose --profile tunnel up -d
   ```

   Im Dashboard springt der Tunnel jetzt auf **HEALTHY**.

5. Zurück im Dashboard: Tunnel auswählen, Reiter **Routes** → **Add route** →
   **Published application**. Subdomain und Domain wählen, und als **Service
   URL** eintragen:

   ```
   http://web:80
   ```

   **Genau so.** Nicht `localhost`, nicht deine Server-IP — `web` ist der
   Container-Name im Compose-Netz, und nur den erreicht cloudflared. `localhost`
   wäre aus Sicht des Tunnel-Containers er selbst, und das schlägt fehl.

6. Speichern. Nach ein paar Sekunden ist die App unter deiner Adresse erreichbar.

### Läuft es?

```bash
docker compose --profile tunnel ps          # tunnel muss "Up" sein
docker compose --profile tunnel logs tunnel # "Registered tunnel connection"
curl -I https://deine-subdomain.deine-domain.de
```

### Ports

Standardmäßig lauscht die App **nur auf localhost** (`WEB_BIND=127.0.0.1`). Das
ist beim Tunnel genau richtig: cloudflared erreicht `web:80` über das
Docker-Netz, ein offener Port am Server wäre nur ein zweiter, unverschlüsselter
Weg an Cloudflare vorbei.

Ist `8080` bei dir belegt, trag in der `.env` einfach einen anderen ein:

```
WEB_PORT=8090
```

Wer die App zusätzlich im LAN erreichen will, setzt `WEB_BIND=0.0.0.0` — dann
aber ohne HTTPS und ohne den Schutz von Cloudflare.

### Wenn es öffentlich steht

- Nimm ein langes Gruppen-Passwort, drei oder vier zufällige Wörter.
- `DOCS_ENABLED=false` lassen.
- Den Notfall-Schlüssel weder ins Handy noch in den Gruppenchat.

Optional kannst du in Cloudflare zusätzlich eine WAF-Rate-Limit-Regel auf
`/api/auth/login` legen. Die App drosselt selbst schon pro Absender-Adresse,
aber dann filtert Cloudflare den Müll ab, bevor er deinen Server erreicht.

---

## Aufbau

```
├── docker-compose.yml     db + api + web (+ optional tunnel)
├── start.sh               ein Kommando: .env anlegen, bauen, starten
├── .env.example           Vorlage für die Konfiguration
├── backend/               FastAPI + SQLAlchemy + Pillow
│   ├── app/
│   │   ├── models.py      Datenbank-Tabellen
│   │   ├── splitting.py   Aufteilung & Schulden-Vereinfachung
│   │   ├── storage.py     Bildverarbeitung der Kassenzettel
│   │   ├── security.py    Passwort-Hashing (bcrypt) und Tokens
│   │   └── routers/       API-Endpunkte
│   └── tests/             104 Tests
└── frontend/              React + TypeScript, mobil zuerst
```

### Datenmodell

| Tabelle | Inhalt |
|---|---|
| `groups` | eine Reise, mit gehashtem Gruppen-Passwort, Notfall-Schlüssel und Währung |
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
.venv/bin/python -m pytest -q          # 104 Tests

# Frontend mit Hot Reload (API muss über Docker laufen)
cd frontend
npm install
npm run dev                            # http://localhost:5173
```

Die API-Doku ist standardmäßig **aus**, weil sie einem Scanner sämtliche
Endpunkte auflistet. Zum Entwickeln in der `.env` `DOCS_ENABLED=true` setzen —
erreichbar ist sie dann direkt an der API, nicht über Port 8080 (nginx leitet
dorthin nur `/api/` weiter).

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

## Sicherheit

Der Stack wurde gegen einen Angriffskatalog geprüft — Auth-Umgehung, fremde
Datenzugriffe, Einschleusung, bösartige Uploads, offene Ports. Was eingebaut ist:

**Anmeldung und Sitzungen**
- Gruppen-Passwörter und Notfall-Schlüssel liegen als bcrypt-Hash in der
  Datenbank, nie im Klartext.
- Anmelde-Tokens sind signiert und an ein Gerät gebunden; „Freigeben" entwertet
  das alte sofort. Manipulierte Tokens und der `alg=none`-Trick werden abgewiesen.
- Die App **startet nicht**, wenn `JWT_SECRET` fehlt, noch der eingebaute
  Standard ist oder unter 32 Zeichen liegt — sonst könnte jeder Sitzungen fälschen.
- Anmeldeversuche sind pro Absender-Adresse begrenzt (10 pro Viertelstunde,
  5 pro Stunde für den Notfall-Schlüssel). Ein Angreifer sperrt damit nur sich
  selbst aus, nicht die Gruppe.

**Daten**
- Jede Anfrage ist auf die eigene Reise beschränkt. Fremde IDs liefern 404 —
  auch für Ausgaben, Belege, Rückzahlungen und Mitglieder.
- Alle Datenbankzugriffe laufen über das ORM, ohne zusammengebaute SQL-Strings.
- Fehlermeldungen beim Login unterscheiden nicht zwischen „Reise gibt es nicht"
  und „Passwort falsch", damit sich keine Reisen aufspüren lassen.

**Uploads**
- Bilder werden aus rohen Pixeln neu kodiert, nicht durchgereicht. Getarnte
  Skripte, SVGs und Nicht-Bilder werden abgelehnt, EXIF/GPS fällt weg.
- Größe (12 MB) und Pixelzahl sind begrenzt, gegen Dekomprimierungs-Bomben.
- Dateinamen kommen vom Server, nie vom Client.

**Betrieb**
- Datenbank und API sind nicht nach außen freigegeben; nur nginx ist erreichbar.
- Der API-Container läuft als normaler Benutzer, nicht als root.
- Sicherheits-Header inklusive Content-Security-Policy, die externe Skripte
  komplett ausschließt; nginx nennt seine Version nicht.
- Abhängigkeiten sind auf dem Stand ohne bekannte Schwachstellen
  (`pip-audit` und `npm audit` sauber).

**Prüf das selbst nach:**

```bash
cd backend && .venv/bin/pip install pip-audit && .venv/bin/pip-audit
cd frontend && npm audit --omit=dev
```

### Wenn die App öffentlich erreichbar ist

- Nimm ein langes Gruppen-Passwort — drei, vier zufällige Wörter.
- Lass `DOCS_ENABLED=false`.
- Halte die Abhängigkeiten aktuell; ein `docker compose build --pull` alle paar
  Monate genügt für eine Urlaubsgruppe.
- Der Notfall-Schlüssel gehört nicht ins Handy und nicht in den Gruppenchat.
