import { useMemo, useState } from 'react';

import { Expense, SessionMember, api } from '../lib/api';
import { categoryOf, formatDate, formatMoney } from '../lib/format';
import { useReceiptUrl } from '../lib/useReceiptUrl';
import Sheet from './Sheet';

interface Props {
  expenses: Expense[];
  me: SessionMember;
  currency: string;
  onEdit: (expense: Expense) => void;
  onChanged: () => void;
}

export default function ExpenseList({ expenses, me, currency, onEdit, onChanged }: Props) {
  const [detail, setDetail] = useState<Expense | null>(null);
  const [deleting, setDeleting] = useState(false);

  const groups = useMemo(() => {
    const byDate = new Map<string, Expense[]>();
    for (const expense of expenses) {
      const list = byDate.get(expense.expense_date) ?? [];
      list.push(expense);
      byDate.set(expense.expense_date, list);
    }
    return [...byDate.entries()];
  }, [expenses]);

  if (expenses.length === 0) {
    return (
      <div className="card empty">
        <span className="big" aria-hidden="true">
          🧾
        </span>
        Noch keine Ausgaben.
        <br />
        Tippe auf „Neu", um die erste einzutragen.
      </div>
    );
  }

  const canModify = (expense: Expense) => expense.created_by_id === me.id || me.is_admin;

  async function remove(expense: Expense) {
    if (!confirm(`„${expense.description}" wirklich löschen?`)) return;
    setDeleting(true);
    try {
      await api.deleteExpense(expense.id);
      setDetail(null);
      onChanged();
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      {groups.map(([date, items]) => (
        <div key={date}>
          <p className="section-title">{formatDate(date)}</p>
          <div className="card tight" style={{ marginTop: 8 }}>
            <div className="list">
              {items.map((expense) => {
                const category = categoryOf(expense.category);
                const myShare = expense.shares.find((s) => s.member_id === me.id);
                return (
                  <button
                    key={expense.id}
                    type="button"
                    className="list-item"
                    onClick={() => setDetail(expense)}
                  >
                    <span className="icon" aria-hidden="true">
                      {category.icon}
                    </span>
                    <span className="body">
                      <span className="title">
                        {expense.description}
                        {expense.receipts.length > 0 && (
                          <span aria-label="mit Beleg" title="Kassenzettel vorhanden">
                            {' '}
                            📎
                          </span>
                        )}
                      </span>
                      <span className="meta">
                        {expense.payer_name} hat bezahlt
                        {myShare ? ` · dein Anteil ${formatMoney(myShare.amount_cents, currency)}` : ''}
                      </span>
                    </span>
                    <span className="trailing">
                      <span className="amount">{formatMoney(expense.amount_cents, currency)}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      ))}

      {detail && (
        <Sheet title={detail.description} onClose={() => setDetail(null)}>
          <div className="card" style={{ marginBottom: 14 }}>
            <div className="hero" style={{ padding: '6px 0 14px' }}>
              <span className="label">Gesamt</span>
              <span className="value">{formatMoney(detail.amount_cents, currency)}</span>
              <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>
                {categoryOf(detail.category).icon} {categoryOf(detail.category).label} ·{' '}
                {formatDate(detail.expense_date)}
              </span>
            </div>

            <p style={{ margin: 0, fontSize: 14 }}>
              <strong>{detail.payer_name}</strong> hat ausgelegt.
            </p>
            <p className="hint" style={{ margin: '4px 0 0' }}>
              Eingetragen von {detail.created_by_name}
            </p>
            {detail.note && <p style={{ marginBottom: 0 }}>{detail.note}</p>}
          </div>

          <p className="section-title">Aufteilung</p>
          <div className="card tight" style={{ margin: '8px 0 14px' }}>
            <div className="list">
              {detail.shares.map((share) => (
                <div key={share.member_id} className="list-item" style={{ cursor: 'default' }}>
                  <span className="body">
                    <span className="title">
                      {share.display_name}
                      {share.member_id === me.id && <span className="badge"> du</span>}
                    </span>
                  </span>
                  <span className="trailing">
                    <span className="amount">{formatMoney(share.amount_cents, currency)}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>

          {detail.receipts.length > 0 && (
            <>
              <p className="section-title">Kassenzettel</p>
              <div className="card" style={{ margin: '8px 0 14px' }}>
                <ReceiptStrip expense={detail} />
              </div>
            </>
          )}

          {canModify(detail) && (
            <div className="row">
              <button
                type="button"
                className="btn secondary"
                onClick={() => {
                  const target = detail;
                  setDetail(null);
                  onEdit(target);
                }}
              >
                Bearbeiten
              </button>
              <button
                type="button"
                className="btn danger"
                disabled={deleting}
                onClick={() => remove(detail)}
              >
                Löschen
              </button>
            </div>
          )}
        </Sheet>
      )}
    </>
  );
}

/** Read-only receipt gallery inside the detail sheet. */
function ReceiptStrip({ expense }: { expense: Expense }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <>
      <div className="thumbs">
        {expense.receipts.map((receipt) => (
          <ReceiptThumb key={receipt.id} id={receipt.id} onOpen={() => setOpen(receipt.id)} />
        ))}
      </div>
      {open && <ReceiptFull id={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function ReceiptThumb({ id, onOpen }: { id: string; onOpen: () => void }) {
  const url = useReceiptUrl(id, true);
  return (
    <button type="button" className="thumb" onClick={onOpen} aria-label="Beleg öffnen">
      {url && <img src={url} alt="" />}
    </button>
  );
}

function ReceiptFull({ id, onClose }: { id: string; onClose: () => void }) {
  const url = useReceiptUrl(id, false);
  return (
    <div className="lightbox" onClick={onClose} role="dialog" aria-modal="true">
      {url ? <img src={url} alt="Kassenzettel" /> : <span style={{ color: '#fff' }}>Lädt…</span>}
    </div>
  );
}
