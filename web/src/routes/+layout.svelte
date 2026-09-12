<script lang="ts">
  import '../app.css';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { api, type Health } from '$lib/api';
  import Chat from '$lib/components/Chat.svelte';

  let { children } = $props();
  let chatOpen = $state(false);
  let health: Health | null = $state(null);
  const links = [
    ['/', 'Overview'], ['/cashflow', 'Cash flow'], ['/spending', 'Spending'], ['/transactions', 'Transactions'],
    ['/categories', 'Categories'], ['/portfolio', 'Portfolio'], ['/plan', 'Plan'], ['/business', 'Business'], ['/accounts', 'Accounts'],
  ];
  onMount(async () => { try { health = await api.health(); } catch {} });
  const issues = $derived(health ? health.connectors.filter((c) => c.status === 'error').length + health.connections.filter((c) => !['active', 'removed'].includes(c.status)).length : 0);
</script>

<div class="shell">
  <nav class="nav">
    <div class="brand"><i></i> homeai</div>
    {#each links as [href, label]}
      <a {href} class:active={page.url.pathname === href}>{label}</a>
    {/each}
    <div class="spacer"></div>
    <a href="/accounts" class="status">
      {#if health}
        {#if issues}<span class="badge warn">△ {issues} data issue{issues === 1 ? '' : 's'}</span>
        {:else}<span class="badge good">● data healthy</span>{/if}
        <div>snapshot {health.latest_snapshot?.as_of ?? '—'}</div>
      {/if}
    </a>
  </nav>
  <main class="main">
    {@render children()}
  </main>
</div>
<Chat bind:open={chatOpen} />
