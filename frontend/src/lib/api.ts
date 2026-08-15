export interface Member {
  id: string;
  display_name: string;
  is_admin: boolean;
  color: string;
  is_you: boolean;
  device_bound: boolean;
}

export interface Group {
  id: string;
  name: string;
  slug: string;
  currency: string;
  created_at: string;
}

export interface SessionMember {
  id: string;
  display_name: string;
  is_admin: boolean;
  color: string;
  created_at: string;
}

export interface Session {
  access_token: string;
  device_id: string;
  member: SessionMember;
  group: Group;
}

export interface Share {
  member_id: string;
  display_name: string;
  amount_cents: number;
  weight: number;
}

export interface Receipt {
  id: string;
  original_filename: string | null;
  content_type: string;
  size_bytes: number;
  uploaded_by_id: string;
  created_at: string;
}

export interface Expense {
  id: string;
  description: string;
  amount_cents: number;
  currency: string;
  category: string;
  expense_date: string;
  note: string | null;
  split_type: 'equal' | 'exact' | 'shares';
  payer_id: string;
  payer_name: string;
  created_by_id: string;
  created_by_name: string;
  created_at: string;
  updated_at: string;
  shares: Share[];
  receipts: Receipt[];
}

export interface Balance {
  member_id: string;
  display_name: string;
  color: string;
  net_cents: number;
  paid_cents: number;
  share_cents: number;
}

export interface Transfer {
  from_member_id: string;
  from_name: string;
  to_member_id: string;
  to_name: string;
  amount_cents: number;
}

export interface BalanceSummary {
  currency: string;
  total_spent_cents: number;
  balances: Balance[];
  suggested_transfers: Transfer[];
}

export interface Settlement {
  id: string;
  from_member_id: string;
  from_name: string;
  to_member_id: string;
  to_name: string;
  amount_cents: number;
  note: string | null;
  created_at: string;
}

export interface ActivityEntry {
  id: string;
  member_name: string | null;
  action: string;
  entity_type: string;
  summary: string | null;
  created_at: string;
}

const TOKEN_KEY = 'tripcost.token';
const DEVICE_KEY = 'tripcost.device';
const SLUG_KEY = 'tripcost.slug';
const NAME_KEY = 'tripcost.name';

export const storage = {
  get token() {
    return localStorage.getItem(TOKEN_KEY);
  },
  set token(value: string | null) {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  },
  /** Persisted per phone: this is what proves the device owns its name. */
  get deviceId() {
    return localStorage.getItem(DEVICE_KEY);
  },
  set deviceId(value: string | null) {
    if (value) localStorage.setItem(DEVICE_KEY, value);
    else localStorage.removeItem(DEVICE_KEY);
  },
  get lastSlug() {
    return localStorage.getItem(SLUG_KEY);
  },
  set lastSlug(value: string | null) {
    if (value) localStorage.setItem(SLUG_KEY, value);
    else localStorage.removeItem(SLUG_KEY);
  },
  get lastName() {
    return localStorage.getItem(NAME_KEY);
  },
  set lastName(value: string | null) {
    if (value) localStorage.setItem(NAME_KEY, value);
    else localStorage.removeItem(NAME_KEY);
  },
  clearSession() {
    // The device id survives logout so the same phone can reclaim its name.
    localStorage.removeItem(TOKEN_KEY);
  },
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = storage.token;
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError(0, 'Keine Verbindung zum Server.');
  }

  if (response.status === 204) return undefined as T;

  const isJson = response.headers.get('content-type')?.includes('application/json');
  const payload = isJson ? await response.json().catch(() => null) : null;

  if (!response.ok) {
    const detail =
      (payload && typeof payload.detail === 'string' && payload.detail) ||
      // FastAPI validation errors arrive as a list of field problems.
      (Array.isArray(payload?.detail) && payload.detail[0]?.msg) ||
      `Fehler ${response.status}`;
    throw new ApiError(response.status, detail);
  }

  return payload as T;
}

export const api = {
  createGroup: (body: {
    name: string;
    password: string;
    currency: string;
    admin_name: string;
  }) => request<Session>('/api/auth/groups', { method: 'POST', body: JSON.stringify(body) }),

  login: (body: {
    group_slug: string;
    password: string;
    display_name: string;
    device_id?: string | null;
  }) => request<Session>('/api/auth/login', { method: 'POST', body: JSON.stringify(body) }),

  me: () => request<Session>('/api/auth/me'),

  members: () => request<Member[]>('/api/members'),

  expenses: () => request<Expense[]>('/api/expenses'),

  createExpense: (body: unknown) =>
    request<Expense>('/api/expenses', { method: 'POST', body: JSON.stringify(body) }),

  updateExpense: (id: string, body: unknown) =>
    request<Expense>(`/api/expenses/${id}`, { method: 'PUT', body: JSON.stringify(body) }),

  deleteExpense: (id: string) => request<void>(`/api/expenses/${id}`, { method: 'DELETE' }),

  uploadReceipt: (expenseId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<Receipt>(`/api/expenses/${expenseId}/receipts`, {
      method: 'POST',
      body: form,
    });
  },

  deleteReceipt: (id: string) => request<void>(`/api/receipts/${id}`, { method: 'DELETE' }),

  balances: () => request<BalanceSummary>('/api/balances'),

  settlements: () => request<Settlement[]>('/api/settlements'),

  createSettlement: (body: {
    from_member_id: string;
    to_member_id: string;
    amount_cents: number;
    note?: string | null;
  }) => request<Settlement>('/api/settlements', { method: 'POST', body: JSON.stringify(body) }),

  deleteSettlement: (id: string) => request<void>(`/api/settlements/${id}`, { method: 'DELETE' }),

  activity: () => request<ActivityEntry[]>('/api/activity'),

  releaseMember: (id: string) =>
    request<void>(`/api/admin/members/${id}/release`, { method: 'POST' }),

  changePassword: (newPassword: string) =>
    request<void>('/api/admin/password', {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword }),
    }),
};

/**
 * Receipt images sit behind auth, so they cannot be used as a plain <img src>.
 * Fetch them as a blob and hand back an object URL the caller must revoke.
 */
export async function fetchReceiptBlobUrl(receiptId: string, thumb = false): Promise<string> {
  const headers = new Headers();
  const token = storage.token;
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const response = await fetch(`/api/receipts/${receiptId}${thumb ? '?thumb=true' : ''}`, {
    headers,
  });
  if (!response.ok) throw new ApiError(response.status, 'Beleg konnte nicht geladen werden.');
  return URL.createObjectURL(await response.blob());
}
