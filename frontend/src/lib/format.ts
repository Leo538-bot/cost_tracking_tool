/** Money helpers. The API speaks integer cents; the UI speaks "12,50". */

export function formatMoney(cents: number, currency = 'EUR'): string {
  return new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency,
  }).format(cents / 100);
}

export function formatMoneyPlain(cents: number): string {
  return (cents / 100).toFixed(2).replace('.', ',');
}

/**
 * Parse what a person actually types: "12,50", "12.50", "1.234,56", "12".
 * Returns null for anything that is not a positive amount.
 */
export function parseMoneyToCents(input: string): number | null {
  const trimmed = input.trim().replace(/\s|€/g, '');
  if (!trimmed) return null;

  let normalised = trimmed;
  const hasComma = normalised.includes(',');
  const hasDot = normalised.includes('.');

  if (hasComma && hasDot) {
    // Whichever separator comes last is the decimal one.
    normalised =
      normalised.lastIndexOf(',') > normalised.lastIndexOf('.')
        ? normalised.replace(/\./g, '').replace(',', '.')
        : normalised.replace(/,/g, '');
  } else if (hasComma) {
    normalised = normalised.replace(',', '.');
  }

  if (!/^\d+(\.\d{1,2})?$/.test(normalised)) return null;

  const cents = Math.round(Number(normalised) * 100);
  return Number.isFinite(cents) && cents > 0 ? cents : null;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function today(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  return new Date(now.getTime() - offset * 60_000).toISOString().slice(0, 10);
}

export const CATEGORIES = [
  { value: 'food', label: 'Essen', icon: '🍽️' },
  { value: 'groceries', label: 'Einkauf', icon: '🛒' },
  { value: 'accommodation', label: 'Unterkunft', icon: '🏠' },
  { value: 'transport', label: 'Transport', icon: '🚗' },
  { value: 'activities', label: 'Aktivitäten', icon: '🎟️' },
  { value: 'drinks', label: 'Getränke', icon: '🍹' },
  { value: 'shopping', label: 'Shopping', icon: '🛍️' },
  { value: 'other', label: 'Sonstiges', icon: '📌' },
] as const;

export function categoryOf(value: string) {
  return CATEGORIES.find((c) => c.value === value) ?? CATEGORIES[CATEGORIES.length - 1];
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}
