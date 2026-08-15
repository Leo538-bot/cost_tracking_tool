import { FormEvent, useMemo, useState } from 'react';

import { ApiError, Expense, Member, Receipt, SessionMember, api } from '../lib/api';
import { CATEGORIES, formatMoney, formatMoneyPlain, parseMoneyToCents, today } from '../lib/format';
import Receipts from './Receipts';
import Sheet from './Sheet';

type SplitType = 'equal' | 'exact' | 'shares';

interface Props {
  members: Member[];
  me: SessionMember;
  currency: string;
  expense: Expense | null;
  onClose: () => void;
  onSaved: () => void;
}

export default function ExpenseSheet({
  members,
  me,
  currency,
  expense,
  onClose,
  onSaved,
}: Props) {
  const isEdit = expense !== null;

  const [description, setDescription] = useState(expense?.description ?? '');
  const [amount, setAmount] = useState(
    expense ? formatMoneyPlain(expense.amount_cents) : '',
  );
  const [payerId, setPayerId] = useState(expense?.payer_id ?? me.id);
  const [date, setDate] = useState(expense?.expense_date ?? today());
  const [category, setCategory] = useState(expense?.category ?? 'other');
  const [note, setNote] = useState(expense?.note ?? '');
  const [splitType, setSplitType] = useState<SplitType>(expense?.split_type ?? 'equal');

  const [participants, setParticipants] = useState<string[]>(
    expense ? expense.shares.map((s) => s.member_id) : members.map((m) => m.id),
  );
  const [exactValues, setExactValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      (expense?.shares ?? []).map((s) => [s.member_id, formatMoneyPlain(s.amount_cents)]),
    ),
  );
  const [weights, setWeights] = useState<Record<string, string>>(() =>
    Object.fromEntries((expense?.shares ?? []).map((s) => [s.member_id, String(s.weight)])),
  );

  const [receipts, setReceipts] = useState<Receipt[]>(expense?.receipts ?? []);
  // For a brand-new expense there is no id yet, so photos wait here until it is saved.
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const amountCents = parseMoneyToCents(amount);

  const exactTotal = useMemo(
    () =>
      participants.reduce((sum, id) => sum + (parseMoneyToCents(exactValues[id] ?? '') ?? 0), 0),
    [participants, exactValues],
  );

  const preview = useMemo(() => {
    if (!amountCents || participants.length === 0) return null;
    if (splitType === 'equal') {
      const base = Math.floor(amountCents / participants.length);
      const rest = amountCents % participants.length;
      return participants.map((id, i) => ({ id, cents: base + (i < rest ? 1 : 0) }));
    }
    if (splitType === 'shares') {
      const totalWeight = participants.reduce(
        (sum, id) => sum + Math.max(0, Number(weights[id] ?? '1') || 0),
        0,
      );
      if (totalWeight <= 0) return null;
      return participants.map((id) => ({
        id,
        cents: Math.floor((amountCents * (Number(weights[id] ?? '1') || 0)) / totalWeight),
      }));
    }
    return participants.map((id) => ({
      id,
      cents: parseMoneyToCents(exactValues[id] ?? '') ?? 0,
    }));
  }, [amountCents, participants, splitType, weights, exactValues]);

  function toggleParticipant(id: string) {
    setParticipants((current) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id],
    );
  }

  async function uploadTo(expenseId: string, file: File) {
    const created = await api.uploadReceipt(expenseId, file);
    return created;
  }

  async function handleUpload(file: File) {
    setError(null);
    if (!isEdit) {
      setPendingFiles((current) => [...current, file]);
      return;
    }
    setUploading(true);
    try {
      const created = await uploadTo(expense!.id, file);
      setReceipts((current) => [...current, created]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Upload fehlgeschlagen.');
    } finally {
      setUploading(false);
    }
  }

  async function handleDeleteReceipt(receiptId: string) {
    try {
      await api.deleteReceipt(receiptId);
      setReceipts((current) => current.filter((r) => r.id !== receiptId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Löschen fehlgeschlagen.');
    }
  }

  function validate(): string | null {
    if (!description.trim()) return 'Bitte eine Beschreibung angeben.';
    if (!amountCents) return 'Bitte einen gültigen Betrag angeben, z. B. 12,50.';
    if (participants.length === 0) return 'Bitte mindestens eine Person auswählen.';
    if (splitType === 'exact' && exactTotal !== amountCents) {
      return `Die Einzelbeträge ergeben ${formatMoney(exactTotal, currency)}, die Ausgabe ist ${formatMoney(amountCents, currency)}.`;
    }
    if (splitType === 'shares') {
      const total = participants.reduce((s, id) => s + (Number(weights[id] ?? '1') || 0), 0);
      if (total <= 0) return 'Mindestens ein Anteil muss größer als 0 sein.';
    }
    return null;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }

    setError(null);
    setBusy(true);
    try {
      const body = {
        description: description.trim(),
        amount_cents: amountCents,
        payer_id: payerId,
        expense_date: date,
        category,
        note: note.trim() || null,
        split_type: splitType,
        participant_ids: splitType === 'equal' ? participants : [],
        shares:
          splitType === 'equal'
            ? []
            : participants.map((id) => ({
                member_id: id,
                value:
                  splitType === 'exact'
                    ? (parseMoneyToCents(exactValues[id] ?? '') ?? 0)
                    : Number(weights[id] ?? '1') || 0,
              })),
      };

      const saved = isEdit
        ? await api.updateExpense(expense!.id, body)
        : await api.createExpense(body);

      // Photos picked before the expense existed are attached now.
      for (const file of pendingFiles) {
        try {
          await uploadTo(saved.id, file);
        } catch {
          setError('Die Ausgabe wurde gespeichert, aber ein Beleg konnte nicht hochgeladen werden.');
        }
      }

      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Speichern fehlgeschlagen.');
    } finally {
      setBusy(false);
    }
  }

  const memberName = (id: string) => members.find((m) => m.id === id)?.display_name ?? '?';

  return (
    <Sheet title={isEdit ? 'Ausgabe bearbeiten' : 'Neue Ausgabe'} onClose={onClose}>
      <form onSubmit={submit}>
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="field amount-input" style={{ marginBottom: 8 }}>
            <input
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0,00"
              inputMode="decimal"
              aria-label={`Betrag in ${currency}`}
              autoFocus={!isEdit}
            />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Wofür? z. B. Abendessen Strandbar"
              maxLength={200}
              aria-label="Beschreibung"
            />
          </div>
        </div>

        <div className="card" style={{ marginBottom: 14 }}>
          <div className="row">
            <div className="field">
              <label htmlFor="payer">Bezahlt von</label>
              <select id="payer" value={payerId} onChange={(e) => setPayerId(e.target.value)}>
                {members.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name}
                    {m.is_you ? ' (du)' : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="date">Datum</label>
              <input
                id="date"
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </div>
          </div>

          <div className="field" style={{ marginBottom: 0 }}>
            <label htmlFor="category">Kategorie</label>
            <select
              id="category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.icon} {c.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="card" style={{ marginBottom: 14 }}>
          <div className="field">
            <label htmlFor="split">Aufteilung</label>
            <select
              id="split"
              value={splitType}
              onChange={(e) => setSplitType(e.target.value as SplitType)}
            >
              <option value="equal">Gleichmäßig teilen</option>
              <option value="exact">Genaue Beträge</option>
              <option value="shares">Nach Anteilen</option>
            </select>
          </div>

          <div className="field" style={{ marginBottom: splitType === 'equal' ? 0 : 14 }}>
            <label>Beteiligt</label>
            <div className="chips">
              {members.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  className="chip"
                  aria-pressed={participants.includes(m.id)}
                  onClick={() => toggleParticipant(m.id)}
                >
                  <span className="dot" style={{ background: m.color }} />
                  {m.display_name}
                </button>
              ))}
            </div>
          </div>

          {splitType !== 'equal' &&
            participants.map((id) => (
              <div className="field" key={id} style={{ marginBottom: 10 }}>
                <label htmlFor={`split-${id}`}>
                  {memberName(id)}
                  {splitType === 'shares' ? ' — Anteile' : ` — Betrag in ${currency}`}
                </label>
                <input
                  id={`split-${id}`}
                  inputMode={splitType === 'shares' ? 'numeric' : 'decimal'}
                  value={
                    splitType === 'shares' ? (weights[id] ?? '1') : (exactValues[id] ?? '')
                  }
                  placeholder={splitType === 'shares' ? '1' : '0,00'}
                  onChange={(e) =>
                    splitType === 'shares'
                      ? setWeights((w) => ({ ...w, [id]: e.target.value }))
                      : setExactValues((v) => ({ ...v, [id]: e.target.value }))
                  }
                />
              </div>
            ))}

          {splitType === 'exact' && amountCents !== null && (
            <div className={exactTotal === amountCents ? 'hint' : 'alert'} style={{ fontSize: 13 }}>
              Summe: {formatMoney(exactTotal, currency)} von {formatMoney(amountCents, currency)}
            </div>
          )}

          {preview && splitType !== 'exact' && participants.length > 0 && (
            <p className="hint" style={{ margin: '4px 0 0', fontSize: 13 }}>
              {preview
                .map((p) => `${memberName(p.id)}: ${formatMoney(p.cents, currency)}`)
                .join(' · ')}
            </p>
          )}
        </div>

        <div className="card" style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-dim)' }}>
            Kassenzettel
          </label>
          <p className="hint" style={{ margin: '2px 0 10px' }}>
            Foto vom Beleg — wird automatisch verkleinert und ohne Standortdaten gespeichert.
          </p>
          <Receipts
            receipts={receipts}
            onUpload={handleUpload}
            onDelete={handleDeleteReceipt}
            canDelete={(r) => r.uploaded_by_id === me.id || me.is_admin}
            uploading={uploading}
          />
          {pendingFiles.length > 0 && (
            <p className="hint" style={{ marginTop: 8 }}>
              {pendingFiles.length} Beleg(e) werden beim Speichern hochgeladen.
            </p>
          )}
        </div>

        <div className="card" style={{ marginBottom: 14 }}>
          <div className="field" style={{ marginBottom: 0 }}>
            <label htmlFor="note">Notiz (optional)</label>
            <textarea
              id="note"
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={2000}
            />
          </div>
        </div>

        {error && (
          <div className="alert" role="alert" style={{ marginBottom: 14 }}>
            {error}
          </div>
        )}

        <button className="btn" type="submit" disabled={busy}>
          {busy && <span className="spinner" aria-hidden="true" />}
          {isEdit ? 'Änderungen speichern' : 'Ausgabe eintragen'}
        </button>
      </form>
    </Sheet>
  );
}
