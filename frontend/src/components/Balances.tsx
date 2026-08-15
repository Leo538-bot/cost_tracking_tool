import { useState } from 'react';

import { BalanceSummary, Member, SessionMember, Settlement, Transfer, api } from '../lib/api';
import { formatDateTime, formatMoney, initials, parseMoneyToCents } from '../lib/format';
import Sheet from './Sheet';

interface Props {
  summary: BalanceSummary;
  settlements: Settlement[];
  members: Member[];
  me: SessionMember;
  onChanged: () => void;
}

export default function Balances({ summary, settlements, members, me, onChanged }: Props) {
  const [payback, setPayback] = useState<Transfer | null>(null);
  const [manual, setManual] = useState(false);

  const currency = summary.currency;
  const mine = summary.balances.find((b) => b.member_id === me.id);
  const maxAbs = Math.max(1, ...summary.balances.map((b) => Math.abs(b.net_cents)));

  return (
    <>
      <div className="card">
        <div className="hero">
          <span className="label">Gesamtausgaben</span>
          <span className="value">{formatMoney(summary.total_spent_cents, currency)}</span>
          {mine && (
            <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>
              {mine.net_cents === 0
                ? 'Du bist ausgeglichen.'
                : mine.net_cents > 0
                  ? `Du bekommst ${formatMoney(mine.net_cents, currency)} zurück.`
                  : `Du schuldest ${formatMoney(-mine.net_cents, currency)}.`}
            </span>
          )}
        </div>
      </div>

      <p className="section-title">Wer steht wie da</p>
      <div className="card tight">
        <div className="list">
          {summary.balances.map((balance) => (
            <div key={balance.member_id} className="list-item" style={{ cursor: 'default' }}>
              <span className="avatar" style={{ background: balance.color }} aria-hidden="true">
                {initials(balance.display_name)}
              </span>
              <span className="body">
                <span className="title">
                  {balance.display_name}
                  {balance.member_id === me.id && <span className="badge"> du</span>}
                </span>
                <span className="meta">
                  bezahlt {formatMoney(balance.paid_cents, currency)} · Anteil{' '}
                  {formatMoney(balance.share_cents, currency)}
                </span>
                <span className="bar">
                  <span
                    style={{
                      width: `${(Math.abs(balance.net_cents) / maxAbs) * 100}%`,
                      background: balance.net_cents >= 0 ? 'var(--positive)' : 'var(--negative)',
                    }}
                  />
                </span>
              </span>
              <span className="trailing">
                <span className={`amount ${balance.net_cents >= 0 ? 'pos' : 'neg'}`}>
                  {balance.net_cents > 0 ? '+' : ''}
                  {formatMoney(balance.net_cents, currency)}
                </span>
              </span>
            </div>
          ))}
        </div>
      </div>

      <p className="section-title">Ausgleich</p>
      {summary.suggested_transfers.length === 0 ? (
        <div className="card empty" style={{ padding: '28px 20px' }}>
          <span className="big" aria-hidden="true">
            ✅
          </span>
          Alles ausgeglichen.
        </div>
      ) : (
        <div className="card tight">
          <div className="list">
            {summary.suggested_transfers.map((transfer, index) => (
              <button
                key={`${transfer.from_member_id}-${transfer.to_member_id}-${index}`}
                type="button"
                className="list-item"
                onClick={() => setPayback(transfer)}
              >
                <span className="icon" aria-hidden="true">
                  💸
                </span>
                <span className="body">
                  <span className="title">
                    {transfer.from_name} → {transfer.to_name}
                  </span>
                  <span className="meta">Tippen, wenn bezahlt wurde</span>
                </span>
                <span className="trailing">
                  <span className="amount">{formatMoney(transfer.amount_cents, currency)}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      <button type="button" className="btn secondary" onClick={() => setManual(true)}>
        Rückzahlung eintragen
      </button>

      {settlements.length > 0 && (
        <>
          <p className="section-title">Bereits zurückgezahlt</p>
          <div className="card tight">
            <div className="list">
              {settlements.map((settlement) => (
                <div key={settlement.id} className="list-item" style={{ cursor: 'default' }}>
                  <span className="body">
                    <span className="title">
                      {settlement.from_name} → {settlement.to_name}
                    </span>
                    <span className="meta">
                      {formatDateTime(settlement.created_at)}
                      {settlement.note ? ` · ${settlement.note}` : ''}
                    </span>
                  </span>
                  <span className="trailing">
                    <span className="amount">
                      {formatMoney(settlement.amount_cents, currency)}
                    </span>
                    {me.is_admin && (
                      <button
                        type="button"
                        className="btn danger slim"
                        style={{ marginTop: 4 }}
                        onClick={async () => {
                          if (!confirm('Rückzahlung löschen?')) return;
                          await api.deleteSettlement(settlement.id);
                          onChanged();
                        }}
                      >
                        Löschen
                      </button>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {(payback || manual) && (
        <SettlementSheet
          members={members}
          me={me}
          currency={currency}
          prefill={payback}
          onClose={() => {
            setPayback(null);
            setManual(false);
          }}
          onSaved={onChanged}
        />
      )}
    </>
  );
}

function SettlementSheet({
  members,
  me,
  currency,
  prefill,
  onClose,
  onSaved,
}: {
  members: Member[];
  me: SessionMember;
  currency: string;
  prefill: Transfer | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [from, setFrom] = useState(prefill?.from_member_id ?? me.id);
  const [to, setTo] = useState(
    prefill?.to_member_id ?? members.find((m) => m.id !== me.id)?.id ?? me.id,
  );
  const [amount, setAmount] = useState(
    prefill ? (prefill.amount_cents / 100).toFixed(2).replace('.', ',') : '',
  );
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cents = parseMoneyToCents(amount);

  async function save() {
    if (!cents) {
      setError('Bitte einen gültigen Betrag angeben.');
      return;
    }
    if (from === to) {
      setError('Sender und Empfänger müssen unterschiedlich sein.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.createSettlement({
        from_member_id: from,
        to_member_id: to,
        amount_cents: cents,
        note: note.trim() || null,
      });
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Speichern fehlgeschlagen.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet title="Rückzahlung eintragen" onClose={onClose}>
      <div className="card" style={{ marginBottom: 14 }}>
        <div className="field amount-input">
          <input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0,00"
            inputMode="decimal"
            aria-label={`Betrag in ${currency}`}
            autoFocus
          />
        </div>
        <div className="row">
          <div className="field">
            <label htmlFor="from">Von</label>
            <select id="from" value={from} onChange={(e) => setFrom(e.target.value)}>
              {members.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="to">An</label>
            <select id="to" value={to} onChange={(e) => setTo(e.target.value)}>
              {members.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.display_name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label htmlFor="settle-note">Notiz (optional)</label>
          <input
            id="settle-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="bar am Flughafen"
            maxLength={200}
          />
        </div>
      </div>

      {error && (
        <div className="alert" role="alert" style={{ marginBottom: 14 }}>
          {error}
        </div>
      )}

      <button type="button" className="btn" onClick={save} disabled={busy}>
        {busy && <span className="spinner" aria-hidden="true" />}
        Eintragen
      </button>
    </Sheet>
  );
}
