<script lang="ts">
  import { compact, signed } from '$lib/format';
  let { label, value, delta = null, deltaLabel = 'vs 30 days ago', upIsGood = true, hero = false, sub = '' }:
    { label: string; value: number | null | undefined; delta?: number | null; deltaLabel?: string; upIsGood?: boolean; hero?: boolean; sub?: string } = $props();
  const cls = $derived(delta === null || delta === undefined || delta === 0 ? '' : (delta > 0) === upIsGood ? 'up' : 'down');
</script>

<div class="card tile">
  <div class="label">{label}</div>
  <div class={hero ? 'hero' : 'value'}>{compact(value)}</div>
  {#if delta !== null && delta !== undefined}
    <div class="delta {cls}">{signed(delta)} {deltaLabel}</div>
  {:else if sub}
    <div class="delta">{sub}</div>
  {/if}
</div>
