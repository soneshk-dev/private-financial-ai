<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Projections, type GoalProjection, type Band } from '$lib/api';
  import { chart, baseOptions, lineDataset, series, withAlpha } from '$lib/charts';
  import { money, compact } from '$lib/format';

  let data = $state<Projections | null>(null);
  let err = $state('');
  let busy = $state(false);
  let editing = $state<string | null>(null);
  let gd = $state<Record<string, string>>({});
  let rd = $state<Record<string, string>>({});
  let editRet = $state(false);

  async function load() { busy = true; try { data = await api.projections(); } finally { busy = false; } }
  onMount(load);
  const clean = (e: any) => String(e.message ?? e).replace(/^\d+\s*/, '');
  const num = (v: string) => (v === '' || v === undefined ? null : Number(v));

  // Fan: p10-p90 band as a filled pair, median as the line. One hue; the band is the same hue at low alpha.
  function fan(points: Band[], labels: string[], target?: number | null) {
    const o = baseOptions();
    o.plugins.legend.display = false;
    o.scales.x.ticks.maxTicksLimit = 8;
    const c = series(1);
    const band = (label: string, vals: number[], fill: any) => ({ label, data: vals, borderColor: withAlpha(c, 0.35), borderWidth: 1, pointRadius: 0, pointHitRadius: 10, tension: 0.25, fill, backgroundColor: withAlpha(c, 0.12) });
    const ds: any[] = [];
    if (points[0]?.p90 !== undefined) { ds.push(band('Strong markets (90th pct)', points.map((p) => p.p90!), false)); ds.push(band('Weak markets (10th pct)', points.map((p) => p.p10!), '-1')); }
    ds.push(lineDataset('Median', points.map((p) => p.p50), c));
    if (target) ds.push({ label: 'Target', data: points.map(() => target), borderColor: series(3), borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0, fill: false });
    return { type: 'line', data: { labels, datasets: ds }, options: o } as any;
  }
  const yearLabel = (m: number) => { const d = new Date(); d.setMonth(d.getMonth() + m); return `${d.getFullYear()}`; };

  function startGoal(g: GoalProjection) {
    editing = g.slug; err = '';
    gd = { monthly_contribution: String(g.monthly_contribution ?? ''), target_amount: String(g.target_amount ?? ''), target_date: String(g.target_date ?? '').slice(0, 10),
           return_pct: String(g.overrides.return_pct ?? ''), vol_pct: String(g.overrides.vol_pct ?? ''),
           debt_rate_pct: String(g.overrides.debt_rate_pct ?? g.projection.rate_pct ?? ''), monthly_payment: String(g.overrides.monthly_payment ?? '') };
  }
  async function saveGoal(g: GoalProjection) {
    const body: Record<string, unknown> = {};
    const keys = g.kind === 'debt' ? ['debt_rate_pct', 'monthly_payment'] : ['monthly_contribution', 'target_amount', 'target_date', 'return_pct', 'vol_pct'];
    for (const k of keys) body[k] = k === 'target_date' ? (gd[k] || null) : num(gd[k]);
    try { await api.savePlan({ goals: { [g.slug]: body } }); editing = null; await load(); } catch (e) { err = clean(e); }
  }
  function startRet() {
    const r = data!.retirement.settings; editRet = true; err = '';
    rd = { current_age: String(r.current_age ?? ''), retire_age: String(r.retire_age), end_age: String(r.end_age), annual_spend: String(r.annual_spend ?? ''),
           annual_contribution: String(r.annual_contribution), other_income: String(r.other_income), other_income_age: String(r.other_income_age), crypto_haircut_pct: String(r.crypto_haircut_pct) };
  }
  async function saveRet() {
    const body: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(rd)) body[k] = num(v);
    try { await api.savePlan({ retirement: body }); editRet = false; await load(); } catch (e) { err = clean(e); }
  }
  const prob = (p?: number) => (p === undefined || p === null ? '—' : `${Math.round(p * 100)}%`);
  const probClass = (p: number | undefined, conf: number) => (p === undefined ? '' : p >= conf ? 'good' : p >= conf - 0.25 ? 'warn' : 'bad');
</script>

{#if data}
  <div class="card" style="margin-top:16px" class:loading={busy}>
    <h2>Goal projections <span class="muted small">— {data.settings.paths} simulated market paths; on track means at least {data.settings.confidence_pct}% of them reach the target</span></h2>
    {#if err}<p><span class="badge bad">{err}</span></p>{/if}
    <div class="grid two">
      {#each data.goals.filter((g) => g.projection.kind !== 'none') as g}
        {@const p = g.projection}
        <div class="goal">
          <div class="h2row"><b>{g.name}</b><button class="btn" onclick={() => (editing === g.slug ? (editing = null) : startGoal(g))}>{editing === g.slug ? 'Cancel' : 'Edit'}</button></div>
          {#if p.kind === 'save'}
            <div class="stats"><span class="badge {probClass(p.probability, (p.confidence_pct ?? 80) / 100)}">{prob(p.probability)} chance of {compact(g.target_amount)} by {String(g.target_date).slice(0, 7)}</span>
              <span>now {compact(g.current)}</span><span>saving {money(g.monthly_contribution ?? 0)}/mo</span>
              {#if p.required_monthly}<span>needs about <b>{money(p.required_monthly)}/mo</b> for {p.confidence_pct}%</span>{:else if p.required_monthly === 0}<span class="muted">no further saving needed at {p.confidence_pct}%</span>{/if}</div>
            <div class="chart-box" style="height:180px"><canvas use:chart={fan(p.series ?? [], (p.series ?? []).map((x) => yearLabel(x.month ?? 0)), g.target_amount)}></canvas></div>
            <div class="muted small">Range at the date: {compact(p.end?.p10)} weak · {compact(p.end?.p50)} median · {compact(p.end?.p90)} strong. Assumes {p.return_pct}% return, {p.vol_pct}% volatility ({p.basis}).</div>
          {:else}
            <div class="stats"><span class="badge {p.payoff_months ? 'good' : 'warn'}">{p.payoff_months ? `paid off in ${Math.floor(p.payoff_months / 12)}y ${p.payoff_months % 12}m` : 'set a monthly payment above the interest to see a payoff date'}</span>
              <span>balance {compact(g.current)}</span><span>interest about {money(p.interest_per_month_now ?? 0)}/mo at {p.rate_pct}%</span><span>paying {money(p.monthly_payment ?? 0)}/mo</span></div>
            {#if (p.series ?? []).length > 1}<div class="chart-box" style="height:180px"><canvas use:chart={fan(p.series ?? [], (p.series ?? []).map((x) => yearLabel(x.month ?? 0)))}></canvas></div>{/if}
          {/if}
          {#if editing === g.slug}
            <div class="row">
              {#if g.kind === 'debt'}
                <label>Rate % <input bind:value={gd.debt_rate_pct} /></label><label>Monthly payment $ <input bind:value={gd.monthly_payment} /></label>
              {:else}
                <label>Saving $/mo <input bind:value={gd.monthly_contribution} /></label><label>Target $ <input bind:value={gd.target_amount} style="width:100px" /></label>
                <label>Date <input type="date" bind:value={gd.target_date} style="width:140px" /></label>
                <label>Return % <input bind:value={gd.return_pct} placeholder="auto" /></label><label>Volatility % <input bind:value={gd.vol_pct} placeholder="auto" /></label>
              {/if}
              <button class="btn primary" onclick={() => saveGoal(g)}>Save</button></div>
          {/if}
        </div>
      {/each}
    </div>
    {#each data.goals.filter((g) => g.projection.kind === 'none' && g.kind !== 'reserve') as g}
      <div class="row" style="margin-top:10px"><span class="muted small"><b>{g.name}</b>: {g.projection.reason}.</span>
        {#if editing === g.slug}<label>Target $ <input bind:value={gd.target_amount} style="width:100px" /></label><label>Date <input type="date" bind:value={gd.target_date} style="width:140px" /></label><label>Saving $/mo <input bind:value={gd.monthly_contribution} /></label><button class="btn primary" onclick={() => saveGoal(g)}>Save</button>
        {:else}<button class="btn" onclick={() => startGoal(g)}>Set</button>{/if}</div>
    {/each}
  </div>

  {@const r = data.retirement}
  <div class="card" style="margin-top:16px" class:loading={busy}>
    <div class="h2row"><h2>Retirement <span class="muted small">— today's dollars, returns net of {r.inflation_pct}% inflation</span></h2>
      <button class="btn" onclick={() => (editRet ? (editRet = false) : startRet())}>{editRet ? 'Cancel' : 'Edit inputs'}</button></div>
    {#if editRet}
      <div class="row" style="margin-bottom:10px">
        <label>Your age <input bind:value={rd.current_age} /></label><label>Retire at <input bind:value={rd.retire_age} /></label><label>Plan to age <input bind:value={rd.end_age} /></label>
        <label>Spending $/yr <input bind:value={rd.annual_spend} placeholder={String(r.annual_spend)} style="width:100px" /></label>
        <label>Saving $/yr until then <input bind:value={rd.annual_contribution} style="width:90px" /></label>
        <label>Other income $/yr <input bind:value={rd.other_income} style="width:90px" /></label><label>from age <input bind:value={rd.other_income_age} /></label>
        <label>Crypto haircut % <input bind:value={rd.crypto_haircut_pct} /></label>
        <button class="btn primary" onclick={saveRet}>Save</button></div>
    {/if}
    <div class="stats">
      <span>Counted assets <b>{compact(r.assets)}</b></span><span>Spending <b>{compact(r.annual_spend)}/yr</b> <span class="muted">({r.annual_spend_source})</span></span>
      <span>4% of assets today = {compact(r.four_pct_spend)}/yr</span><span>Spending needs {compact(r.needed_at_4pct)} at 4%</span>
      <span class="muted">mix implies {r.real_return_pct}% real return, {r.vol_pct}% volatility</span></div>
    {#if r.ready}
      <div class="stats"><span class="badge {probClass(r.success_probability, 0.8)}">{prob(r.success_probability)} of paths last to age {r.settings.end_age}</span>
        <span>At {r.at_retirement?.age}: {compact(r.at_retirement?.p10)} weak · <b>{compact(r.at_retirement?.p50)}</b> median · {compact(r.at_retirement?.p90)} strong</span></div>
      <div class="chart-box" style="height:220px"><canvas use:chart={fan(r.series ?? [], (r.series ?? []).map((x) => `age ${x.age}`))}></canvas></div>
      <div class="muted small">{r.note} Crypto is counted at {100 - r.settings.crypto_haircut_pct}% of its value. Reserve and earmarked money are excluded.</div>
    {:else}<p class="muted">{r.reason}. Use "Edit inputs".</p>{/if}
  </div>
{/if}

<style>
  .goal { border-top: 1px solid var(--grid); padding-top: 10px; }
  .stats { display: flex; gap: 14px; flex-wrap: wrap; font-size: 13px; align-items: center; margin: 6px 0; }
  .row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-top: 8px; }
  .row label { display: flex; gap: 6px; align-items: center; font-size: 13px; }
  input { width: 70px; padding: 5px 7px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--ink); font: inherit; }
</style>
