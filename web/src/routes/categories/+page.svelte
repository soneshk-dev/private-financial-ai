<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type TaxonomyL1, type CategoryRule, type MergeSuggestion } from '$lib/api';

  let taxonomy = $state<TaxonomyL1[]>([]);
  let rules = $state<CategoryRule[]>([]);
  let ruleCounts = $state<Record<string, number>>({});
  let suggestions = $state<MergeSuggestion[]>([]);
  let loading = $state(true);
  let editing = $state<string | null>(null);
  let target = $state('');
  let msg = $state('');
  let showCore = $state(false);
  let busy = $state(false);

  async function load() {
    loading = true;
    const [r, sg] = await Promise.all([api.categories(), api.categorySuggestions()]);
    taxonomy = r.taxonomy; rules = r.rules; ruleCounts = r.rule_counts; suggestions = sg; loading = false;
  }
  onMount(load);
  const coreCats = $derived(taxonomy.flatMap((t) => [t.level1, ...t.subs.filter((s) => s.core).map((s) => s.category)]));
  const strayTotal = $derived(taxonomy.reduce((n, t) => n + t.stray, 0));
  const used = $derived(taxonomy.reduce((n, t) => n + t.n, 0));
  const legacyRules = $derived(Object.entries(ruleCounts).filter(([k]) => k !== 'user').reduce((n, [, v]) => n + v, 0));

  function startEdit(cat: string) { editing = cat; target = cat; msg = ''; }
  async function merge(from: string, to: string, allow_new = false) {
    busy = true;
    try {
      const r = await api.renameCategory(from, to, allow_new);
      msg = `${r.from} → ${r.to}: ${r.affected} transactions, ${r.rules} rules repointed`;
      editing = null; await load();
    } catch (e: any) {
      const text = String(e.message ?? e);
      if (!allow_new && text.includes('not an existing category') && confirm(`"${to}" is a new sub-category. Create it?`)) return merge(from, to, true);
      msg = text.replace(/^\d+\s*/, '');
    } finally { busy = false; }
  }
  async function keep(cat: string, k = true) { await api.keepCategory(cat, k); msg = k ? `${cat} is now part of the core taxonomy` : `${cat} removed from the core taxonomy`; await load(); }
  async function acceptAll() {
    const strong = suggestions.filter((s) => s.confidence >= 0.75);
    if (!confirm(`Merge ${strong.length} sub-categories with confidence ≥ 0.75 into their suggested core category?`)) return;
    busy = true;
    for (const s of strong) { try { await api.renameCategory(s.from, s.to); } catch {} }
    busy = false; msg = `merged ${strong.length}`; await load();
  }
  async function dropRule(r: CategoryRule) {
    if (!confirm(`Delete the rule "${r.pattern}" → ${r.category}? Existing overrides stay; future syncs fall back to the provider category.`)) return;
    await api.deleteRule(r.id); await load();
  }
</script>

<div class="page-head">
  <h1>Categories</h1>
  <div class="sub">{used.toLocaleString()} categorised transactions · {strayTotal} sub-categories outside the core taxonomy</div>
</div>
{#if msg}<div class="filters"><span class="badge good">{msg}</span></div>{/if}

<div class="grid two" class:loading>
  <div class="card">
    <div class="h2row"><h2>Suggested merges <span class="muted small">— inherited names that match a core category</span></h2>
      {#if suggestions.length}<button class="btn" onclick={acceptAll} disabled={busy}>Accept all ≥ 0.75</button>{/if}</div>
    {#if !suggestions.length}<div class="muted small">Nothing to merge. Sub-categories still outside the core taxonomy are listed below; merge them by hand or keep them.</div>{/if}
    <table class="data">
      <tbody>
        {#each suggestions as s (s.from)}
          <tr>
            <td>{s.from.split(' > ')[1]} <span class="muted small">{s.from.split(' > ')[0]}</span></td>
            <td class="num">{s.n}</td>
            <td>→ <b>{s.to.split(' > ')[1]}</b></td>
            <td class="num"><span class="badge" class:good={s.confidence >= 0.75}>{Math.round(s.confidence * 100)}%</span></td>
            <td class="num" style="white-space:nowrap">
              <button class="btn" style="padding:2px 8px" onclick={() => merge(s.from, s.to)} disabled={busy}>Merge</button>
              <button class="btn" style="padding:2px 8px" onclick={() => keep(s.from)} disabled={busy} title="Promote to the core taxonomy instead">Keep</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>Merchant rules</h2>
    <div class="muted small" style="margin-bottom:10px">
      {rules.length} rule{rules.length === 1 ? '' : 's'} created from the picker ("Always use this for …").
      {#if legacyRules}{legacyRules.toLocaleString()} rules were inherited from the previous app; merging a sub-category above repoints them too.{/if}
    </div>
    <table class="data">
      <tbody>
        {#each rules as r (r.id)}
          <tr>
            <td>{r.pattern}</td>
            <td>{r.category}</td>
            <td class="num"><button class="btn" style="padding:2px 8px" onclick={() => dropRule(r)}>Delete</button></td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>

<div class="card" style="margin-top:16px" class:loading>
  <div class="h2row"><h2>Taxonomy</h2>
    <label class="small"><input type="checkbox" bind:checked={showCore} /> show core sub-categories too</label></div>
  <table class="data">
    <thead><tr><th>Category</th><th class="num">Transactions</th><th class="num">Last used</th><th></th></tr></thead>
    <tbody>
      {#each taxonomy as t}
        <tr class="l1"><td><b>{t.level1}</b>{#if t.bare_n}<span class="muted small"> · {t.bare_n} without a sub-category</span>{/if}{#if t.stray}<span class="badge warn" style="margin-left:8px">{t.stray} to tidy</span>{/if}</td><td class="num">{t.n}</td><td></td><td></td></tr>
        {#each t.subs.filter((s) => !s.core || (showCore && s.n)) as s (s.category)}
          <tr>
            <td style="padding-left:24px">
              {#if editing === s.category}
                <input list="cats" bind:value={target} onkeydown={(e) => { if (e.key === 'Enter') merge(s.category, target.trim()); if (e.key === 'Escape') editing = null; }} style="min-width:300px" placeholder="Type a core category to merge into, or a new name" />
                <button class="btn" style="padding:2px 8px" onclick={() => merge(s.category, target.trim())} disabled={busy}>Save</button>
                <button class="btn" style="padding:2px 8px" onclick={() => (editing = null)}>Cancel</button>
              {:else}{s.name}{#if !s.core}<span class="badge warn" style="margin-left:6px">not in taxonomy</span>{/if}{/if}
            </td>
            <td class="num">{s.n || ''}</td>
            <td class="num muted small">{s.last ?? ''}</td>
            <td class="num" style="white-space:nowrap">
              {#if editing !== s.category}
                {#if s.n}<button class="btn" style="padding:2px 8px" onclick={() => startEdit(s.category)}>Rename / merge</button>{/if}
                {#if !s.core}<button class="btn" style="padding:2px 8px" onclick={() => keep(s.category)}>Keep</button>
                {:else if showCore}<button class="btn" style="padding:2px 8px" onclick={() => keep(s.category, false)} title="Demote from the core taxonomy (only user-kept ones change)">Unkeep</button>{/if}
              {/if}
            </td>
          </tr>
        {/each}
      {/each}
    </tbody>
  </table>
  <datalist id="cats">{#each coreCats as c}<option value={c}></option>{/each}</datalist>
</div>

<style>
  tr.l1 td { padding-top: 12px; border-bottom: 0; }
</style>
