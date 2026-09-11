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
  patchTxn: (id: string, body: { flow_type?: string; category?: string }) =>
    j<{ ok: boolean }>(`/api/transactions/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
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
