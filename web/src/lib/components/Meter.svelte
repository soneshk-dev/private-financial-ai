<script lang="ts">
  import { money, pct } from '$lib/format';
  let { name, spent, limit, status }: { name: string; spent: number; limit: number; status: 'ok' | 'warning' | 'over' } = $props();
  const ratio = $derived(limit > 0 ? Math.min(spent / limit, 1) : 0);
  const icon = $derived(status === 'over' ? '⚠' : status === 'warning' ? '△' : '');
</script>

<div class="meter" title="{name}: {money(spent)} of {money(limit)}">
  <div class="name">{name}{#if icon}<span class="flag" aria-label={status}>{icon} {status}</span>{/if}</div>
  <div class="nums">{money(spent)} / {money(limit)} · {pct(limit > 0 ? spent / limit : null)}</div>
  <div class="track"><div class="fill {status}" style="width: {ratio * 100}%"></div></div>
</div>
