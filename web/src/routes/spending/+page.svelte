<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Spending, type Budget, type Txn } from '$lib/api';
  import { chart, baseOptions, barDataset, series } from '$lib/charts';
  import { money, monthLabel, thisMonth, shiftMonth, FLOWS } from '$lib/format';
  import Meter from '$lib/components/Meter.svelte';

  let month = $state(thisMonth());
  let sp: Spending | null = $state(null);
  let budgets: Budget[] = $state([]);
  let txns: Txn[] = $state([]);
  let category = $state('');
  let loading = $state(true);

  async function load() {
    loading = true;
    const start = month + '-01', end = shiftMonth(month, 1) + '-01';
    [sp, budgets, txns] = await Promise.all([api.spending(month), api.budgets(month),
      api.transactions({ start, end, category: category || undefined, limit: 500, pending: true })]);
    txns = txns.filter((t) => ['expense', 'fee', 'refund'].includes(t.flow) && t.posted_at < end);
    loading = false;
  }
  onMount(load);

  // Magnitude comparison across nominal categories: horizontal bars, one hue, sorted.
  const cfg = $derived.by(() => {
    if (!sp) return null;
    const rows = sp.by_level1.filter((r) => r.spent > 0).slice(0, 12);
    const o = baseOptions();
    o.indexAxis = 'y'; o.plugins.legend.display = false; o.interaction = { mode: 'nearest', axis: 'y', intersect: false };
    o.scales.x = { grid: { color: o.scales.y.grid.color, lineWidth: 1, drawTicks: false }, border: { display: false }, ticks: o.scales.y.ticks };
    o.scales.y = { grid: { display: false }, border: { color: o.scales.x.border?.color }, ticks: { color: o.scales.x.ticks.color, font: { size: 12 }, autoSkip: false } };
    return { type: 'bar', data: { labels: rows.map((r) => r.category), datasets: [barDataset('Spent', rows.map((r) => r.spent), series(1))] }, options: o } as any;
  });

  async function setFlow(t: Txn, flow: string) { await api.patchTxn(t.id, { flow_type: flow }); load(); }
  async function setCategory(t: Txn) {
    const c = prompt('Category (Level 1 > Sub):', t.category ?? '');
    if (c && c !== t.category) { await api.patchTxn(t.id, { category: c }); load(); }
  }
</script>

<div class="page-head"><h1>Spending</h1><div class="sub">{#if sp}{money(sp.total)} in {monthLabel(month)}{/if}</div></div>
<div class="filters">
  <button class="chip" onclick={() => { month = shiftMonth(month, -1); load(); }}>‹</button>
  <input type="month" bind:value={month} onchange={load} />
  <button class="chip" onclick={() => { month = shiftMonth(month, 1); load(); }} disabled={month >= thisMonth()}>›</button>
  <select bind:value={category} onchange={load}>
    <option value="">All categories</option>
    {#each sp?.by_level1 ?? [] as r}<option value={r.category}>{r.category}</option>{/each}
  </select>
</div>

<div class="grid two" class:loading>
  <div class="card">
    <h2>By category</h2>
    <div class="chart-box tall"><canvas use:chart={cfg}></canvas></div>
  </div>
  <div class="card">
    <h2>Budgets</h2>
    {#each budgets as b}<Meter name={b.category} spent={b.spent} limit={b.limit} status={b.status} />{:else}<div class="muted small">No budgets set.</div>{/each}
    <h2 style="margin-top:18px">Top merchants</h2>
    <table class="data"><tbody>
      {#each (sp?.top_merchants ?? []).slice(0, 10) as m}<tr><td>{m.merchant}</td><td class="num muted">{m.n}</td><td class="num">{money(m.spent)}</td></tr>{/each}
    </tbody></table>
  </div>
</div>

<div class="card" style="margin-top:16px" class:loading>
  <h2>Transactions ({txns.length})</h2>
  <table class="data">
    <thead><tr><th>Date</th><th>Description</th><th>Account</th><th>Category</th><th>Flow</th><th class="num">Amount</th></tr></thead>
    <tbody>
      {#each txns as t}
        <tr>
          <td class="muted small">{t.posted_at}{#if t.pending}<span class="badge" style="margin-left:6px">pending</span>{/if}</td>
          <td>{t.merchant ?? t.description}<div class="mono">{t.description}</div></td>
          <td class="small">{t.account_name}</td>
          <td class="small"><button class="btn" style="padding:2px 8px" onclick={() => setCategory(t)} title="Edit category">{t.category ?? '—'}</button></td>
          <td class="inline-edit"><select value={t.flow} onchange={(e) => setFlow(t, (e.target as HTMLSelectElement).value)}>{#each FLOWS as f}<option value={f}>{f}</option>{/each}</select></td>
          <td class="num" class:pos={t.amount > 0}>{money(t.amount, 2)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
