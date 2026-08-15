import { FormEvent, useState } from 'react';

import { ApiError, Session, api, storage } from '../lib/api';

interface Props {
  onAuthenticated: (session: Session) => void;
}

export default function Login({ onAuthenticated }: Props) {
  const [mode, setMode] = useState<'join' | 'create'>(storage.lastSlug ? 'join' : 'create');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [slug, setSlug] = useState(storage.lastSlug ?? '');
  const [name, setName] = useState(storage.lastName ?? '');
  const [password, setPassword] = useState('');
  const [tripName, setTripName] = useState('');
  const [currency, setCurrency] = useState('EUR');

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const session =
        mode === 'create'
          ? await api.createGroup({
              name: tripName.trim(),
              password,
              currency,
              admin_name: name.trim(),
            })
          : await api.login({
              group_slug: slug.trim().toLowerCase(),
              password,
              display_name: name.trim(),
              // Proves this phone already owns the name it is asking for.
              device_id: storage.deviceId,
            });

      storage.token = session.access_token;
      storage.deviceId = session.device_id;
      storage.lastSlug = session.group.slug;
      storage.lastName = session.member.display_name;
      onAuthenticated(session);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unerwarteter Fehler.');
    } finally {
      setBusy(false);
    }
  }

  const canSubmit =
    name.trim().length > 0 &&
    password.length >= (mode === 'create' ? 8 : 1) &&
    (mode === 'create' ? tripName.trim().length >= 2 : slug.trim().length > 0);

  return (
    <div className="auth">
      <div className="brand">
        <div className="logo" aria-hidden="true">
          🧾
        </div>
        <h1>TripCost</h1>
        <p>Urlaubskosten teilen, ohne Zettelwirtschaft.</p>
      </div>

      <div className="switcher" role="group" aria-label="Anmeldeart">
        <button type="button" aria-pressed={mode === 'join'} onClick={() => setMode('join')}>
          Beitreten
        </button>
        <button type="button" aria-pressed={mode === 'create'} onClick={() => setMode('create')}>
          Neue Reise
        </button>
      </div>

      <form className="card" onSubmit={submit}>
        {mode === 'create' ? (
          <>
            <div className="field">
              <label htmlFor="trip">Name der Reise</label>
              <input
                id="trip"
                value={tripName}
                onChange={(e) => setTripName(e.target.value)}
                placeholder="Mallorca 2026"
                autoComplete="off"
                required
              />
            </div>
            <div className="field">
              <label htmlFor="currency">Währung</label>
              <select
                id="currency"
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
              >
                <option value="EUR">Euro (€)</option>
                <option value="CHF">Schweizer Franken</option>
                <option value="USD">US-Dollar</option>
                <option value="GBP">Britisches Pfund</option>
                <option value="SEK">Schwedische Krone</option>
                <option value="DKK">Dänische Krone</option>
                <option value="PLN">Polnischer Złoty</option>
                <option value="CZK">Tschechische Krone</option>
              </select>
            </div>
          </>
        ) : (
          <div className="field">
            <label htmlFor="slug">Reise-Kürzel</label>
            <input
              id="slug"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="mallorca-2026"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              required
            />
            <span className="hint">Steht in dem Link, den du bekommen hast.</span>
          </div>
        )}

        <div className="field">
          <label htmlFor="name">Dein Name</label>
          <input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Leo"
            autoComplete="nickname"
            required
          />
          {mode === 'join' && (
            <span className="hint">
              Der Name gehört danach zu diesem Gerät — niemand sonst kann ihn nutzen.
            </span>
          )}
        </div>

        <div className="field">
          <label htmlFor="password">
            {mode === 'create' ? 'Gruppen-Passwort festlegen' : 'Gruppen-Passwort'}
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === 'create' ? 'new-password' : 'current-password'}
            required
          />
          {mode === 'create' && (
            <span className="hint">
              Mindestens 8 Zeichen. Dieses Passwort gibst du deinen Freunden weiter.
            </span>
          )}
        </div>

        {error && (
          <div className="alert" role="alert" style={{ marginBottom: 14 }}>
            {error}
          </div>
        )}

        <button className="btn" type="submit" disabled={!canSubmit || busy}>
          {busy && <span className="spinner" aria-hidden="true" />}
          {mode === 'create' ? 'Reise anlegen' : 'Beitreten'}
        </button>
      </form>
    </div>
  );
}
