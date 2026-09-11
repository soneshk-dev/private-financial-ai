<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Positions, type Crypto } from '$lib/api';
  import { money, compact, KIND_LABEL, titleCase } from '$lib/format';
  import StatTile from '$lib/components/StatTile.svelte';

  let pos: Positions | null = $state(null);
  let cr: Crypto | null = $state(null);
  let loading = $state(true);
  onMount(async () => { [pos, cr] = await Promise.all([api.positions(), api.crypto()]); loading = false; });

  // Part-to-whole: one stacked horizontal bar with a legend (not a donut).
  const alloc = $derived(pos ? Object.entries(pos.allocation).filter(([, v]) => v > 0).slice(0, 8) : []);
  const gainPct = $derived(pos && pos.cost_basis_known > 0 ? null : null);
  const hfBadge = $derived(cr?.aave ? (cr.aave.status === 'healthy' ? 'good' : cr.aave.status === 'moderate' ? 'warn' : 'bad') : '');
</script>

<div class="page-head"><h1>Portfolio</h1><div class="sub">{#if pos?.accounts.length}positions as of {pos.accounts[0].as_of}{/if}</div></div>

<div class="grid kpis" class:loading>
  <StatTile label="Positions (Fidelity + wallets)" value={pos?.total} hero />
  <StatTile label="Crypto (all wallets + exchanges)" value={cr?.total} />
  <StatTile label="Known cost basis" value={pos?.cost_basis_known} sub="taxable accounts only" />
  {#if cr?.aave}
    <div class="card tile">
      <div class="label">Aave V3 health factor</div>
      <div class="value">{cr.aave.health_factor} <span class="badge {hfBadge}">{cr.aave.status}</span></div>
      <div class="delta">collateral {compact(cr.aave.collateral)} · debt {compact(cr.aave.debt)} · BTC liq {compact(cr.aave.liquidation_price_btc)}</div>
    </div>
  {/if}
</div>

{#if alloc.length && pos}
  <div class="card" style="margin-top:16px" class:loading>
    <h2>Allocation by asset class</h2>
    <div class="stack-bar" role="img" aria-label="allocation">
      {#each alloc as [k, v], i}<span style="width:{(v / pos.total) * 100}%;background:var(--series-{i + 1})" title="{titleCase(k)} {money(v)}"></span>{/each}
    </div>
    <div class="legend">{#each alloc as [k, v], i}<span><i style="background:var(--series-{i + 1})"></i>{titleCase(k)} {money(v)} ({Math.round((v / pos.total) * 100)}%)</span>{/each}</div>
  </div>
{/if}

{#if pos}
  {#each [...pos.accounts].sort((x, y) => y.value - x.value) as a}
    <div class="card" style="margin-top:16px" class:loading>
      <div class="h2row"><h2>{a.name} <span class="muted">· {KIND_LABEL[a.kind] ?? a.kind}{a.institution ? ` · ${a.institution}` : ''}</span></h2><span>{money(a.value)}</span></div>
      <table class="data">
        <thead><tr><th>Holding</th><th>Class</th><th class="num">Qty</th><th class="num">Price</th><th class="num">Value</th><th class="num">Cost basis</th><th class="num">Gain</th></tr></thead>
        <tbody>
          {#each a.positions as p}
            <tr>
              <td>{p.symbol ? `${p.symbol} · ` : ''}{p.description ?? p.key}</td><td class="small muted">{p.asset_class ?? ''}</td>
              <td class="num">{p.quantity?.toLocaleString('en-US', { maximumFractionDigits: 4 }) ?? ''}</td>
              <td class="num">{p.price ? money(p.price, 2) : ''}</td><td class="num">{money(p.value)}</td>
              <td class="num muted">{p.cost_basis ? money(p.cost_basis) : ''}</td>
              <td class="num" class:pos={p.cost_basis != null && p.value - p.cost_basis > 0}>{p.cost_basis ? money(p.value - p.cost_basis) : ''}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/each}
{/if}

{#if cr?.protocols.length}
  <div class="card" style="margin-top:16px">
    <h2>DeFi positions</h2>
    <table class="data">
      <thead><tr><th>Protocol</th><th>Side</th><th>Asset</th><th class="num">Qty</th><th class="num">Value</th></tr></thead>
      <tbody>
        {#each cr.protocols as p}
          {#each [['supplied', p.supplied], ['borrowed', p.borrowed], ['claimable', p.claimable]] as [side, rows]}
            {#each rows as r}<tr><td>{p.protocol} <span class="muted small">{p.network}</span></td><td>{side}</td><td>{r.symbol}</td><td class="num">{Number(r.quantity).toLocaleString('en-US', { maximumFractionDigits: 4 })}</td><td class="num" class:neg={side === 'borrowed'}>{side === 'borrowed' ? '-' : ''}{money(r.value)}</td></tr>{/each}
          {/each}
        {/each}
      </tbody>
    </table>
  </div>
{/if}
