<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type NetWorth, type CashflowRow, type Budget } from '$lib/api';
  import { chart, baseOptions, lineDataset, series } from '$lib/charts';
  import { money, compact, CLASS_LABEL, KIND_LABEL, dateLabel, thisMonth } from '$lib/format';
  import StatTile from '$lib/components/StatTile.svelte';
  import Meter from '$lib/components/Meter.svelte';

  let nw: NetWorth | null = $state(null);
  let cf: CashflowRow[] = $state([]);
  let budgets: Budget[] = $state([]);
  let days = $state(365);
  let loading = $state(true);

  async function load() {
    loading = true;
    [nw, cf, budgets] = await Promise.all([api.netWorth(days), api.cashflow(3), api.budgets(thisMonth())]);
    loading = false;
  }
  onMount(load);

  const cfg = $derived.by(() => {
    if (!nw?.series?.length) return null;
    const o = baseOptions();
    o.plugins.legend.display = false;                       // single series: the title names it
    o.scales.x.ticks.maxTicksLimit = 8;
    return {
      type: 'line',
      data: { labels: nw.series.map((s) => dateLabel(s.as_of)), datasets: [lineDataset('Net worth', nw.series.map((s) => s.net_worth), series(1), true)] },
      options: o,
    } as any;
  });
  const classes = $derived(nw ? Object.entries(nw.by_class).filter(([k]) => k !== 'liability').sort((a, b) => b[1] - a[1]) : []);
  const thisCf = $derived(cf.find((r) => r.month === thisMonth()) ?? cf[cf.length - 1]);
  const attention = $derived(budgets.filter((b) => b.status !== 'ok').sort((a, b) => (b.pct ?? 0) - (a.pct ?? 0)).slice(0, 5));
</script>

<div class="page-head">
  <h1>Overview</h1>
  <div class="sub">{#if nw}as of {nw.as_of}{/if}</div>
</div>

<div class="filters">
  {#each [[90, '90d'], [365, '1y'], [1095, '3y']] as [d, l]}
    <button class="chip" class:on={days === d} onclick={() => { days = d as number; load(); }}>{l}</button>
  {/each}
</div>

<div class="grid kpis" class:loading>
  <StatTile label="Net worth" value={nw?.net_worth} delta={nw?.change ?? null} deltaLabel="over {days} days" hero />
  <StatTile label="Assets" value={nw?.assets} />
  <StatTile label="Debt" value={nw?.liabilities} sub="cards, mortgage, HELOC" />
  <StatTile label="This month spending" value={thisCf ? -thisCf.spending : null} sub={thisCf ? `income ${compact(thisCf.income)}` : ''} />
</div>

<div class="grid two" style="margin-top:16px" class:loading>
  <div class="card">
    <h2>Net worth over time</h2>
    <div class="chart-box"><canvas use:chart={cfg}></canvas></div>
  </div>
  <div class="card">
    <h2>By asset class</h2>
    <table class="data">
      <tbody>
        {#each classes as [k, v], i}
          <tr><td><i class="dot" style="display:inline-block;width:10px;height:10px;border-radius:2px;background:var(--series-{Math.min(i + 1, 8)});margin-right:8px"></i>{CLASS_LABEL[k] ?? k}</td><td class="num">{money(v)}</td></tr>
        {/each}
        {#if nw}<tr><td>Debt</td><td class="num">-{money(nw.liabilities)}</td></tr>{/if}
      </tbody>
    </table>
    {#if attention.length}
      <h2 style="margin-top:18px">Budgets needing attention</h2>
      {#each attention as b}<Meter name={b.category} spent={b.spent} limit={b.limit} status={b.status} />{/each}
    {/if}
  </div>
</div>

{#if nw}
  <div class="card" style="margin-top:16px">
    <h2>Accounts</h2>
    <table class="data">
      <thead><tr><th>Account</th><th>Kind</th><th>Institution</th><th>Entity</th><th class="num">Balance</th><th>As of</th></tr></thead>
      <tbody>
        {#each Object.entries(nw.accounts_by_class) as [cls, accts]}
          <tr><td colspan="6" class="muted small" style="padding-top:12px">{CLASS_LABEL[cls] ?? cls}</td></tr>
          {#each accts as a}
            <tr><td>{a.name}</td><td>{KIND_LABEL[a.kind] ?? a.kind}</td><td>{a.institution ?? ''}</td><td class="muted">{a.entity}</td><td class="num">{money(a.balance)}</td><td class="muted small">{a.as_of ?? '—'}</td></tr>
          {/each}
        {/each}
      </tbody>
    </table>
  </div>
{/if}
