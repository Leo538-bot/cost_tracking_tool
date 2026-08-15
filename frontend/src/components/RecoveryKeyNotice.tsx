import { useState } from 'react';

interface Props {
  recoveryKey: string;
  /** Creation shows a welcome framing, a rotation explains why the old key died. */
  reason: 'created' | 'rotated';
  onAcknowledge: () => void;
}

/**
 * Shown exactly once per issued key. The server only keeps a hash, so if this is
 * dismissed without writing the key down it is gone for good — hence the
 * deliberate friction of a confirmation checkbox.
 */
export default function RecoveryKeyNotice({ recoveryKey, reason, onAcknowledge }: Props) {
  const [copied, setCopied] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(recoveryKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard is blocked outside HTTPS; the key is on screen to copy by hand.
      setCopied(false);
    }
  }

  return (
    <div className="sheet-backdrop" role="dialog" aria-modal="true" aria-label="Notfall-Schlüssel">
      <div className="sheet">
        <div className="sheet-head">
          <h2>🔑 Dein Notfall-Schlüssel</h2>
        </div>

        <div className="card" style={{ marginBottom: 14 }}>
          <p style={{ marginTop: 0 }}>
            {reason === 'created'
              ? 'Bewahre diesen Schlüssel gut auf — am besten außerhalb deines Handys.'
              : 'Der alte Schlüssel ist ab sofort ungültig. Hier ist der neue.'}
          </p>

          <div
            className="copy-row"
            style={{ fontSize: 19, fontWeight: 700, letterSpacing: '0.08em', justifyContent: 'center' }}
          >
            {recoveryKey}
          </div>

          <button type="button" className="btn secondary" style={{ marginTop: 10 }} onClick={copy}>
            {copied ? '✓ Kopiert' : 'Schlüssel kopieren'}
          </button>
        </div>

        <div className="alert info" style={{ marginBottom: 14 }}>
          <strong>Wofür ist der gut?</strong>
          <p style={{ margin: '6px 0 0' }}>
            Wenn dein Handy verloren geht oder du die Browserdaten löschst, kommst du damit wieder
            unter deinem Namen rein — auch ohne dass dich jemand freigeben muss. Deine Ausgaben
            bleiben dabei erhalten.
          </p>
          <p style={{ margin: '8px 0 0' }}>
            Er wird <strong>nur dieses eine Mal angezeigt</strong>. Wir speichern ihn nicht im
            Klartext, wir können ihn dir also später nicht noch einmal zeigen.
          </p>
          <p style={{ margin: '8px 0 0' }}>
            Gib ihn <strong>niemandem</strong> — er ist stärker als das Gruppen-Passwort. Nicht
            verwechseln: das Gruppen-Passwort teilst du, diesen Schlüssel nie.
          </p>
        </div>

        <label
          className="chip"
          style={{ width: '100%', justifyContent: 'flex-start', marginBottom: 12, padding: 12 }}
        >
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            style={{ width: 18, height: 18, flex: 'none' }}
          />
          Ich habe den Schlüssel sicher notiert.
        </label>

        <button type="button" className="btn" disabled={!confirmed} onClick={onAcknowledge}>
          Weiter
        </button>
      </div>
    </div>
  );
}
