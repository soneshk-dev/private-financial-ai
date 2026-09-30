<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { marked } from 'marked';
  import { api, chat, type Conversation, type Message, type Model } from '$lib/api';

  type Turn = Message & { tools?: string[]; pending?: boolean; when?: string };
  let models: Model[] = $state([]);
  let provider: string | null = $state(null);
  let convs: Conversation[] = $state([]);
  let current: string | null = $state(null);
  let title = $state('');
  let msgs: Turn[] = $state([]);
  let input = $state('');
  let filter = $state('');
  let busy = $state(false);
  let status = $state('');
  let renaming = $state(false);
  let renameText = $state('');
  let box: HTMLDivElement | undefined = $state();
  let ta: HTMLTextAreaElement | undefined = $state();

  const render = (s: string) => marked.parse(s, { async: false }) as string;
  const scroll = () => queueMicrotask(() => box?.scrollTo({ top: box.scrollHeight, behavior: 'smooth' }));
  const day = (iso: string) => { const d = new Date(iso); const now = new Date(); const diff = (now.getTime() - d.getTime()) / 864e5;
    return diff < 1 && d.getDate() === now.getDate() ? 'Today' : diff < 2 ? 'Yesterday' : diff < 7 ? 'This week' : diff < 30 ? 'This month' : 'Older'; };
  const shown = $derived(convs.filter((c) => !filter || (c.title ?? '').toLowerCase().includes(filter.toLowerCase()) || (c.preview ?? '').toLowerCase().includes(filter.toLowerCase())));
  const groups = $derived.by(() => { const g: Record<string, Conversation[]> = {}; for (const c of shown) (g[day(c.updated_at)] ??= []).push(c); return ['Today', 'Yesterday', 'This week', 'This month', 'Older'].filter((k) => g[k]).map((k) => [k, g[k]] as const); });

  onMount(async () => {
    try { models = await api.models(); provider = (models.find((m) => m.default) ?? models[0])?.name ?? null; } catch {}
    await refresh();
    const c = page.url.searchParams.get('c');
    if (c) await load(c); else ta?.focus();
  });
  async function refresh() { try { convs = await api.conversations(); } catch {} }

  async function load(id: string) {
    const c = await api.conversation(id);
    current = id; title = c.title ?? 'Untitled'; renaming = false;
    const out: Turn[] = [];
    for (const m of c.messages ?? []) {
      const when = (m as any).created_at;
      if (m.role === 'user') out.push({ ...m, when });
      else if (m.role === 'assistant' && m.tool_calls?.length) {
        const names = m.tool_calls.map((t: any) => t.function?.name).filter(Boolean);
        const last = out[out.length - 1];
        if (last?.role === 'assistant' && last.pending) last.tools = [...(last.tools ?? []), ...names];
        else out.push({ role: 'assistant', content: '', tools: names, pending: true, when });
      } else if (m.role === 'assistant' && m.content) {
        const last = out[out.length - 1];
        if (last?.role === 'assistant' && last.pending) { last.content = m.content; last.pending = false; }
        else out.push({ ...m, when });
      }
    }
    for (const t of out) if (t.pending) t.pending = false;   // a turn that never got an answer
    msgs = out;
    goto(`/chat?c=${id}`, { replaceState: true, keepFocus: true, noScroll: true });
    await tick(); box?.scrollTo({ top: box.scrollHeight });
  }
  function fresh() { current = null; title = ''; msgs = []; status = ''; goto('/chat', { replaceState: true, keepFocus: true }); ta?.focus(); }
  async function remove(c: Conversation) {
    if (!confirm(`Delete "${c.title ?? 'this conversation'}"?`)) return;
    await api.deleteConversation(c.id);
    if (current === c.id) fresh();
    await refresh();
  }
  async function rename() {
    if (!current) return;
    await api.renameConversation(current, renameText);
    title = renameText || 'Untitled'; renaming = false; await refresh();
  }

  async function send(e?: Event) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    input = ''; busy = true; status = '';
    msgs = [...msgs, { role: 'user', content: text, when: new Date().toISOString() }, { role: 'assistant', content: '', tools: [], pending: true }];
    if (!current) title = text.slice(0, 80);
    scroll();
    const ai = msgs[msgs.length - 1];
    try {
      for await (const ev of chat({ message: text, conversation_id: current, provider })) {
        if (ev.type === 'conversation') { if (!current) { current = ev.id; goto(`/chat?c=${ev.id}`, { replaceState: true, keepFocus: true, noScroll: true }); } }
        else if (ev.type === 'routing') status = `${ev.provider} · ${ev.model}`;
        else if (ev.type === 'status') status = ev.message;
        else if (ev.type === 'tool_call') { ai.tools = [...(ai.tools ?? []), ev.name]; msgs = [...msgs]; scroll(); }
        else if (ev.type === 'message') { ai.content = ev.content; ai.pending = false; ai.when = new Date().toISOString(); msgs = [...msgs]; scroll(); }
        else if (ev.type === 'error') { ai.content = `**Error:** ${ev.message}`; ai.pending = false; msgs = [...msgs]; }
        else if (ev.type === 'done') status = `${status} · ${ev.usage.rounds} round${ev.usage.rounds === 1 ? '' : 's'} · ${ev.usage.seconds}s`;
      }
    } catch (err: any) { ai.content = `**Error:** ${err.message}`; ai.pending = false; msgs = [...msgs]; }
    finally { busy = false; ai.pending = false; msgs = [...msgs]; await refresh(); ta?.focus(); }
  }
  function onKey(e: KeyboardEvent) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }
  function grow() { if (!ta) return; ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'; }
  const starters = ['How did we do this month vs last?', 'What is my allocation drift right now?', 'Which theses have kill metrics close to tripping?', 'Am I on track for both college goals?'];
</script>

<svelte:head><title>Chat · homeai</title></svelte:head>

<div class="chat-page">
  <aside class="chat-list">
    <div class="chat-list-head">
      <button class="btn primary" onclick={fresh}>＋ New chat</button>
      <input class="search" placeholder="Search chats" bind:value={filter} />
    </div>
    <div class="chat-list-body">
      {#each groups as [label, items]}
        <div class="group">{label}</div>
        {#each items as c}
          <div class="conv" class:on={c.id === current}>
            <button class="conv-main" onclick={() => load(c.id)}>
              <div class="conv-title">{c.title ?? 'Untitled'}</div>
              {#if c.preview}<div class="conv-preview">{c.preview}</div>{/if}
            </button>
            <button class="conv-x" title="Delete" onclick={() => remove(c)}>×</button>
          </div>
        {/each}
      {:else}<div class="muted small" style="padding:12px">{filter ? 'No matches.' : 'No saved chats yet.'}</div>{/each}
    </div>
  </aside>

  <section class="chat-main">
    <header class="chat-head">
      {#if current}
        {#if renaming}
          <form class="rename" onsubmit={(e) => { e.preventDefault(); rename(); }}><input bind:value={renameText} autofocus /><button class="btn primary" type="submit">Save</button><button class="btn" type="button" onclick={() => (renaming = false)}>Cancel</button></form>
        {:else}
          <h1 title="Click to rename"><button class="linkish" onclick={() => { renameText = title; renaming = true; }}>{title}</button></h1>
        {/if}
      {:else}<h1>New chat</h1>{/if}
      <span class="spacer"></span>
      <select bind:value={provider} title="Model provider">
        {#each models as m}<option value={m.name} disabled={!m.reachable}>{m.name}{m.model ? ` · ${m.model}` : ''}{m.reachable ? '' : ' (down)'}</option>{/each}
      </select>
    </header>

    <div class="chat-thread" bind:this={box}>
      {#if !msgs.length}
        <div class="empty">
          <p class="muted">The model runs locally and reads the ledger through tools. Every chat is saved on the left.</p>
          <div class="starters">{#each starters as s}<button class="btn" onclick={() => { input = s; send(); }}>{s}</button>{/each}</div>
        </div>
      {/if}
      {#each msgs as m}
        {#if m.role === 'user'}
          <div class="turn user"><div class="msg user">{m.content}</div></div>
        {:else}
          <div class="turn assistant">
            {#if m.tools?.length}<div class="tools">{#each m.tools as t}<span class="badge">{t}</span>{/each}</div>{/if}
            {#if m.pending && !m.content}<div class="thinking">thinking…</div>{/if}
            {#if m.content}<div class="msg assistant">{@html render(m.content)}</div>{/if}
          </div>
        {/if}
      {/each}
    </div>

    <div class="chat-status">{status}</div>
    <form class="composer" onsubmit={send}>
      <textarea bind:this={ta} bind:value={input} onkeydown={onKey} oninput={grow} rows="1" placeholder="Ask about spending, positions, theses, goals… (Enter to send, Shift+Enter for a new line)" disabled={busy}></textarea>
      <button class="btn primary" type="submit" disabled={busy || !input.trim()}>{busy ? '…' : 'Send'}</button>
    </form>
  </section>
</div>
