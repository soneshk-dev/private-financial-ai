<script lang="ts">
  import { onMount } from 'svelte';
  import { marked } from 'marked';
  import { api, chat, type Conversation, type Message, type Model } from '$lib/api';

  let { open = $bindable(false) }: { open?: boolean } = $props();
  let models: Model[] = $state([]);
  let provider: string | null = $state(null);
  let convs: Conversation[] = $state([]);
  let current: string | null = $state(null);
  let msgs: (Message & { tools?: string[]; pending?: boolean })[] = $state([]);
  let input = $state('');
  let busy = $state(false);
  let status = $state('');
  let showConvs = $state(false);
  let box: HTMLDivElement | undefined = $state();

  onMount(async () => {
    try { models = await api.models(); provider = (models.find((m) => m.default) ?? models[0])?.name ?? null; } catch {}
    try { convs = await api.conversations(); } catch {}
  });

  const scroll = () => queueMicrotask(() => box?.scrollTo({ top: box.scrollHeight }));
  const render = (s: string) => marked.parse(s, { async: false }) as string;

  async function load(id: string) {
    const c = await api.conversation(id);
    current = id;
    const out: typeof msgs = [];
    for (const m of c.messages ?? []) {
      if (m.role === 'user') out.push(m);
      else if (m.role === 'assistant' && m.tool_calls?.length) {
        const last = out[out.length - 1];
        const names = m.tool_calls.map((t: any) => t.function?.name).filter(Boolean);
        if (last && last.role === 'assistant' && last.pending) last.tools = [...(last.tools ?? []), ...names];
        else out.push({ role: 'assistant', content: '', tools: names, pending: true });
      } else if (m.role === 'assistant' && m.content) {
        const last = out[out.length - 1];
        if (last && last.role === 'assistant' && last.pending) { last.content = m.content; last.pending = false; }
        else out.push(m);
      }
    }
    msgs = out;
    showConvs = false;
    scroll();
  }

  function fresh() { current = null; msgs = []; showConvs = false; }

  async function send(e?: Event) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    input = '';
    busy = true;
    msgs = [...msgs, { role: 'user', content: text }, { role: 'assistant', content: '', tools: [], pending: true }];
    scroll();
    const ai = msgs[msgs.length - 1];
    try {
      for await (const ev of chat({ message: text, conversation_id: current, provider })) {
        if (ev.type === 'conversation') current = ev.id;
        else if (ev.type === 'routing') status = `${ev.provider} · ${ev.model}`;
        else if (ev.type === 'status') status = ev.message;
        else if (ev.type === 'tool_call') { ai.tools = [...(ai.tools ?? []), ev.name]; msgs = [...msgs]; scroll(); }
        else if (ev.type === 'message') { ai.content = ev.content; ai.pending = false; msgs = [...msgs]; scroll(); }
        else if (ev.type === 'error') { ai.content = `**Error:** ${ev.message}`; ai.pending = false; msgs = [...msgs]; }
        else if (ev.type === 'done') status = `${status} · ${ev.usage.rounds} round${ev.usage.rounds === 1 ? '' : 's'} · ${ev.usage.seconds}s`;
      }
    } catch (err: any) {
      ai.content = `**Error:** ${err.message}`; ai.pending = false; msgs = [...msgs];
    } finally {
      busy = false;
      try { convs = await api.conversations(); } catch {}
    }
  }

  function onKey(e: KeyboardEvent) { if (e.key === 'Enter' && !e.shiftKey) send(e); }
</script>

<button class="chat-toggle" onclick={() => (open = !open)} title="Chat with your ledger" aria-label="Toggle chat">💬</button>

<aside class="drawer" class:open aria-hidden={!open}>
  <header>
    <button class="btn" onclick={() => (showConvs = !showConvs)} title="Conversations">☰</button>
    <button class="btn" onclick={fresh} title="New conversation">＋</button>
    <select bind:value={provider} title="Model provider">
      {#each models as m}<option value={m.name} disabled={!m.reachable}>{m.name}{m.model ? ` · ${m.model}` : ''}{m.reachable ? '' : ' (down)'}</option>{/each}
    </select>
    <span class="spacer" style="flex:1"></span>
    <button class="btn" onclick={() => (open = false)} aria-label="Close">✕</button>
  </header>
  {#if showConvs}
    <div class="convs">
      {#each convs as c}
        <button class:on={c.id === current} onclick={() => load(c.id)}>{c.title ?? c.id} <span class="muted small">· {c.updated_at.slice(0, 10)}</span></button>
      {:else}<div class="muted small" style="padding:8px 14px">No conversations yet.</div>{/each}
    </div>
  {/if}
  <div class="msgs" bind:this={box}>
    {#if !msgs.length}
      <div class="muted small">Ask about spending, cash flow, positions, or the health of the data. The model runs locally and reads the ledger through tools.</div>
    {/if}
    {#each msgs as m}
      {#if m.role === 'user'}
        <div class="msg user">{m.content}</div>
      {:else}
        {#if m.tools?.length}<div class="tools">{#each m.tools as t}<span class="badge">{t}</span>{/each}</div>{/if}
        {#if m.pending && !m.content}<div class="thinking">thinking…</div>{/if}
        {#if m.content}<div class="msg assistant">{@html render(m.content)}</div>{/if}
      {/if}
    {/each}
  </div>
  <div class="thinking" style="padding: 0 14px 6px">{status}</div>
  <form onsubmit={send}>
    <textarea bind:value={input} onkeydown={onKey} placeholder="Ask… (Enter to send)" disabled={busy}></textarea>
    <button class="btn primary" type="submit" disabled={busy || !input.trim()}>Send</button>
  </form>
</aside>
