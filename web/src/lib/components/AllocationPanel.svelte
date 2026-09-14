<script lang="ts">
  import { api, type Allocation, type PortfolioSettings } from '$lib/api';
  import { money, compact } from '$lib/format';

  let { alloc, onchanged }: { alloc: Allocation; onchanged: () => void } = $props();
  const CLASSES = ['us_equity', 'intl_equity', 'em_equity', 'bonds', 'gold', 'btc', 'eth', 'other_crypto', 'cash', 'other'];
  const LABEL: Record<string, string> = { us_equity: 'US equity', intl_equity: 'International equity', em_equity: 'Emerging markets', bonds: 'Bonds', gold: 'Gold', btc: 'Bitcoin', eth: 'Ether', other_crypto: 'Other crypto', cash: 'Cash', other: 'Other' };
  const ROLES = ['reserve', 'core', 'thesis', 'earmarked', 'excluded'];
  const TRADE = ['open', 'menu', 'manual', 'cash', 'locked'];
  const TAX = ['taxable', 'tax_deferred', 'tax_free', 'tax_free_medical', 'tax_free_education', 'kiddie', 'none'];

  let editing = $state(false);
  let showAccounts = $state(false);
  let draft = $state<{ thesis_cap_pct: number; drift_band_pct: number; crypto_in_policy: boolean; never_sell: string; policy: Record<string, number> }>({ thesis_cap_pct: 15, drift_band_pct: 5, crypto_in_policy: true, never_sell: '', policy: {} });
  let msg = $state('');
  let err = $state('');
  let busy = $state(false);

  function startEdit() {
    const s = alloc.settings;
    draft = { thesis_cap_pct: s.thesis_cap_pct, drift_band_pct: s.drift_band_pct, crypto_in_policy: s.crypto_in_policy,
              never_sell: s.never_sell.join(', '), policy: Object.fromEntries(CLASSES.map((c) => [c, s.policy[c] ?? 0])) };
    editing = true; err = '';
  }
  const policySum = $derived(Object.values(draft.policy).reduce((a, b) => a + (Number(b) || 0), 0));
  async function save(patch: Partial<PortfolioSettings>) {
    busy = true; err = ''; msg = '';
    try { await api.savePortfolioSettings(patch); msg = 'saved'; editing = false; onchanged(); }
    catch (e: any) { err = String(e.message ?? e).replace(/^\d+\s*/, ''); }
    finally { busy = false; setTimeout(() => (msg = ''), 3000); }
  }
  function saveDraft() {
    save({ thesis_cap_pct: Number(draft.thesis_cap_pct), drift_band_pct: Number(draft.drift_band_pct), crypto_in_policy: draft.crypto_in_policy,
           never_sell: draft.never_sell.split(/[,\s]+/).filter(Boolean), policy: Object.fromEntries(Object.entries(draft.policy).map(([k, v]) => [k, Number(v) || 0]).filter(([, v]) => (v as number) > 0)) });
  }
  function classify(u: { symbol: string | null; description: string | null }, cls: string) {
    if (!cls) return;
    const key = u.symbol || u.description || '';
    save({ exposures: { ...alloc.settings.exposures, [key]: { [cls]: 1 } } });
  }
  function setAccount(id: string, field: 'role' | 'tradability' | 'tax_treatment', value: string) {
    const cur = alloc.settings.account_roles[id] ?? {};
    save({ account_roles: { ...alloc.settings.account_roles, [id]: { ...cur, [field]: value } } });
  }
  const maxPct = $derived(Math.max(10, ...alloc.by_class.map((r) => Math.max(r.pct ?? 0, r.policy_pct ?? 0))));
  const capPct = $derived(alloc.thesis_cap ? Math.min(100, (alloc.thesis_used / alloc.thesis_cap) * 100) : 0);
</script>

<div class="grid kpis">
  <div class="card tile"><div class="label">Investable (core + thesis)</div><div class="value">{compact(alloc.investable)}</div><div class="delta">policy applies to this</div></div>
  <div class="card tile"><div class="label">Reserve sleeve</div><div class="value">{compact(alloc.sleeves.reserve)}</div><div class="delta">runway cash, outside the policy</div></div>
  <div class="card tile"><div class="label">Thesis sleeve</div><div class="value">{compact(alloc.thesis_used)} <span class="muted small">of {compact(alloc.thesis_cap)}</span></div>
    <div class="meter" style="padding:6px 0 0"><div class="track"><div class="fill" class:over={capPct > 100} style="width:{capPct}%"></div></div></div>
    <div class="delta">cap {alloc.settings.thesis_cap_pct}% of investable</div></div>
  <div class="card tile"><div class="label">Earmarked</div><div class="value">{compact(alloc.sleeves.earmarked)}</div><div class="delta">529s, custodial, deferred comp</div></div>
</div>

<div class="card" style="margin-top:16px">
  <div class="h2row">
    <h2>Allocation vs policy <span class="muted small">— look-through, drift band ±{alloc.settings.drift_band_pct}%{alloc.settings.crypto_in_policy ? '' : ' · crypto held beside the policy'}</span></h2>
    <div>{#if msg}<span class="badge good">{msg}</span>{/if} {#if err}<span class="badge bad">{err}</span>{/if}
      {#if !editing}<button class="btn" onclick={startEdit}>Edit policy &amp; variables</button>{/if}</div>
  </div>
  {#if editing}
    <div class="edit">
      <div class="row"><label>Thesis cap % of investable <input type="number" step="1" min="0" max="100" bind:value={draft.thesis_cap_pct} /></label>
        <label>Drift band % <input type="number" step="0.5" min="0.5" max="50" bind:value={draft.drift_band_pct} /></label>
        <label><input type="checkbox" bind:checked={draft.crypto_in_policy} /> crypto counts inside the policy</label>
        <label>Never sell <input placeholder="BTC, ETH" bind:value={draft.never_sell} /></label></div>
      <div class="row policy">
        {#each CLASSES as c}<label>{LABEL[c]} <input type="number" step="1" min="0" max="100" bind:value={draft.policy[c]} /></label>{/each}
        <span class="badge" class:bad={Math.abs(policySum - 100) > 0.5} class:good={Math.abs(policySum - 100) <= 0.5}>sum {policySum}%</span>
      </div>
      <div class="row"><button class="btn primary" onclick={saveDraft} disabled={busy || Math.abs(policySum - 100) > 0.5}>Save</button><button class="btn" onclick={() => (editing = false)}>Cancel</button></div>
    </div>
  {/if}
  <table class="data">
    <thead><tr><th>Class</th><th style="width:40%">Current vs policy</th><th class="num">Value</th><th class="num">Now</th><th class="num">Policy</th><th class="num">Drift</th></tr></thead>
    <tbody>
      {#each alloc.by_class.filter((r) => r.value > 0 || (r.policy_pct ?? 0) > 0) as r, i}
        <tr>
          <td>{r.label}{#if r.side}<span class="badge" style="margin-left:6px">beside policy</span>{/if}</td>
          <td>
            {#if r.pct !== null}
              <div class="bars">
                <div class="bar now" style="width:{((r.pct ?? 0) / maxPct) * 100}%;background:var(--series-{(i % 8) + 1})"></div>
                {#if r.policy_pct !== null}<div class="marker" style="left:{(r.policy_pct / maxPct) * 100}%" title="policy {r.policy_pct}%"></div>{/if}
              </div>
            {/if}
          </td>
          <td class="num">{money(r.value)}</td>
          <td class="num">{r.pct !== null ? `${r.pct}%` : '—'}</td>
          <td class="num muted">{r.policy_pct !== null ? `${r.policy_pct}%` : '—'}</td>
          <td class="num">{#if r.drift_pct !== null}<span class="badge" class:warn={r.out_of_band}>{r.drift_pct > 0 ? '+' : ''}{r.drift_pct}% · {r.drift_value! > 0 ? '+' : ''}{compact(r.drift_value)}</span>{/if}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if alloc.unclassified.length}
    <h2 style="margin-top:16px">Holdings classified by asset type only <span class="muted small">— assign a class so the look-through is right</span></h2>
    <table class="data">
      <tbody>
        {#each alloc.unclassified as u}
          <tr><td>{u.symbol ? `${u.symbol} · ` : ''}{u.description}</td><td class="muted small">{u.account}</td><td class="num">{money(u.value)}</td>
            <td class="num"><select onchange={(e) => classify(u, (e.target as HTMLSelectElement).value)}><option value="">assign…</option>{#each CLASSES as c}<option value={c}>{LABEL[c]}</option>{/each}</select></td></tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>

<div class="card" style="margin-top:16px">
  <div class="h2row"><h2>Accounts: role, tax treatment, what can be traded</h2>
    <button class="btn" onclick={() => (showAccounts = !showAccounts)}>{showAccounts ? 'Hide' : 'Show'} {alloc.accounts.length} accounts</button></div>
  {#if showAccounts}
    <table class="data">
      <thead><tr><th>Account</th><th class="num">Balance</th><th>Role</th><th>Tax</th><th>Tradability</th><th>Restrictions</th></tr></thead>
      <tbody>
        {#each [...alloc.accounts].sort((a, b) => b.balance - a.balance) as a}
          <tr>
            <td>{a.name}<div class="muted small">{a.kind}{a.overridden ? ' · edited' : ''}</div></td>
            <td class="num">{money(a.balance)}</td>
            <td class="inline-edit"><select value={a.role} onchange={(e) => setAccount(a.id, 'role', (e.target as HTMLSelectElement).value)}>{#each ROLES as r}<option value={r}>{r}</option>{/each}</select></td>
            <td class="inline-edit"><select value={a.tax_treatment} onchange={(e) => setAccount(a.id, 'tax_treatment', (e.target as HTMLSelectElement).value)}>{#each TAX as t}<option value={t}>{t.replace(/_/g, ' ')}</option>{/each}</select></td>
            <td class="inline-edit"><select value={a.tradability} onchange={(e) => setAccount(a.id, 'tradability', (e.target as HTMLSelectElement).value)}>{#each TRADE as t}<option value={t}>{t}</option>{/each}</select></td>
            <td class="small muted">{a.restrictions.map((r) => r.replace(/_/g, ' ')).join(', ')}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>

<style>
  .edit { border: 1px dashed var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; display: grid; gap: 10px; }
  .row { display: flex; gap: 14px; flex-wrap: wrap; align-items: center; }
  .row label { display: flex; gap: 6px; align-items: center; font-size: 13px; }
  .row input[type=number] { width: 64px; padding: 4px 6px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); }
  .row input:not([type]) { padding: 4px 6px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); }
  .bars { position: relative; height: 14px; background: color-mix(in oklab, var(--seq-250) 30%, var(--surface)); border-radius: 4px; }
  .bar { position: absolute; inset: 0 auto 0 0; border-radius: 4px; }
  .marker { position: absolute; top: -3px; bottom: -3px; width: 2px; background: var(--ink); }
</style>
