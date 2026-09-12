<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Txn, type Account } from '$lib/api';
  import { money, FLOWS } from '$lib/format';
  import CategoryPicker from '$lib/components/CategoryPicker.svelte';

  let txns: Txn[] = $state([]);
  let accounts: Account[] = $state([]);
  let f = $state({ q: '', flow: '', account_id: '', start: '', end: '', entity: '' });
  let limit = $state(200);
  let loading = $state(true);
  let t: any;

  async function load() { loading = true; txns = await api.transactions({ ...f, limit }); loading = false; }
  onMount(async () => { accounts = await api.accounts(true); load(); });
  const debounced = () => { clearTimeout(t); t = setTimeout(load, 250); };

  async function setFlow(x: Txn, flow: string) { await api.patchTxn(x.id, { flow_type: flow }); x.flow = flow; }
  let picking: Txn | null = $state(null);
  let toast = $state('');
  function applied(r: { id: string; category: string; scope: string; merchant: string; affected: number; rule_id: number | null }) {
    const key = r.merchant.toLowerCase();
    for (const x of txns) {
      if (x.id === r.id || (r.scope === 'merchant' && ((x.merchant ?? x.description ?? '').trim().toLowerCase() === key))) {
        x.category = r.category; x.category_l1 = r.category.split(' > ')[0];
      }
    }
    toast = `${r.category} → ${r.affected} transaction${r.affected === 1 ? '' : 's'}${r.rule_id ? ' · rule saved' : ''}`;
    setTimeout(() => (toast = ''), 4000);
  }
  const sum = $derived(txns.reduce((s, x) => s + x.amount, 0));
</script>

<div class="page-head"><h1>Transactions</h1><div class="sub">{txns.length} shown · sum {money(sum)}{#if toast} · <span class="badge good">{toast}</span>{/if}</div></div>
<div class="filters">
  <input placeholder="Search description or merchant" bind:value={f.q} oninput={debounced} style="min-width:260px" />
  <select bind:value={f.flow} onchange={load}><option value="">Any flow</option>{#each FLOWS as fl}<option value={fl}>{fl}</option>{/each}</select>
  <select bind:value={f.account_id} onchange={load}><option value="">Any account</option>{#each accounts as a}<option value={a.id}>{a.institution ? a.institution + ' · ' : ''}{a.name}</option>{/each}</select>
  <input type="date" bind:value={f.start} onchange={load} /><input type="date" bind:value={f.end} onchange={load} />
  <select bind:value={limit} onchange={load}><option value={200}>200</option><option value={500}>500</option><option value={2000}>2000</option></select>
</div>

<div class="card" class:loading>
  <table class="data">
    <thead><tr><th>Date</th><th>Description</th><th>Account</th><th>Category</th><th>Flow</th><th class="num">Amount</th></tr></thead>
    <tbody>
      {#each txns as x}
        <tr>
          <td class="muted small">{x.posted_at}{#if x.pending}<span class="badge" style="margin-left:6px">pending</span>{/if}{#if x.transfer_group}<span class="badge" title="paired transfer" style="margin-left:6px">⇄</span>{/if}</td>
          <td>{x.merchant ?? x.description}<div class="mono">{x.description}</div></td>
          <td class="small">{x.account_name}<div class="muted small">{x.entity}</div></td>
          <td class="small"><button class="btn" style="padding:2px 8px" title="Change category" onclick={() => (picking = x)}>{x.category ?? '—'}</button></td>
          <td class="inline-edit"><select value={x.flow} onchange={(e) => setFlow(x, (e.target as HTMLSelectElement).value)}>{#each FLOWS as fl}<option value={fl}>{fl}</option>{/each}</select></td>
          <td class="num" class:pos={x.amount > 0}>{money(x.amount, 2)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

{#if picking}
  <CategoryPicker txn={picking} onclose={() => (picking = null)} onapplied={applied} />
{/if}
