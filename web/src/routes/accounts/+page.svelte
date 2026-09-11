<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Account, type Health } from '$lib/api';
  import { money, KIND_LABEL, KINDS } from '$lib/format';

  let accounts: Account[] = $state([]);
  let health: Health | null = $state(null);
  let showInactive = $state(false);
  let syncing = $state(false);
  let syncMsg = $state('');
  let loading = $state(true);

  async function load() { loading = true; [accounts, health] = await Promise.all([api.accounts(showInactive), api.health()]); loading = false; }
  onMount(load);

  async function setKind(a: Account, kind: string) { await api.patchAccount(a.id, { kind }); load(); }
  async function setEntity(a: Account) {
    const e = prompt('Entity (personal or business:<slug>):', a.entity);
    if (e && e !== a.entity) { await api.patchAccount(a.id, { entity: e }); load(); }
  }
  async function toggleActive(a: Account) { await api.patchAccount(a.id, { is_active: !a.is_active }); load(); }
  async function sync() {
    syncing = true; syncMsg = 'syncing…';
    try { const r = await api.sync(); syncMsg = r.connectors.map((c: any) => `${c.connector}: ${c.skipped ? 'skipped' : c.ok ? 'ok' : 'error'}`).join(' · '); }
    catch (e: any) { syncMsg = e.message; }
    syncing = false; load();
  }
  const badge = (s: string) => (s === 'ok' || s === 'active' ? 'good' : s === 'never' || s === 'removed' ? '' : s === 'login_required' ? 'warn' : 'bad');
</script>

<div class="page-head"><h1>Accounts & data</h1><div class="sub">{accounts.length} accounts</div></div>
<div class="filters">
  <button class="chip" class:on={showInactive} onclick={() => { showInactive = !showInactive; load(); }}>show inactive</button>
  <button class="btn primary" onclick={sync} disabled={syncing}>{syncing ? 'Syncing…' : 'Sync now'}</button>
  <span class="muted small">{syncMsg}</span>
</div>

{#if health}
  <div class="grid two">
    <div class="card">
      <h2>Connectors</h2>
      <table class="data"><tbody>
        {#each health.connectors as c}
          <tr><td>{c.connector}</td><td><span class="badge {badge(c.status)}">{c.status}</span></td><td class="muted small">{c.last_success_at?.slice(0, 16).replace('T', ' ') ?? 'never'}</td><td class="small">{c.last_error ?? ''}</td></tr>
        {/each}
      </tbody></table>
    </div>
    <div class="card">
      <h2>Connections</h2>
      <table class="data"><tbody>
        {#each health.connections.filter((c) => c.status !== 'removed') as c}
          <tr><td>{c.institution}</td><td><span class="badge {badge(c.status)}">{c.status}</span></td>
            <td class="small">{#if c.status === 'login_required'}<a class="btn" href="/link?connection_id={c.id}" target="_blank">Re-link</a>{/if}</td></tr>
        {/each}
      </tbody></table>
      <div style="margin-top:12px"><a class="btn" href="/link" target="_blank">Link a new institution</a></div>
    </div>
  </div>
{/if}

<div class="card" style="margin-top:16px" class:loading>
  <h2>Accounts</h2>
  <table class="data">
    <thead><tr><th>Name</th><th>Institution</th><th>Kind</th><th>Entity</th><th>Source</th><th class="num">Balance</th><th>As of</th><th></th></tr></thead>
    <tbody>
      {#each accounts as a}
        <tr style={a.is_active ? '' : 'opacity:.55'}>
          <td>{a.name}{#if a.mask}<span class="muted small"> ···{a.mask}</span>{/if}</td>
          <td class="small">{a.institution ?? ''}</td>
          <td class="inline-edit"><select value={a.kind} onchange={(e) => setKind(a, (e.target as HTMLSelectElement).value)}>{#each KINDS as k}<option value={k}>{KIND_LABEL[k]}</option>{/each}</select></td>
          <td><button class="btn" style="padding:2px 8px" onclick={() => setEntity(a)}>{a.entity}</button></td>
          <td class="muted small">{a.source}</td>
          <td class="num">{money(a.latest_balance)}</td>
          <td class="muted small">{a.balance_as_of ?? '—'}</td>
          <td><button class="btn" style="padding:2px 8px" onclick={() => toggleActive(a)}>{a.is_active ? 'deactivate' : 'activate'}</button></td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
