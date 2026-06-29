<script>
  let { text = '', diff = false } = $props()
  const lines = $derived((text ?? '').replace(/\s+$/, '').split('\n'))
  function cls(l) {
    if (!diff) return ''
    if (l.startsWith('+') && !l.startsWith('+++')) return 'add'
    if (l.startsWith('-') && !l.startsWith('---')) return 'del'
    if (l.startsWith('@@') || l.startsWith('diff ') || l.startsWith('index ')) return 'hunk'
    return ''
  }
</script>

<div class="cv">
  {#if !text}
    <div class="cv-empty">nothing yet</div>
  {:else}
    {#each lines as l}<span class="ln {cls(l)}">{l || ' '}</span>{/each}
  {/if}
</div>

<style>
  .cv { font-family: var(--mono); font-size: 11.5px; line-height: 1.65; padding: 12px 14px; overflow: auto; height: 100%; color: var(--ink); }
  .cv-empty { color: var(--faint); font-size: 12px; }
  .ln { display: block; white-space: pre-wrap; word-break: break-word; padding: 0 6px; border-radius: 4px; }
  .ln.add { background: var(--green-soft); color: var(--green); }
  .ln.del { background: var(--red-soft); color: var(--red); }
  .ln.hunk { color: var(--accent); }
</style>
