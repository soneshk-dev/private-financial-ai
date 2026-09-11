<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type CashflowRow } from '$lib/api';
  import { chart, baseOptions, barDataset, series } from '$lib/charts';
  import { money, monthLabel } from '$lib/format';

  let rows: CashflowRow[] = $state([]);
  let months = $state(12);
  let entity = $state('');
  let loading = $state(true);
  async function load() { loading = true; rows = await api.cashflow(months, entity || undefined); loading = false; }
  onMount(load);

  // Income up, outflows stacked down, one axis, five series (legend + table).
  const cfg = $derived.by(() => {
    if (!rows.length) return null;
    const o = baseOptions();
    o.scales.x.stacked = true; o.scales.y.stacked = true;
    const labels = rows.map((r) => monthLabel(r.month));
    return {
      type: 'bar',
      data: { labels, datasets: [
        barDataset('Income', rows.map((r) => r.income), series(1), { stack: 'in' }),
        barDataset('Spending', rows.map((r) => r.spending), series(2), { stack: 'out', borderWidth: 2 }),
        barDataset('Loan payments', rows.map((r) => r.loan_payments), series(3), { stack: 'out', borderWidth: 2 }),
        barDataset('Taxes', rows.map((r) => r.taxes), series(4), { stack: 'out', borderWidth: 2 }),
        barDataset('Investing (net)', rows.map((r) => r.investing), series(5), { stack: 'out', borderWidth: 2 }),
      ] },
      options: o,
    } as any;
  });
  const totals = $derived({
    income: rows.reduce((s, r) => s + r.income, 0), spending: rows.reduce((s, r) => s + r.spending, 0),
    net: rows.reduce((s, r) => s + r.net, 0),
  });
</script>

<div class="page-head"><h1>Cash flow</h1><div class="sub">signed amounts, money out is negative; transfers between own accounts excluded</div></div>
<div class="filters">
  {#each [[6, '6 mo'], [12, '12 mo'], [24, '24 mo']] as [m, l]}
    <button class="chip" class:on={months === m} onclick={() => { months = m as number; load(); }}>{l}</button>
  {/each}
  <select bind:value={entity} onchange={load}><option value="">All entities</option><option value="personal">personal</option></select>
</div>

<div class="card" class:loading>
  <div class="h2row"><h2>Income vs outflows by month</h2><span class="muted small">{months} months: income {money(totals.income)} · spending {money(totals.spending)} · net {money(totals.net)}</span></div>
  <div class="chart-box tall"><canvas use:chart={cfg}></canvas></div>
</div>

<div class="card" style="margin-top:16px" class:loading>
  <h2>Table</h2>
  <table class="data">
    <thead><tr><th>Month</th><th class="num">Income</th><th class="num">Spending</th><th class="num">Loans</th><th class="num">Taxes</th><th class="num">Investing</th><th class="num">Transfers</th><th class="num">Net</th><th class="num">Txns</th></tr></thead>
    <tbody>
      {#each [...rows].reverse() as r}
        <tr><td>{monthLabel(r.month)}</td><td class="num pos">{money(r.income)}</td><td class="num">{money(r.spending)}</td><td class="num">{money(r.loan_payments)}</td><td class="num">{money(r.taxes)}</td><td class="num">{money(r.investing)}</td><td class="num muted">{money(r.transfers)}</td><td class="num" class:pos={r.net > 0}>{money(r.net)}</td><td class="num muted">{r.n}</td></tr>
      {/each}
    </tbody>
  </table>
</div>
