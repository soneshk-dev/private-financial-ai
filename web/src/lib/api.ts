/** Thin client for the homeai API. Same origin in production; Vite proxies /api in dev. */

export type Account = {
  id: string; name: string; institution: string | null; kind: string; asset_class: string; entity: string;
  is_liability: number; is_active: number; source: string; latest_balance: number | null; balance_as_of: string | null;
  mask: string | null; connection_id: string | null;
};
export type NetWorth = {
  as_of: string; assets: number; liabilities: number; net_worth: number; change: number | null;
  by_class: Record<string, number>; by_entity: Record<string, number>;
  series: { as_of: string; assets: number; liabilities: number; net_worth: number; by_class: Record<string, number> }[];
  accounts_by_class: Record<string, { id: string; name: string; institution: string; kind: string; entity: string; balance: number | null; as_of: string | null }[]>;
};
export type CashflowRow = { month: string; income: number; spending: number; taxes: number; loan_payments: number; investing: number; transfers: number; unknown: number; net: number; n: number };
export type Spending = { month: string; total: number; by_level1: { category: string; spent: number; n: number }[]; by_category: { category: string; spent: number; n: number }[]; top_merchants: { merchant: string; spent: number; n: number }[] };
export type Budget = { category: string; limit: number; spent: number; pct: number | null; status: 'ok' | 'warning' | 'over' };
export type Txn = { id: string; posted_at: string; account_name: string; account_kind: string; institution: string | null; amount: number; description: string | null; merchant: string | null; category: string | null; category_l1: string; flow: string; entity: string; pending: number; transfer_group: string | null };
export type Positions = { total: number; cost_basis_known: number; allocation: Record<string, number>; accounts: { account_id: string; name: string; kind: string; institution: string | null; as_of: string; value: number; positions: { key: string; symbol: string | null; description: string | null; quantity: number | null; price: number | null; value: number; cost_basis: number | null; asset_class: string | null }[] }[] };
export type Crypto = { wallets: { id: string; name: string; source: string; balance: number | null; as_of: string | null }[]; total: number; protocols: { protocol: string; network: string; supplied: any[]; borrowed: any[]; claimable: any[]; net: number }[]; aave: { health_factor: number; status: string; collateral: number; debt: number; liquidation_price_btc: number | null; collateral_breakdown: Record<string, number>; debt_breakdown: Record<string, number> } | null };
export type Health = { version: string; schema_version: number; connectors: { connector: string; status: string; last_success_at: string | null; last_error: string | null; rows_written: number }[]; connections: { id: string; connector: string; institution: string; status: string; error_code: string | null; last_success_at: string | null }[]; counts: Record<string, number>; latest_snapshot: { as_of: string; net_worth: number } | null };
export type Entity = { slug: string; name: string; kind: string; tax_form: string | null; accounts: number; transactions: number; months: number; revenue: number; expenses: number; net: number };
export type PnlRow = { month: string; revenue: number; expenses: number; taxes: number; transfers: number; n: number; net: number };
export type ReviewItem = { id: string; posted_at: string; account_name: string; amount: number; description: string | null; merchant: string | null; category: string | null; flow: string; entity: string; reason: string };
export type Runway = { as_of: string; reserve: number; reserve_detail: { name: string; kind: string; value: number }[]; burn: { months_averaged: number; spending: number; loan_payments: number; taxes: number; total: number }; incomes: { name: string; monthly: number; observed_monthly: number; until: string | null; matches: number }[]; net_monthly_now: number; months_no_income: number | null; cliff_month: string | null; reserve_at_horizon: number; series: { month: string; reserve: number; income: number; burn: number }[] };
export type TaxEstimate = { year: number; as_of: string; filing_status: string; income: { wages: number; wages_source: string; other_personal_income: number; investment_income: number; business: Record<string, { revenue: number; expenses: number; net: number }>; business_net: number; additional: Record<string, number>; agi: number }; deductions: { standard: number }; taxable_income: number; federal: { tax: number; niit: number; marginal_rate: number; paid: number; remaining: number }; state: { rate: number; tax: number; paid: number; remaining: number }; total_tax: number; effective_rate: number | null; safe_harbor: { required_payments: number; multiplier: number; paid: number; shortfall: number; met: boolean } | null; schedule: { due: string; federal: number; state: number }[]; roth_headroom_in_bracket: number | null; caveats: string[] };
export type Goal = { slug: string; name: string; kind: string; priority: number; target_amount: number | null; target_date: string | null; current: number; start_amount: number | null; pct: number | null; remaining: number | null; months_left: number | null; needed_monthly: number | null; monthly_contribution: number | null; on_track: boolean | null; notes: string | null };
export type TaxonomySub = { name: string; category: string; n: number; last: string | null; core: boolean };
export type TaxonomyL1 = { level1: string; n: number; bare_n: number; stray: number; subs: TaxonomySub[] };
export type MergeSuggestion = { from: string; to: string; n: number; last: string | null; confidence: number };
export type CategoryRule = { id: number; pattern: string; match_kind: string; category: string; flow_type: string | null; priority: number; source: string | null; created_at: string };
export type Similar = { merchant: string; n: number; categories: { category: string | null; n: number; total: number }[]; rule: { id: number; category: string } | null };
export type CategoryResult = { id: string; category: string; scope: 'one' | 'merchant'; merchant: string; affected: number; rule_id: number | null };
export type AllocRow = { class: string; label: string; value: number; pct: number | null; policy_pct: number | null; drift_pct: number | null; drift_value: number | null; out_of_band?: boolean; side?: boolean };
export type RegistryAccount = { id: string; name: string; kind: string; institution: string | null; asset_class: string; balance: number; balance_as_of: string | null; role: string; tax_treatment: string; tradability: string; restrictions: string[]; overridden: boolean };
export type Holding = { account_id: string; account_name: string; role: string; tax_treatment: string; symbol: string | null; description: string | null; value: number; quantity: number | null; price: number | null; cost_basis: number | null; classes: Record<string, number>; how: string };
export type PortfolioSettings = { thesis_cap_pct: number; drift_band_pct: number; crypto_in_policy: boolean; never_sell: string[]; policy: Record<string, number>; exposures: Record<string, Record<string, number>>; account_roles: Record<string, { role?: string; tradability?: string; tax_treatment?: string; restrictions?: string[] }>; benchmarks: string[]; macro_series: string[] };
export type Allocation = { as_of: string | null; investable: number; sleeves: Record<string, number>; thesis_cap: number; thesis_used: number; by_class: AllocRow[]; holdings: Holding[]; unclassified: { symbol: string | null; description: string | null; value: number; account: string }[]; settings: PortfolioSettings; accounts: RegistryAccount[] };
export type Macro = { series: string; label: string; as_of: string; value: number; prior: number; prior_as_of: string; change: number; history: { as_of: string; value: number }[] };
export type KillMetric = { series: string; op: '>' | '<'; level: number; note?: string; value?: number | null; breached?: boolean; distance_pct?: number | null };
export type ThesisLeg = { id: number; symbol: string; direction: string; account_id: string | null; account_name?: string | null; quantity: number | null; quantity_source?: string; entry_price: number | null; entry_price_used: number | null; price: number | null; price_as_of: string | null; value: number; pnl: number | null; return_pct: number | null; closed_at: string | null; notes: string | null };
export type Thesis = { slug: string; name: string; view: string; status: string; conviction: number; budget_pct: number; budget: number; deployed: number; pnl: number | null; return_pct: number | null; over_budget: boolean; horizon_start: string | null; horizon_end: string | null; horizon_pct?: number; days_left?: number; expired?: boolean; benchmark: string | null; benchmark_return_pct?: number | null; exit_rules: string | null; notes: string | null; kill_metrics: KillMetric[]; kill_breached: boolean; legs: ThesisLeg[] };
export type ThesisBudget = { cap: number; cap_pct: number; deployed: number; allocated_pct_of_cap: number; remaining: number };
export type PlacementOption = { account_id: string; account: string; tax_treatment: string; tradability: string; restrictions: string[]; tax_rate_on_gain: number; tax_on_expected_gain: number; after_tax_gain: number; cash_available: number; funded_from_cash: boolean; already_holds: boolean; note: string };
export type Candidate = { symbol: string; price: { as_of: string; close: number } | null; return_1m_pct: number | null; return_3m_pct: number | null; class: string; class_now_pct: number | null; class_after_pct: number | null; class_policy_pct: number | null; already_held: { account: string; value: number }[]; already_held_value: number; never_sell: boolean; placement: PlacementOption[] };
export type Analysis = { amount: number; per_symbol: number; holding_months: number; expected_return_pct: number; candidates: Candidate[]; rates: { short_term_total: number; long_term_total: number; basis: string }; thesis_budget: ThesisBudget & { after_this: number; fits: boolean }; note: string };
export type Model = { name: string; base_url: string; reachable: boolean; model: string | null; default: boolean; fallback: boolean };
export type Conversation = { id: string; title: string | null; provider: string | null; model: string | null; created_at: string; updated_at: string; n?: number; messages?: Message[] };
export type Message = { id?: number; role: 'user' | 'assistant' | 'tool'; content: string | null; tool_calls?: any[] | null; name?: string | null };

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...init });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
const q = (o: Record<string, any>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : '';
};

export const api = {
  health: () => j<Health>('/api/health'),
  accounts: (all = false) => j<Account[]>(`/api/accounts${q({ all })}`),
  patchAccount: (id: string, body: Partial<Pick<Account, 'kind' | 'entity' | 'name'>> & { is_active?: boolean }) =>
    j<{ ok: boolean }>(`/api/accounts/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  netWorth: (days = 365) => j<NetWorth>(`/api/net-worth${q({ days })}`),
  cashflow: (months = 12, entity?: string) => j<CashflowRow[]>(`/api/cashflow${q({ months, entity })}`),
  spending: (month?: string, entity?: string) => j<Spending>(`/api/spending${q({ month, entity })}`),
  budgets: (month?: string) => j<Budget[]>(`/api/budgets${q({ month })}`),
  transactions: (f: Record<string, any>) => j<Txn[]>(`/api/transactions${q(f)}`),
  entities: (months = 12) => j<Entity[]>(`/api/entities${q({ months })}`),
  pnl: (entity: string, months = 12) => j<PnlRow[]>(`/api/business/pnl${q({ entity, months })}`),
  review: (months = 6) => j<ReviewItem[]>(`/api/business/review${q({ months })}`),
  runway: () => j<Runway>('/api/runway'),
  tax: () => j<TaxEstimate>('/api/tax'),
  goals: () => j<Goal[]>('/api/goals'),
  patchTxn: (id: string, body: { flow_type?: string; category?: string; entity?: string }) =>
    j<{ ok: boolean }>(`/api/transactions/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  categories: () => j<{ taxonomy: TaxonomyL1[]; rules: CategoryRule[]; rule_counts: Record<string, number> }>('/api/categories'),
  categorySuggestions: () => j<MergeSuggestion[]>('/api/categories/suggestions'),
  keepCategory: (category: string, keep = true) => j<{ kept: string[] }>('/api/categories/keep', { method: 'POST', body: JSON.stringify({ category, keep }) }),
  similar: (id: string) => j<Similar>(`/api/transactions/${id}/similar`),
  setCategory: (id: string, body: { category: string; scope: 'one' | 'merchant'; remember?: boolean; allow_new?: boolean }) =>
    j<CategoryResult>(`/api/transactions/${id}/category`, { method: 'POST', body: JSON.stringify(body) }),
  renameCategory: (from_category: string, to_category: string, allow_new = false) =>
    j<{ from: string; to: string; affected: number; rules: number }>('/api/categories/rename', { method: 'POST', body: JSON.stringify({ from_category, to_category, allow_new }) }),
  deleteRule: (id: number) => j<{ ok: boolean }>(`/api/categories/rules/${id}`, { method: 'DELETE' }),
  allocation: () => j<Allocation>('/api/portfolio/allocation'),
  portfolioSettings: () => j<PortfolioSettings>('/api/portfolio/settings'),
  savePortfolioSettings: (patch: Partial<PortfolioSettings>) => j<PortfolioSettings>('/api/portfolio/settings', { method: 'PUT', body: JSON.stringify(patch) }),
  theses: (closed = false) => j<{ theses: Thesis[]; budget: ThesisBudget }>(`/api/theses${q({ closed })}`),
  saveThesis: (body: Record<string, unknown>) => j<{ slug: string }>('/api/theses', { method: 'POST', body: JSON.stringify(body) }),
  saveLeg: (slug: string, body: Record<string, unknown>) => j<{ id: number }>(`/api/theses/${slug}/legs`, { method: 'POST', body: JSON.stringify(body) }),
  deleteLeg: (slug: string, id: number) => j<any>(`/api/theses/${slug}/legs/${id}`, { method: 'DELETE' }),
  analyze: (body: Record<string, unknown>) => j<Analysis>('/api/portfolio/analyze', { method: 'POST', body: JSON.stringify(body) }),
  macro: (days = 30) => j<Macro[]>(`/api/market/macro${q({ days })}`),
  positions: () => j<Positions>('/api/positions'),
  crypto: () => j<Crypto>('/api/crypto'),
  sync: (only?: string) => j<any>(`/api/sync${q({ only })}`, { method: 'POST' }),
  models: () => j<Model[]>('/api/models'),
  conversations: () => j<Conversation[]>('/api/conversations'),
  conversation: (id: string) => j<Conversation>(`/api/conversations/${id}`),
  deleteConversation: (id: string) => j<{ deleted: number }>(`/api/conversations/${id}`, { method: 'DELETE' }),
  brief: () => j<{ text: string }>('/api/brief'),
};

export type ChatEvent =
  | { type: 'conversation'; id: string } | { type: 'routing'; provider: string; model: string }
  | { type: 'status'; message: string } | { type: 'reasoning'; content: string }
  | { type: 'tool_call'; id: string; name: string; arguments: any }
  | { type: 'tool_result'; id: string; name: string; preview: string; error: boolean }
  | { type: 'message'; content: string } | { type: 'done'; usage: any } | { type: 'error'; message: string };

/** POST /api/chat and yield parsed SSE events. */
export async function* chat(body: { message: string; conversation_id?: string | null; provider?: string | null }): AsyncGenerator<ChatEvent> {
  const r = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok || !r.body) throw new Error(`${r.status} ${await r.text()}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const data = chunk.split('\n').find((l) => l.startsWith('data: '));
      if (data) yield JSON.parse(data.slice(6)) as ChatEvent;
    }
  }
}
