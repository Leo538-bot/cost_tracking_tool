import { useCallback, useEffect, useState } from 'react';

import Balances from './components/Balances';
import ExpenseList from './components/ExpenseList';
import ExpenseSheet from './components/ExpenseSheet';
import Login from './components/Login';
import Settings from './components/Settings';
import {
  ActivityEntry,
  ApiError,
  BalanceSummary,
  Expense,
  Member,
  Session,
  Settlement,
  api,
  storage,
} from './lib/api';
import { formatMoney } from './lib/format';

type Tab = 'expenses' | 'balances' | 'settings';

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);

  const [tab, setTab] = useState<Tab>('expenses');
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [summary, setSummary] = useState<BalanceSummary | null>(null);
  const [settlements, setSettlements] = useState<Settlement[]>([]);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);

  const [sheet, setSheet] = useState<{ open: boolean; expense: Expense | null }>({
    open: false,
    expense: null,
  });
  const [loadError, setLoadError] = useState<string | null>(null);

  // Resume a stored session on app start; an expired token just drops to login.
  useEffect(() => {
    if (!storage.token) {
      setChecking(false);
      return;
    }
    api
      .me()
      .then((restored) => {
        storage.token = restored.access_token;
        setSession(restored);
      })
      .catch(() => storage.clearSession())
      .finally(() => setChecking(false));
  }, []);

  const refresh = useCallback(async () => {
    if (!session) return;
    try {
      const [nextExpenses, nextMembers, nextSummary, nextSettlements, nextActivity] =
        await Promise.all([
          api.expenses(),
          api.members(),
          api.balances(),
          api.settlements(),
          api.activity(),
        ]);
      setExpenses(nextExpenses);
      setMembers(nextMembers);
      setSummary(nextSummary);
      setSettlements(nextSettlements);
      setActivity(nextActivity);
      setLoadError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        // The admin released this name, or the token expired mid-use.
        storage.clearSession();
        setSession(null);
        return;
      }
      setLoadError(err instanceof Error ? err.message : 'Daten konnten nicht geladen werden.');
    }
  }, [session]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function logout() {
    storage.clearSession();
    setSession(null);
    setExpenses([]);
    setMembers([]);
    setSummary(null);
    setTab('expenses');
  }

  if (checking) {
    return <p className="center-note" style={{ paddingTop: 80 }}>Lädt…</p>;
  }

  if (!session) {
    return <Login onAuthenticated={setSession} />;
  }

  const { group, member: me } = session;
  const myBalance = summary?.balances.find((b) => b.member_id === me.id);

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>{group.name}</h1>
          <p className="sub">
            {members.length} {members.length === 1 ? 'Person' : 'Personen'}
            {myBalance && myBalance.net_cents !== 0 && (
              <>
                {' · '}
                <span className={myBalance.net_cents > 0 ? 'pos' : 'neg'}>
                  {myBalance.net_cents > 0 ? 'bekommst ' : 'schuldest '}
                  {formatMoney(Math.abs(myBalance.net_cents), group.currency)}
                </span>
              </>
            )}
          </p>
        </div>
        <button
          type="button"
          className="btn slim"
          onClick={() => setSheet({ open: true, expense: null })}
        >
          + Neu
        </button>
      </header>

      <main className="content">
        {loadError && (
          <div className="alert" role="alert">
            {loadError}
          </div>
        )}

        {tab === 'expenses' && (
          <ExpenseList
            expenses={expenses}
            me={me}
            currency={group.currency}
            onEdit={(expense) => setSheet({ open: true, expense })}
            onChanged={refresh}
          />
        )}

        {tab === 'balances' &&
          (summary ? (
            <Balances
              summary={summary}
              settlements={settlements}
              members={members}
              me={me}
              onChanged={refresh}
            />
          ) : (
            <p className="center-note">Lädt…</p>
          ))}

        {tab === 'settings' && (
          <Settings
            group={group}
            members={members}
            me={me}
            activity={activity}
            onChanged={refresh}
            onLogout={logout}
          />
        )}
      </main>

      <nav className="tabbar" aria-label="Hauptnavigation">
        <button
          type="button"
          aria-current={tab === 'expenses' ? 'page' : undefined}
          onClick={() => setTab('expenses')}
        >
          <span className="glyph" aria-hidden="true">
            🧾
          </span>
          Ausgaben
        </button>
        <button
          type="button"
          aria-current={tab === 'balances' ? 'page' : undefined}
          onClick={() => setTab('balances')}
        >
          <span className="glyph" aria-hidden="true">
            ⚖️
          </span>
          Salden
        </button>
        <button type="button" onClick={() => setSheet({ open: true, expense: null })}>
          <span className="glyph" aria-hidden="true">
            ➕
          </span>
          Eintragen
        </button>
        <button
          type="button"
          aria-current={tab === 'settings' ? 'page' : undefined}
          onClick={() => setTab('settings')}
        >
          <span className="glyph" aria-hidden="true">
            ⚙️
          </span>
          Gruppe
        </button>
      </nav>

      {sheet.open && members.length > 0 && (
        <ExpenseSheet
          members={members}
          me={me}
          currency={group.currency}
          expense={sheet.expense}
          onClose={() => setSheet({ open: false, expense: null })}
          onSaved={refresh}
        />
      )}
    </div>
  );
}
