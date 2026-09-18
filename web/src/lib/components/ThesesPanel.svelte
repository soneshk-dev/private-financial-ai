<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Thesis, type ThesisBudget, type Analysis, type RegistryAccount } from '$lib/api';
  import { money, compact } from '$lib/format';

  let { accounts, onchanged }: { accounts: RegistryAccount[]; onchanged: () => void } = $props();
  let theses = $state<Thesis[]>([]);
  let budget = $state<ThesisBudget | null>(null);
  let err = $state('');
  let showNew = $state(false);
  let draft = $state({ name: '', view: '', budget_pct: 25, horizon_end: '', benchmark: 'SPY', exit_rules: '', conviction: 2, kill: '' });
  let legFor = $state<string | null>(null);
  let leg = $state({ symbol: '', account_id: '', quantity: '', entry_price: '', direction: 'long' });
  let an = $state({ symbols: '', amount: 25000, holding_months: 12, expected_return_pct: 10 });
  let analysis = $state<Analysis | null>(null);
  let busy = $state(false);

  const tradable = $derived(accounts.filter((a) => ['open', 'menu'].includes(a.tradability) && ['core', 'thesis'].includes(a.role)));
  async function load() { const r = await api.theses(); theses = r.theses; budget = r.budget; }
  onMount(load);
  const clean = (e: any) => String(e.message ?? e).replace(/^\d+\s*/, '');

  // "wti_usd > 110, ust_10y > 5.5, price:TLT < 80"
  function parseKill(text: string) {
    return text.split(',').map((x) => x.trim()).filter(Boolean).map((x) => {
      const m = x.match(/^([\w:.]+)\s*([<>])\s*([\d.]+)$/);
      if (!m) throw new Error(`kill metric "${x}" should look like wti_usd > 110`);
      return { series: m[1], op: m[2], level: Number(m[3]) };
    });
  }
  async function create() {
    err = '';
    try {
      await api.saveThesis({ name: draft.name, view: draft.view, budget_pct: Number(draft.budget_pct), horizon_end: draft.horizon_end || undefined,
        benchmark: draft.benchmark || undefined, exit_rules: draft.exit_rules || undefined, conviction: Number(draft.conviction), status: 'active', kill_metrics: parseKill(draft.kill) });
      showNew = false; draft = { ...draft, name: '', view: '', exit_rules: '', kill: '' }; await load(); onchanged();
    } catch (e) { err = clean(e); }
  }
  async function setStatus(t: Thesis, status: string) { await api.saveThesis({ slug: t.slug, status }); await load(); onchanged(); }
  async function addLeg(slug: string) {
    err = '';
    try {
      await api.saveLeg(slug, { symbol: leg.symbol, direction: leg.direction, account_id: leg.account_id || undefined,
        quantity: leg.quantity === '' ? undefined : Number(leg.quantity), entry_price: leg.entry_price === '' ? undefined : Number(leg.entry_price), opened_at: new Date().toISOString().slice(0, 10) });
      legFor = null; leg = { symbol: '', account_id: '', quantity: '', entry_price: '', direction: 'long' }; await load(); onchanged();
    } catch (e) { err = clean(e); }
  }
  async function removeLeg(slug: string, id: number) { await api.deleteLeg(slug, id); await load(); onchanged(); }
  async function analyze() {
    busy = true; err = '';
    try { analysis = await api.analyze(an); } catch (e) { err = clean(e); } finally { busy = false; }
  }
  const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v}%`);
</script>

<div class="card" style="margin-top:16px">
  <div class="h2row">
    <h2>Theses <span class="muted small">— 6 to 24 month views, sized inside the thesis cap</span></h2>
    <div>{#if budget}<span class="muted small">deployed {compact(budget.deployed)} of {compact(budget.cap)} · {budget.allocated_pct_of_cap}% of cap budgeted&nbsp;</span>{/if}
      <button class="btn" onclick={() => (showNew = !showNew)}>{showNew ? 'Cancel' : 'New thesis'}</button></div>
  </div>
  {#if err}<p><span class="badge bad">{err}</span></p>{/if}
  {#if showNew}
    <div class="edit">
      <div class="row"><label>Name <input bind:value={draft.name} placeholder="Oil and rates roll over" style="width:240px" /></label>
        <label>Budget % of cap <input type="number" min="0" max="100" bind:value={draft.budget_pct} /></label>
        <label>Horizon end <input type="date" bind:value={draft.horizon_end} /></label>
        <label>Benchmark <input bind:value={draft.benchmark} style="width:70px" /></label>
        <label>Conviction <select bind:value={draft.conviction}><option value={1}>low</option><option value={2}>medium</option><option value={3}>high</option></select></label></div>
      <label class="col">The view, in your words <textarea rows="2" bind:value={draft.view} placeholder="What you believe, why, and by when"></textarea></label>
      <label class="col">Exit rules <input bind:value={draft.exit_rules} placeholder="Take half off at +25%; out entirely if the view is wrong by March" /></label>
      <label class="col">Kill metrics <input bind:value={draft.kill} placeholder="wti_usd > 110, ust_10y > 5.5, price:TLT < 80" />
        <span class="muted small">series: wti_usd, ust_2y, ust_10y, ust_30y, btc_usd, eth_usd, or price:SYMBOL. Checked daily; a breach alerts you on Telegram.</span></label>
      <div class="row"><button class="btn primary" onclick={create} disabled={!draft.name || !draft.view}>Create</button></div>
    </div>
  {/if}

  {#if !theses.length && !showNew}<p class="muted">No theses yet. Create one to give a view a budget, a horizon and kill metrics.</p>{/if}
  {#each theses as t}
    <div class="thesis">
      <div class="h2row">
        <div><b>{t.name}</b> <span class="badge" class:good={t.status === 'active'}>{t.status}</span>
          {#if t.kill_breached}<span class="badge bad">kill metric hit</span>{/if}{#if t.expired}<span class="badge warn">past horizon</span>{/if}{#if t.over_budget}<span class="badge warn">over budget</span>{/if}</div>
        <div class="small">
          {#if t.status === 'draft'}<button class="btn" onclick={() => setStatus(t, 'active')}>Activate</button>{/if}
          <button class="btn" onclick={() => setStatus(t, 'closed')}>Close</button></div>
      </div>
      <p class="view">{t.view}</p>
      <div class="stats">
        <span>Budget <b>{compact(t.budget)}</b> <span class="muted">({t.budget_pct}% of cap)</span></span>
        <span>Deployed <b>{compact(t.deployed)}</b></span>
        <span>P&amp;L <b class:pos={(t.pnl ?? 0) > 0} class:neg={(t.pnl ?? 0) < 0}>{t.pnl === null ? '—' : money(t.pnl)}</b> <span class="muted">{pct(t.return_pct)}</span></span>
        {#if t.benchmark}<span>{t.benchmark} since start <b>{pct(t.benchmark_return_pct)}</b></span>{/if}
        {#if t.horizon_end}<span>Horizon {t.horizon_end} <span class="muted">({t.days_left} days left)</span></span>{/if}
      </div>
      {#if t.horizon_pct !== undefined}<div class="meter" style="padding:4px 0 8px"><div class="track"><div class="fill" class:over={t.expired} style="width:{t.horizon_pct}%"></div></div></div>{/if}
      {#if t.kill_metrics.length}
        <div class="stats">{#each t.kill_metrics as m}<span class="badge" class:bad={m.breached}>{m.series} {m.op} {m.level} · now {m.value ?? '?'}{m.distance_pct != null ? ` (${pct(m.distance_pct)} away)` : ''}</span>{/each}</div>
      {/if}
      {#if t.exit_rules}<p class="small muted">Exit: {t.exit_rules}</p>{/if}
      {#if t.legs.length}
        <table class="data">
          <thead><tr><th>Leg</th><th>Account</th><th class="num">Qty</th><th class="num">Entry</th><th class="num">Price</th><th class="num">Value</th><th class="num">P&amp;L</th><th></th></tr></thead>
          <tbody>{#each t.legs as l}
            <tr><td>{l.symbol} <span class="muted small">{l.direction}{l.closed_at ? ' · closed' : ''}</span></td><td class="small">{l.account_name ?? '—'}</td>
              <td class="num">{l.quantity ?? '—'}{#if l.quantity_source}<span class="muted small"> held</span>{/if}</td>
              <td class="num">{l.entry_price_used ? money(l.entry_price_used, 2) : '—'}</td><td class="num">{l.price ? money(l.price, 2) : 'not priced yet'}</td>
              <td class="num">{money(l.value)}</td><td class="num" class:pos={(l.pnl ?? 0) > 0} class:neg={(l.pnl ?? 0) < 0}>{l.pnl === null ? '—' : money(l.pnl)} <span class="muted small">{pct(l.return_pct)}</span></td>
              <td class="num"><button class="btn" onclick={() => removeLeg(t.slug, l.id)}>×</button></td></tr>
          {/each}</tbody>
        </table>
      {/if}
      {#if legFor === t.slug}
        <div class="row" style="margin-top:8px"><input placeholder="Symbol" bind:value={leg.symbol} style="width:80px" />
          <select bind:value={leg.direction}><option value="long">long</option><option value="underweight">underweight (note only)</option></select>
          <select bind:value={leg.account_id}><option value="">account…</option>{#each tradable as a}<option value={a.id}>{a.name} · {a.tax_treatment.replace(/_/g, ' ')}</option>{/each}</select>
          <input placeholder="Qty (blank = track holding)" bind:value={leg.quantity} style="width:170px" /><input placeholder="Entry price" bind:value={leg.entry_price} style="width:100px" />
          <button class="btn primary" onclick={() => addLeg(t.slug)} disabled={!leg.symbol}>Add</button><button class="btn" onclick={() => (legFor = null)}>Cancel</button></div>
      {:else}<button class="btn" style="margin-top:8px" onclick={() => (legFor = t.slug)}>Add leg</button>{/if}
    </div>
  {/each}
</div>

<div class="card" style="margin-top:16px">
  <h2>Frame an expression <span class="muted small">— where it would live, what the tax is, how it fits</span></h2>
  <div class="row"><label>Symbols <input bind:value={an.symbols} placeholder="TLT, XHB, JETS" style="width:200px" /></label>
    <label>Amount $ <input type="number" step="1000" bind:value={an.amount} style="width:100px" /></label>
    <label>Hold (months) <input type="number" min="1" max="60" bind:value={an.holding_months} /></label>
    <label>Expected return % <input type="number" bind:value={an.expected_return_pct} /></label>
    <button class="btn primary" onclick={analyze} disabled={busy || !an.symbols}>{busy ? 'Working…' : 'Analyze'}</button></div>
  {#if analysis}
    <p class="small muted">{analysis.rates.basis}. Tax on gains in a taxable account: {Math.round(analysis.rates.short_term_total * 100)}% under 12 months, {Math.round(analysis.rates.long_term_total * 100)}% over.
      Thesis budget: {compact(analysis.thesis_budget.remaining)} remaining of {compact(analysis.thesis_budget.cap)};
      <span class="badge" class:good={analysis.thesis_budget.fits} class:bad={!analysis.thesis_budget.fits}>{analysis.thesis_budget.fits ? 'fits' : 'exceeds the cap'}</span></p>
    {#each analysis.candidates as c}
      <div class="thesis">
        <div class="stats"><b>{c.symbol}</b>
          <span>{c.price ? `${money(c.price.close, 2)} (${c.price.as_of})` : 'no price found'}</span><span>1m {pct(c.return_1m_pct)}</span><span>3m {pct(c.return_3m_pct)}</span>
          <span>{c.class.replace(/_/g, ' ')}: {c.class_now_pct ?? '—'}% → {c.class_after_pct ?? '—'}%{c.class_policy_pct != null ? ` (policy ${c.class_policy_pct}%)` : ''}</span>
          {#if c.already_held_value}<span class="badge warn">already hold {compact(c.already_held_value)}</span>{/if}</div>
        <table class="data">
          <thead><tr><th>Account</th><th>Tax</th><th class="num">Tax on gain</th><th class="num">After-tax gain</th><th class="num">Cash there</th><th>Note</th></tr></thead>
          <tbody>{#each c.placement as o, i}
            <tr><td>{#if i === 0}<span class="badge good">lowest tax</span> {/if}{o.account}</td><td class="small">{o.tax_treatment.replace(/_/g, ' ')}</td>
              <td class="num">{money(o.tax_on_expected_gain)}</td><td class="num">{money(o.after_tax_gain)}</td>
              <td class="num" class:neg={!o.funded_from_cash}>{money(o.cash_available)}</td><td class="small muted">{o.note}</td></tr>
          {/each}</tbody>
        </table>
      </div>
    {/each}
    <p class="small muted">{analysis.note}</p>
  {/if}
</div>

<style>
  .edit { border: 1px dashed var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; display: grid; gap: 10px; }
  .row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
  .row label, .col { display: flex; gap: 6px; align-items: center; font-size: 13px; }
  .col { flex-direction: column; align-items: stretch; }
  input, select, textarea { padding: 5px 7px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--ink); font: inherit; }
  input[type=number] { width: 70px; }
  .thesis { border-top: 1px solid var(--grid); padding: 12px 0; }
  .view { margin: 6px 0; }
  .stats { display: flex; gap: 16px; flex-wrap: wrap; font-size: 13px; align-items: center; margin: 4px 0; }
</style>
