export const money = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? '—' : (v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** Auto-compact for tiles: $1.28M / $412K / $980 */
export const compact = (v: number | null | undefined) => {
  if (v === null || v === undefined) return '—';
  const a = Math.abs(v), s = v < 0 ? '-' : '';
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(a >= 1e7 ? 1 : 2)}M`;
  if (a >= 1e4) return `${s}$${(a / 1e3).toFixed(a >= 1e5 ? 0 : 1)}K`;
  return `${s}$${a.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
};
export const signed = (v: number) => (v >= 0 ? '+' : '') + money(v);
export const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`);
export const monthLabel = (m: string) => new Date(m + '-02').toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
export const dateLabel = (d: string) => new Date(d + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
export const thisMonth = () => new Date().toISOString().slice(0, 7);
export const shiftMonth = (m: string, delta: number) => {
  const d = new Date(m + '-02T12:00:00');
  d.setMonth(d.getMonth() + delta);
  return d.toISOString().slice(0, 7);
};
export const titleCase = (s: string) => s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
export const KIND_LABEL: Record<string, string> = {
  checking: 'Checking', savings: 'Savings', money_market: 'Money market', cd: 'CD', cash_mgmt: 'Cash management',
  credit_card: 'Credit card', mortgage: 'Mortgage', heloc: 'HELOC', loan: 'Loan', student_loan: 'Student loan',
  brokerage: 'Brokerage', retirement_401k: '401(k)', roth_401k: 'Roth 401(k)', ira: 'IRA', roth_ira: 'Roth IRA', hsa: 'HSA',
  deferred_comp: 'Deferred comp', e529: '529', custodial: 'Custodial', crypto_wallet: 'Crypto wallet',
  crypto_exchange: 'Crypto exchange', real_estate: 'Real estate', vehicle: 'Vehicle', other: 'Other',
};
export const CLASS_LABEL: Record<string, string> = {
  cash: 'Cash', investments: 'Investments', retirement: 'Retirement', education: 'Education', crypto: 'Crypto',
  real_estate: 'Real estate', liability: 'Debt', other: 'Other',
};
export const FLOWS = ['expense', 'income', 'transfer', 'investment_buy', 'investment_sell', 'dividend', 'interest', 'loan_payment', 'tax', 'fee', 'refund', 'unknown'];
export const KINDS = Object.keys(KIND_LABEL);
