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
