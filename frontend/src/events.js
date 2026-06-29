// Live Server-Sent Events from the FastAPI backend.

export function liveRun({ mode, prompt, repo }, onEvent) {
  const params = new URLSearchParams({ prompt, mode })
  if (mode === 'code') params.set('baseline', 'gemini')
  if (mode === 'repo') params.set('repo', repo || 'webrepo')
  const es = new EventSource('/run_stream?' + params.toString())
  es.onmessage = (m) => {
    let ev
    try { ev = JSON.parse(m.data) } catch { return }
    onEvent(ev)
    if (ev.type === 'all_done') es.close()
  }
  es.onerror = () => {
    es.close()
    onEvent({ type: 'run_error', message: 'Live stream closed before Crucible returned a result.' })
    onEvent({ type: 'all_done' })
  }
  return () => es.close()
}
