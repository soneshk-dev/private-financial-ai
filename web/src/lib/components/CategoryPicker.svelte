<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { api, type Txn, type TaxonomyL1, type Similar, type CategoryResult } from '$lib/api';
  import { money } from '$lib/format';

  let { txn, onclose, onapplied }: { txn: Txn; onclose: () => void; onapplied: (r: CategoryResult) => void } = $props();

  let taxonomy = $state<TaxonomyL1[]>([]);
  let similar = $state<Similar | null>(null);
  let query = $state('');
  let selected: string | null = $state(txn.category ?? null);
  let scope: 'one' | 'merchant' = $state('one');
  let remember = $state(false);
  let newL1 = $state('');
  let busy = $state(false);
  let error = $state('');
  let cursor = $state(0);
  let input: HTMLInputElement;

  onMount(async () => {
    const [t, s] = await Promise.all([api.categories(), api.similar(txn.id)]);
    taxonomy = t.taxonomy;
    similar = s;
    if (s.n > 0) scope = 'merchant';
    newL1 = taxonomy[0]?.level1 ?? '';
    await tick();
    input?.focus();
  });

  type Row = { category: string; l1: string; sub: string; n: number; core: boolean };
  const all = $derived<Row[]>(taxonomy.flatMap((t) => [
    { category: t.level1, l1: t.level1, sub: '', n: t.bare_n, core: true },
    ...t.subs.map((s) => ({ category: s.category, l1: t.level1, sub: s.name, n: s.n, core: s.core })),
  ]));
  const strayCount = $derived(all.filter((r) => !r.core).length);
  // Without a search, only the core taxonomy is offered. Searching also reaches the
  // inherited free-text sub-categories (flagged), so an old name can still be found.
  const filtered = $derived.by(() => {
    const q = query.trim().toLowerCase();
    if (!q) return all.filter((r) => r.core || r.category === selected);
    const terms = q.split(/\s+/);
    const hit = all.filter((r) => terms.every((w) => r.category.toLowerCase().includes(w)));
    return [...hit.filter((r) => r.core), ...hit.filter((r) => !r.core)];
  });
  const exact = $derived(filtered.some((r) => r.category.toLowerCase() === query.trim().toLowerCase()));
  const canCreate = $derived(query.trim().length > 1 && !query.includes('>') && !exact);
  const newCategory = $derived(`${newL1} > ${query.trim().replace(/\s+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}`);
  const changed = $derived(selected !== null && selected !== (txn.category ?? null));
  const merchant = $derived(similar?.merchant || txn.merchant || txn.description || '');

  $effect(() => { query; cursor = 0; });

  function pick(cat: string) { selected = cat; error = ''; }
  function onkey(e: KeyboardEvent) {
    if (e.key === 'Escape') { onclose(); return; }
    if (e.key === 'ArrowDown') { cursor = Math.min(cursor + 1, filtered.length - 1); e.preventDefault(); scrollTo(); }
    else if (e.key === 'ArrowUp') { cursor = Math.max(cursor - 1, 0); e.preventDefault(); scrollTo(); }
    else if (e.key === 'Enter' || e.code === 'Enter' || e.code === 'NumpadEnter') {
      e.preventDefault();
      if (filtered[cursor]) { pick(filtered[cursor].category); if (e.metaKey || e.ctrlKey) apply(); }
      else if (canCreate) create();
    }
  }
  function scrollTo() { document.getElementById(`cp-row-${cursor}`)?.scrollIntoView({ block: 'nearest' }); }
  async function create() {
    await apply(newCategory, true);
  }
  async function apply(cat: string | null = selected, allow_new = false) {
    if (!cat) return;
    busy = true; error = '';
    try {
      const r = await api.setCategory(txn.id, { category: cat, scope, remember, allow_new });
      onapplied(r);
      onclose();
    } catch (e: any) {
      error = String(e.message ?? e).replace(/^\d+\s*/, '');
    } finally { busy = false; }
  }
</script>

<div class="cp-backdrop" role="presentation" onclick={onclose}></div>
<div class="cp" role="dialog" aria-label="Choose category" onkeydown={onkey} tabindex="-1">
  <div class="cp-head">
    <div>
      <div class="cp-title">{txn.merchant ?? txn.description}</div>
      <div class="muted small">{txn.posted_at} · {txn.account_name} · <span class:pos={txn.amount > 0}>{money(txn.amount, 2)}</span> · now <b>{txn.category ?? '—'}</b></div>
    </div>
    <button class="btn" onclick={onclose} aria-label="Close">✕</button>
  </div>

  <input class="cp-search" bind:this={input} bind:value={query} placeholder="Search categories… (↑↓ to move, Enter to select, ⌘Enter to apply)" />
  {#if !query && strayCount}<div class="muted small" style="margin:-4px 18px 6px">Showing the core taxonomy. {strayCount} inherited names are reachable by search and flagged.</div>{/if}

  <div class="cp-list">
    {#each filtered as r, i (r.category)}
      <button id={`cp-row-${i}`} class="cp-row" class:sub={!!r.sub} class:on={selected === r.category} class:cur={cursor === i}
              onclick={() => pick(r.category)} ondblclick={() => { pick(r.category); apply(); }}>
        <span class="cp-name">{#if r.sub}<span class="muted">{r.l1} ›</span> {r.sub}{:else}{r.l1}{/if}
          {#if !r.core}<span class="badge warn" title="Inherited free-text name, not in the core taxonomy. Prefer a core category, or merge it on the Categories page.">not in taxonomy</span>{/if}</span>
        {#if r.n}<span class="badge">{r.n}</span>{/if}
      </button>
    {/each}
    {#if !filtered.length && !canCreate}<div class="muted small" style="padding:12px">No matching category.</div>{/if}
    {#if canCreate}
      <div class="cp-create">
        <div class="small">No exact match. Create a new sub-category?</div>
        <div class="cp-create-row">
          <select bind:value={newL1}>{#each taxonomy as t}<option value={t.level1}>{t.level1}</option>{/each}</select>
          <span class="mono">› {newCategory.split(' > ')[1]}</span>
          <button class="btn" onclick={create} disabled={busy}>Create &amp; apply</button>
        </div>
        <div class="muted small">New sub-categories show up in every picker from now on, so prefer an existing one when it fits.</div>
      </div>
    {/if}
  </div>

  <div class="cp-foot">
    {#if similar}
      <div class="cp-scope">
        <label><input type="radio" bind:group={scope} value="one" /> Only this transaction</label>
        <label class:disabled={!similar.n}><input type="radio" bind:group={scope} value="merchant" disabled={!similar.n} />
          All {similar.n + 1} from <b>{merchant}</b>
          {#if similar.categories.length}<span class="muted small">(now: {similar.categories.map((c) => `${c.category ?? '—'} ×${c.n}`).join(', ')})</span>{/if}
        </label>
        <label><input type="checkbox" bind:checked={remember} /> Always use this for <b>{merchant}</b> in future syncs
          {#if similar.rule}<span class="badge">rule exists: {similar.rule.category}</span>{/if}</label>
      </div>
    {/if}
    {#if error}<div class="badge bad" style="margin-bottom:8px">{error}</div>{/if}
    <div class="cp-actions">
      <span class="small muted">{selected ? `→ ${selected}` : 'Pick a category'}</span>
      <span style="flex:1"></span>
      <button class="btn" onclick={onclose}>Cancel</button>
      <button class="btn primary" onclick={() => apply()} disabled={!selected || busy || (!changed && !remember && scope === 'one')}>
        {busy ? 'Applying…' : scope === 'merchant' ? `Apply to ${(similar?.n ?? 0) + 1}` : 'Apply'}
      </button>
    </div>
  </div>
</div>

<style>
  .cp-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 40; }
  .cp { position: fixed; z-index: 41; top: 8vh; left: 50%; transform: translateX(-50%); width: min(680px, 94vw); max-height: 84vh;
        background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: 0 20px 60px rgba(0,0,0,.25);
        display: flex; flex-direction: column; outline: none; }
  .cp-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; padding: 16px 18px 10px; }
  .cp-title { font-weight: 600; }
  .cp-search { margin: 0 18px 10px; padding: 9px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2); font-size: 15px; }
  .cp-list { overflow: auto; flex: 1; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); padding: 6px 0; min-height: 120px; }
  .cp-row { display: flex; justify-content: space-between; align-items: center; width: 100%; text-align: left; padding: 6px 18px; border: 0; background: transparent; cursor: pointer; font: inherit; color: var(--ink); }
  .cp-row.sub { padding-left: 30px; }
  .cp-row:not(.sub) { font-weight: 600; margin-top: 4px; }
  .cp-row:hover, .cp-row.cur { background: var(--surface-2); }
  .cp-row.on { background: color-mix(in oklab, var(--accent) 16%, var(--surface)); }
  .cp-row.on .cp-name::before { content: '✓ '; color: var(--accent); }
  .cp-create { padding: 12px 18px; border-top: 1px dashed var(--border); margin-top: 8px; display: grid; gap: 6px; }
  .cp-create-row { display: flex; gap: 8px; align-items: center; }
  .cp-create-row select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
  .cp-foot { padding: 12px 18px 14px; }
  .cp-scope { display: grid; gap: 6px; margin-bottom: 10px; font-size: 14px; }
  .cp-scope label { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .cp-scope label.disabled { opacity: .5; }
  .cp-actions { display: flex; gap: 8px; align-items: center; }
</style>
