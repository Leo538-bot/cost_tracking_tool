import { useState } from 'react';

import { ActivityEntry, Group, Member, SessionMember, api } from '../lib/api';
import { formatDateTime, initials } from '../lib/format';

interface Props {
  group: Group;
  members: Member[];
  me: SessionMember;
  activity: ActivityEntry[];
  onChanged: () => void;
  onLogout: () => void;
  onRecoveryKeyIssued: (key: string) => void;
}

export default function Settings({
  group,
  members,
  me,
  activity,
  onChanged,
  onLogout,
  onRecoveryKeyIssued,
}: Props) {
  const [copied, setCopied] = useState(false);
  const [newPassword, setNewPassword] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const joinHint = `${window.location.origin} — Kürzel: ${group.slug}`;

  async function copyInvite() {
    try {
      await navigator.clipboard.writeText(joinHint);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError('Kopieren hat nicht geklappt — bitte manuell abtippen.');
    }
  }

  async function rotatePassword() {
    setError(null);
    setMessage(null);
    if (newPassword.length < 8) {
      setError('Das Passwort braucht mindestens 8 Zeichen.');
      return;
    }
    try {
      await api.changePassword(newPassword);
      setNewPassword('');
      setMessage('Passwort geändert. Angemeldete Geräte bleiben angemeldet.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ändern fehlgeschlagen.');
    }
  }

  async function release(member: Member) {
    if (
      !confirm(
        `Gerätebindung von ${member.display_name} aufheben? Das aktuelle Gerät wird abgemeldet.`,
      )
    )
      return;
    try {
      await api.releaseMember(member.id);
      setMessage(`${member.display_name} kann sich jetzt auf einem neuen Gerät anmelden.`);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Aktion fehlgeschlagen.');
    }
  }

  return (
    <>
      <div className="card">
        <p className="section-title" style={{ margin: 0 }}>
          Freunde einladen
        </p>
        <p className="hint" style={{ margin: '8px 0' }}>
          Freunde öffnen die Seite, tippen auf „Beitreten" und geben Kürzel, ihren Namen und das
          Gruppen-Passwort ein.
        </p>
        <div className="copy-row">{joinHint}</div>
        <button
          type="button"
          className="btn secondary"
          style={{ marginTop: 10 }}
          onClick={copyInvite}
        >
          {copied ? '✓ Kopiert' : 'Einladung kopieren'}
        </button>
      </div>

      <p className="section-title">Mitglieder</p>
      <div className="card tight">
        <div className="list">
          {members.map((member) => (
            <div key={member.id} className="list-item" style={{ cursor: 'default' }}>
              <span className="avatar" style={{ background: member.color }} aria-hidden="true">
                {initials(member.display_name)}
              </span>
              <span className="body">
                <span className="title">
                  {member.display_name}
                  {member.is_admin && <span className="badge"> Admin</span>}
                  {member.is_you && <span className="badge"> du</span>}
                </span>
                <span className="meta">
                  {member.device_bound ? 'an ein Gerät gebunden' : 'kein Gerät — frei zum Anmelden'}
                </span>
              </span>
              {me.is_admin && member.device_bound && (
                <button
                  type="button"
                  className="btn secondary slim"
                  onClick={() => release(member)}
                >
                  Freigeben
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
      {me.is_admin && (
        <p className="hint" style={{ margin: '-6px 2px 0', fontSize: 12.5 }}>
          „Freigeben" ist die Notlösung bei verlorenem oder neuem Handy: der Name wird frei und
          das alte Gerät verliert seinen Zugang.
        </p>
      )}

      {me.is_admin && (
        <>
          <p className="section-title">Gruppen-Passwort ändern</p>
          <div className="card">
            <div className="field" style={{ marginBottom: 10 }}>
              <label htmlFor="new-password">Neues Passwort</label>
              <input
                id="new-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
              />
              <span className="hint">
                Sinnvoll, wenn jemand die Gruppe verlässt. Bereits angemeldete Handys bleiben
                angemeldet.
              </span>
            </div>
            <button type="button" className="btn secondary" onClick={rotatePassword}>
              Passwort ändern
            </button>
          </div>
        </>
      )}

      {me.is_admin && (
        <>
          <p className="section-title">Notfall-Schlüssel</p>
          <div className="card">
            <p className="hint" style={{ margin: '0 0 10px' }}>
              Damit kommst du wieder rein, wenn dein Handy weg ist und dich niemand freigeben
              kann. Zettel verloren? Erzeuge einen neuen — der alte wird dabei ungültig.
            </p>
            <button
              type="button"
              className="btn secondary"
              onClick={async () => {
                if (!confirm('Neuen Notfall-Schlüssel erzeugen? Der alte gilt danach nicht mehr.'))
                  return;
                setError(null);
                try {
                  const { recovery_key } = await api.regenerateRecoveryKey();
                  onRecoveryKeyIssued(recovery_key);
                } catch (err) {
                  setError(err instanceof Error ? err.message : 'Erzeugen fehlgeschlagen.');
                }
              }}
            >
              Neuen Notfall-Schlüssel erzeugen
            </button>
          </div>
        </>
      )}

      {message && <div className="alert info">{message}</div>}
      {error && (
        <div className="alert" role="alert">
          {error}
        </div>
      )}

      <p className="section-title">Letzte Aktivitäten</p>
      <div className="card tight">
        {activity.length === 0 ? (
          <p className="center-note">Noch nichts passiert.</p>
        ) : (
          <div className="list">
            {activity.slice(0, 30).map((entry) => (
              <div key={entry.id} className="list-item" style={{ cursor: 'default' }}>
                <span className="body">
                  <span className="title" style={{ fontSize: 14, fontWeight: 500 }}>
                    {entry.summary ?? entry.action}
                  </span>
                  <span className="meta">
                    {entry.member_name ?? 'System'} · {formatDateTime(entry.created_at)}
                  </span>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <button type="button" className="btn secondary" onClick={onLogout}>
        Abmelden
      </button>
      <p className="center-note" style={{ paddingTop: 0 }}>
        Reise „{group.name}" · Kürzel {group.slug}
      </p>
    </>
  );
}
