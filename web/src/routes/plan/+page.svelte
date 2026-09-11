<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Runway, type TaxEstimate, type Goal } from '$lib/api';
  import { chart, baseOptions, lineDataset, series } from '$lib/charts';
  import { money, compact, monthLabel, pct } from '$lib/format';
  import StatTile from '$lib/components/StatTile.svelte';
  import Meter from '$lib/components/Meter.svelte';

  let rw: Runway | null = $state(null);
  let tax: TaxEstimate | null = $state(null);
  let goals: Goal[] = $state([]);
  let loading = $state(true);
  onMount(async () => { [rw, tax, goals] = await Promise.all([api.runway(), api.tax(), api.goals()]); loading = false; });

  // One series (projected reserve), area wash; the story is when it crosses zero.
  const cfg = $derived.by(() => {
    if (!rw) return null;
    const o = baseOptions();
    o.plugins.legend.display = false;
    o.scales.x.ticks.maxTicksLimit = 9;
    return { type: 'line', data: { labels: rw.series.map((s) => monthLabel(s.month)),
      datasets: [lineDataset('Projected reserve', rw.series.map((s) => s.reserve), series(1), true)] }, options: o } as any;
  });
  const goalStatus = (g: Goal) => (g.pct === null ? 'ok' : g.pct >= 1 ? 'ok' : g.on_track === false ? 'warning' : 'ok');
</script>

<div class="page-head"><h1>Plan</h1><div class="sub">runway, goals and the tax estimate for the transition year</div></div>

{#if rw}
  <div class="grid kpis" class:loading>
    <StatTile label="Liquid reserve" value={rw.reserve} sub={rw.reserve_detail.map((d) => d.name).join(', ')} hero />
    <StatTile label="Monthly burn (avg {rw.burn.months_averaged} mo)" value={rw.burn.total} sub="spending {compact(rw.burn.spending)} · loans {compact(rw.burn.loan_payments)} · taxes {compact(rw.burn.taxes)}" />
    <StatTile label="Net per month now" value={rw.net_monthly_now} sub={rw.incomes.map((i) => `${i.name} ${compact(i.monthly)}${i.until ? ' to ' + i.until.slice(0, 7) : ''}`).join(' · ')} upIsGood />
    <div class="card tile">
      <div class="label">Runway</div>
      <div class="value">{rw.months_no_income ?? '—'} mo</div>
      <div class="delta">with no income · {rw.cliff_month ? `reserves negative in ${monthLabel(rw.cliff_month)}` : `positive through ${monthLabel(rw.series[rw.series.length - 1].month)}`}</div>
    </div>
  </div>

  <div class="grid two" style="margin-top:16px" class:loading>
    <div class="card">
      <h2>Projected reserve, {rw.series.length - 1} months</h2>
      <div class="chart-box"><canvas use:chart={cfg}></canvas></div>
      <table class="data" style="margin-top:10px"><thead><tr><th>Month</th><th class="num">Income</th><th class="num">Burn</th><th class="num">Reserve</th></tr></thead>
        <tbody>{#each rw.series.filter((_, i) => i % 3 === 0) as s}<tr><td>{monthLabel(s.month)}</td><td class="num">{money(s.income)}</td><td class="num">{money(-s.burn)}</td><td class="num" class:neg={s.reserve < 0}>{money(s.reserve)}</td></tr>{/each}</tbody></table>
    </div>
    <div class="card">
      <h2>Goals</h2>
      {#each goals as g}
        <Meter name="{g.name}{g.target_date ? ' · ' + g.target_date.slice(0, 7) : ''}" spent={g.current} limit={g.target_amount ?? g.current} status={goalStatus(g)} />
        <div class="muted small" style="margin:-4px 0 10px">
          {#if g.kind === 'debt'}remaining {money(g.remaining)}{:else}{money(g.remaining ?? 0)} to go{/if}
          {#if g.months_left !== null} · {g.months_left} months{/if}{#if g.needed_monthly} · needs {money(g.needed_monthly)}/mo{/if}{#if g.monthly_contribution} · saving {money(g.monthly_contribution)}/mo{/if}
        </div>
      {:else}<div class="muted small">No goals configured (private/config.yaml → goals).</div>{/each}
    </div>
  </div>
{/if}

{#if tax}
  <div class="card" style="margin-top:16px" class:loading>
    <div class="h2row"><h2>{tax.year} tax estimate ({tax.filing_status.toUpperCase()}) · as of {tax.as_of}</h2><span class="muted small">effective rate {pct(tax.effective_rate)}</span></div>
    <div class="grid two">
      <table class="data">
        <tbody>
          <tr><td>Wages <span class="muted small">{tax.income.wages_source}</span></td><td class="num">{money(tax.income.wages)}</td></tr>
          <tr><td>Other personal income</td><td class="num">{money(tax.income.other_personal_income)}</td></tr>
          <tr><td>Dividends & interest</td><td class="num">{money(tax.income.investment_income)}</td></tr>
          <tr><td>Business net</td><td class="num">{money(tax.income.business_net)}</td></tr>
          {#each Object.entries(tax.income.additional) as [k, v]}<tr><td>{k} <span class="muted small">config</span></td><td class="num">{money(v)}</td></tr>{/each}
          <tr><td><b>AGI</b></td><td class="num"><b>{money(tax.income.agi)}</b></td></tr>
          <tr><td>Standard deduction</td><td class="num">-{money(tax.deductions.standard)}</td></tr>
          <tr><td><b>Taxable income</b></td><td class="num"><b>{money(tax.taxable_income)}</b></td></tr>
        </tbody>
      </table>
      <table class="data">
        <tbody>
          <tr><td>Federal tax <span class="muted small">marginal {pct(tax.federal.marginal_rate)}</span></td><td class="num">{money(tax.federal.tax)}</td></tr>
          {#if tax.federal.niit}<tr><td>Net investment income tax</td><td class="num">{money(tax.federal.niit)}</td></tr>{/if}
          <tr><td>State tax ({pct(tax.state.rate)})</td><td class="num">{money(tax.state.tax)}</td></tr>
          <tr><td><b>Total estimated</b></td><td class="num"><b>{money(tax.total_tax)}</b></td></tr>
          <tr><td>Federal paid so far</td><td class="num">{money(tax.federal.paid)}</td></tr>
          <tr><td>State paid so far</td><td class="num">{money(tax.state.paid)}</td></tr>
          <tr><td><b>Remaining</b></td><td class="num"><b>{money(tax.federal.remaining + tax.state.remaining)}</b></td></tr>
          {#if tax.safe_harbor}<tr><td>Safe harbour ({tax.safe_harbor.multiplier * 100}% of prior year)</td><td class="num">{tax.safe_harbor.met ? '✓ met' : `short ${money(tax.safe_harbor.shortfall)}`}</td></tr>{/if}
          {#if tax.roth_headroom_in_bracket}<tr><td>Room left in current bracket</td><td class="num">{money(tax.roth_headroom_in_bracket)}</td></tr>{/if}
        </tbody>
      </table>
    </div>
    {#if tax.schedule.length}
      <h2 style="margin-top:14px">Remaining estimated payments</h2>
      <table class="data"><thead><tr><th>Due</th><th class="num">Federal</th><th class="num">State</th></tr></thead>
        <tbody>{#each tax.schedule as s}<tr><td>{s.due}</td><td class="num">{money(s.federal)}</td><td class="num">{money(s.state)}</td></tr>{/each}</tbody></table>
    {/if}
    <ul class="muted small" style="margin:12px 0 0; padding-left:18px">{#each tax.caveats as c}<li>{c}</li>{/each}</ul>
  </div>
{/if}
