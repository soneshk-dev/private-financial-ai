<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Entity, type PnlRow, type ReviewItem } from '$lib/api';
  import { chart, baseOptions, barDataset, series } from '$lib/charts';
  import { money, monthLabel } from '$lib/format';

  let entities: Entity[] = $state([]);
  let selected = $state('');
  let rows: PnlRow[] = $state([]);
  let queue: ReviewItem[] = $state([]);
  let months = $state(12);
  let loading = $state(true);

  async function load() {
    loading = true;
    [entities, queue] = await Promise.all([api.entities(months), api.review()]);
    if (!selected) selected = entities.find((e) => e.kind === 'business')?.slug ?? entities[0]?.slug ?? '';
    rows = selected ? await api.pnl(selected, months) : [];
    loading = false;
  }
  onMount(load);

  const cfg = $derived.by(() => {
    if (!rows.length) return null;
    const o = baseOptions();
    o.scales.x.stacked = true; o.scales.y.stacked = true;
    return { type: 'bar', data: { labels: rows.map((r) => monthLabel(r.month)), datasets: [
      barDataset('Revenue', rows.map((r) => r.revenue), series(1), { stack: 'in' }),
      barDataset('Expenses', rows.map((r) => r.expenses), series(2), { stack: 'out' }),
      barDataset('Taxes', rows.map((r) => r.taxes), series(4), { stack: 'out', borderWidth: 2 }),
    ] }, options: o } as any;
  });

  async function assign(item: ReviewItem, entity: string) {
    if (!entity) return;
    await api.patchTxn(item.id, { entity, ...(entity !== 'personal' && item.flow === 'transfer' ? {} : {}) });
    queue = queue.filter((q) => q.id !== item.id);
    if (entity === selected) rows = await api.pnl(selected, months);
  }
  const bizEntities = $derived(entities.filter((e) => e.kind !== 'personal'));
</script>

<div class="page-head"><h1>Business</h1><div class="sub">per-entity P&L from tagged accounts and transactions</div></div>
<div class="filters">
  <select bind:value={selected} onchange={load}>{#each entities as e}<option value={e.slug}>{e.name}</option>{/each}</select>
  {#each [[6, '6 mo'], [12, '12 mo'], [24, '24 mo']] as [m, l]}
    <button class="chip" class:on={months === m} onclick={() => { months = m as number; load(); }}>{l}</button>
  {/each}
</div>

<div class="grid kpis" class:loading>
  {#each entities as e}
    <div class="card tile" style="cursor:pointer" onclick={() => { selected = e.slug; load(); }} role="button" tabindex="0" onkeydown={(k) => k.key === 'Enter' && (selected = e.slug, load())}>
      <div class="label">{e.name} <span class="muted">· {e.accounts} acct · {e.transactions} txns</span></div>
      <div class="value">{money(e.net)}</div>
      <div class="delta">revenue {money(e.revenue)} · expenses {money(e.expenses)} · {months} mo</div>
    </div>
  {/each}
</div>

<div class="grid two" style="margin-top:16px" class:loading>
  <div class="card">
    <h2>{entities.find((e) => e.slug === selected)?.name ?? ''} by month</h2>
    <div class="chart-box"><canvas use:chart={cfg}></canvas></div>
    <table class="data" style="margin-top:10px"><thead><tr><th>Month</th><th class="num">Revenue</th><th class="num">Expenses</th><th class="num">Taxes</th><th class="num">Transfers</th><th class="num">Net</th></tr></thead>
      <tbody>{#each [...rows].reverse() as r}<tr><td>{monthLabel(r.month)}</td><td class="num pos">{money(r.revenue)}</td><td class="num">{money(r.expenses)}</td><td class="num">{money(r.taxes)}</td><td class="num muted">{money(r.transfers)}</td><td class="num" class:pos={r.net > 0}>{money(r.net)}</td></tr>{/each}</tbody></table>
  </div>
  <div class="card">
    <h2>Review queue <span class="muted">· {queue.length} on personal accounts</span></h2>
    <p class="muted small" style="margin:0 0 10px">Charges that look like business activity, unclassified rows, and large unpaired transfers. Assign an entity to move them into that P&L; the override survives re-syncs.</p>
    <table class="data">
      <thead><tr><th>Date</th><th>What</th><th class="num">Amount</th><th>Assign</th></tr></thead>
      <tbody>
        {#each queue as q}
          <tr>
            <td class="muted small">{q.posted_at}</td>
            <td>{q.merchant ?? q.description}<div class="mono">{q.category ?? ''} · {q.reason}</div></td>
            <td class="num">{money(q.amount)}</td>
            <td class="inline-edit"><select onchange={(e) => assign(q, (e.target as HTMLSelectElement).value)}>
              <option value="">— keep personal —</option>{#each bizEntities as e}<option value={e.slug}>{e.name}</option>{/each}</select></td>
          </tr>
        {:else}<tr><td colspan="4" class="muted small">Nothing to review.</td></tr>{/each}
      </tbody>
    </table>
  </div>
</div>
