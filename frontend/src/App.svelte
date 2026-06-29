<script>
  import { fly, fade, scale } from 'svelte/transition'
  import { flip } from 'svelte/animate'
  import { tweened } from 'svelte/motion'
  import { cubicOut } from 'svelte/easing'
  import { liveRun } from './events.js'
  import Code from './Code.svelte'

  const BROKEN_LIMITER = `def allow_events(events, limit, window_seconds):
    history = {}
    seen_ids = {}
    decisions = []
    for event in events:
        user_id = event["user_id"]
        timestamp = event["timestamp"]
        event_id = event.get("event_id")
        window = history.setdefault(user_id, [])
        window[:] = [t for t in window if timestamp - t <= window_seconds]
        if event_id is not None and event_id in seen_ids.setdefault(user_id, set()):
            decisions.append(True)
            continue
        allowed = len(window) <= limit
        if allowed:
            window.append(timestamp)
        if event_id is not None:
            seen_ids[user_id].add(event_id)
        decisions.append(allowed)
    return decisions
`
  const BROKEN_BATCHES = `def topological_batches(tasks):
    # tasks: [{"id": "build", "deps": ["lint"]}, ...]
    remaining = {task["id"]: set(task.get("deps", [])) for task in tasks}
    batches = []
    while remaining:
        ready = [name for name, deps in remaining.items() if not deps]
        if not ready:
            return []
        batches.append(ready)
        for name in ready:
            del remaining[name]
        for deps in remaining.values():
            deps.difference_update(ready)
    return batches
`
  const MODES = [
    { id: 'code', label: 'Code', hint: 'verified function or module' },
    { id: 'app',  label: 'Build', hint: 'interactive app with runtime checks' },
    { id: 'repo', label: 'Fix',   hint: 'paste broken code or point at a repo' },
  ]
  const CASES = {
    code: [
      {
        id: 'rolling-rate-limit',
        label: 'rate limiter',
        prompt: 'Implement a deterministic per-user rolling-window rate limiter. Expose allow_events(events, limit, window_seconds), where events is a list of dicts with user_id, timestamp, and event_id. Events can arrive out of order, duplicate event_id values must be idempotent per user, timestamps exactly window_seconds old are expired, and the returned decisions must be in input order.',
      },
      {
        id: 'rules-engine',
        label: 'rules engine',
        prompt: 'Write evaluate_rules(records, rules) for a compact rules engine. Records are dicts; rules support nested all/any/not groups, comparisons eq/ne/lt/lte/gt/gte/contains/exists, missing fields are false except exists:false, and the result must include matched record ids plus a stable explanation trail for every rejected predicate.',
      },
      {
        id: 'inventory-ledger',
        label: 'inventory ledger',
        prompt: 'Implement reconcile_inventory(events) for an inventory ledger. Events include receive, reserve, release, ship, and expire with sku, qty, timestamp, reservation_id. Never allow negative available stock, expire reservations in timestamp order, reject invalid events with reasons, and return final balances plus rejected event ids.',
      },
    ],
    app: [
      {
        id: 'incident-triage',
        label: 'incident triage',
        prompt: 'Build an incident triage board with severity filters, owner assignment, SLA countdowns, keyboard navigation, and a detail drawer. It should feel like an operations tool judges can click through, not a landing page.',
      },
      {
        id: 'migration-planner',
        label: 'migration planner',
        prompt: 'Build a migration planner for database changes with dependency graph rows, dry-run status, blocked steps, rollback notes, and a compact command bar for approving or holding each step.',
      },
      {
        id: 'warehouse-picks',
        label: 'warehouse picks',
        prompt: 'Build a warehouse pick-path planner with CSV import, route ordering, exception states, and a compact operator dashboard for scanned bins, missing items, and route completion.',
      },
    ],
    repo: [
      {
        id: 'pasted-limiter',
        label: 'broken limiter',
        source: 'snippet',
        code: BROKEN_LIMITER,
        prompt: 'Repair allow_events(events, limit, window_seconds). Events are dicts with user_id, timestamp, and event_id. The function must isolate users, handle out-of-order timestamps, expire timestamps exactly window_seconds old, make duplicate event_id calls idempotent by returning the original decision, keep memory bounded, and return decisions in input order.',
      },
      {
        id: 'pasted-batches',
        label: 'dependency batches',
        source: 'snippet',
        code: BROKEN_BATCHES,
        prompt: 'Repair topological_batches(tasks). It must return stable sorted batches, reject unknown dependency ids with a clear ValueError, detect cycles with the cycle members, preserve duplicate task protection, and avoid mutating the input task objects.',
      },
      {
        id: 'undo-redo',
        label: 'undo/redo',
        source: 'repo',
        repo: 'webrepo',
        prompt: 'add keyboard-accessible undo and redo to the bundled web repo, with tests for history boundaries and visual QA for the controls',
      },
      {
        id: 'reservations',
        label: 'reservations',
        source: 'repo',
        repo: 'webrepo',
        prompt: 'extend the inventory repo with atomic item reservations, expiry handling, and regression tests for over-reservation',
      },
    ],
  }
  const STORY = {
    code: {
      kicker: 'code gauntlet',
      title: 'Complex prompts become contracts, tests, and verified code.',
      body: 'Adversary blind. Implementer blind. Oracle executes.',
      chips: ['stateful cases', 'counterexamples', 'fuzz + diff'],
    },
    app: {
      kicker: 'build proof',
      title: 'Generated UI is rendered, clicked, and visually checked.',
      body: 'Files are not enough. Render, click, inspect.',
      chips: ['runtime check', 'preview', 'vision QA'],
    },
    repo: {
      kicker: 'repair bench',
      title: 'Paste broken code or point Crucible at a repo.',
      body: 'The output is a corrected implementation or a verified patch.',
      chips: ['pasted code', 'repo path', 'tests'],
    },
  }
  const A = {
    architect: ['architect', 'Architect', 'M3 21h18M5 21V8l7-4 7 4v13M9 21v-6h6v6'],
    adversary: ['adversary', 'Adversary', 'M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z'],
    implementer: ['implementer', 'Implement', 'M8 9l-4 3 4 3M16 9l4 3-4 3M13 6l-2 12'],
    surgeon: ['surgeon', 'Surgeon', 'M6 3v6a6 6 0 0012 0V3M9 21a3 3 0 100-6 3 3 0 000 6zM12 15v-3'],
    arbiter: ['arbiter', 'Arbiter', 'M12 3v18M5 7h14M7 7l-3 6h6zM17 7l3 6h-6z'],
    vision: ['vision', 'Vision', 'M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM12 9a3 3 0 100 6 3 3 0 100-6z'],
  }

  const MEMORY_KEY = 'crucible-run-memory'
  const SNAPSHOT_KEY = 'crucible-tab-snapshots'

  let theme = $state('light')
  let mode = $state('code')
  let prompt = $state(CASES.code[0].prompt)
  let repoPath = $state('')
  let fixSource = $state('snippet')
  let sourceCode = $state(BROKEN_LIMITER)
  let running = $state(false)
  let selectedCaseId = $state(CASES.code[0].id)
  let showMemory = $state(false)
  let memories = $state([])
  let modeSnapshots = $state({})

  let agents = $state({})
  let stages = $state([])
  let ce = $state(null)
  let surgeon = $state(null)
  let spec = $state(null)
  let oracle = $state(null)
  let test = $state(null)
  let diff = $state('')
  let testOutput = $state(null)
  let delivered = $state(null)
  let candidateCode = $state('')
  let candidateReason = $state('')
  let candidateHistory = $state([])
  let selectedStage = $state('')
  let verdict = $state('')
  let tab = $state('flow')

  let base = $state({ provider: 'Google AI Studio', code: '', raw: '', running: false })
  let baseElapsed = $state(0)
  let baseDoneElapsed = $state(0)
  const cbTps = tweened(0, { duration: 550, easing: cubicOut })
  const gpTps = tweened(0, { duration: 700, easing: cubicOut })

  let appHtml = $state('')
  let appVerified = $state(false)
  let copyStatus = $state('')

  let stopFn = null
  const modeIdx = $derived(MODES.findIndex((m) => m.id === mode))
  const modeStory = $derived(getStory())
  const artifactReady = $derived(Boolean(artifactText()))
  const artifactKind = $derived(artifactLabel())
  const modeCases = $derived(CASES[mode] || [])
  const selectedCase = $derived(currentCase())
  const agentList = $derived(
    mode === 'code'
      ? [A.architect, A.adversary, A.implementer, A.surgeon, A.arbiter]
      : [A.architect, A.adversary, A.implementer, A.surgeon, A.vision]
  )

  $effect(() => { document.documentElement.dataset.theme = theme })
  $effect(() => {
    try {
      memories = JSON.parse(localStorage.getItem(MEMORY_KEY) || '[]')
    } catch {
      memories = []
    }
  })
  $effect(() => {
    try {
      const savedSnapshots = JSON.parse(localStorage.getItem(SNAPSHOT_KEY) || '{}')
      modeSnapshots = savedSnapshots
      const saved = savedSnapshots.code
      if (saved) restoreSnapshot(saved, 'code')
    } catch {
      modeSnapshots = {}
    }
  })
  $effect(() => {
    if (base.running) {
      const t0 = performance.now(); baseElapsed = 0
      const iv = setInterval(() => (baseElapsed = (performance.now() - t0) / 1000), 70)
      return () => clearInterval(iv)
    }
  })

  function pickMode(id) {
    if (running || id === mode) return
    const saved = saveModeSnapshot(mode)
    mode = id
    restoreSnapshot(saved[id], id)
  }

  function reset() {
    agents = {}; stages = []; ce = null; surgeon = null; spec = null; oracle = null; test = null
    diff = ''; testOutput = null; delivered = null; candidateCode = ''; candidateReason = ''; candidateHistory = []; selectedStage = ''; verdict = ''
    copyStatus = ''
    tab = defaultTab(mode, fixSource)
    base = { provider: mode === 'code' ? 'Google AI Studio' : '', code: '', raw: '', running: false }
    baseDoneElapsed = 0; appHtml = ''; appVerified = false
    cbTps.set(0, { duration: 0 }); gpTps.set(0, { duration: 0 })
  }

  function defaultTab(id = mode, source = fixSource) {
    if (id === 'code') return 'flow'
    if (id === 'repo') return source === 'snippet' ? 'diff' : 'plan'
    return 'app'
  }

  function streamedCode(text, final = false) {
    const raw = text || ''
    const open = raw.match(/```(?:python|py)?\s*\n?/i)
    if (open) {
      const start = open.index + open[0].length
      const rest = raw.slice(start)
      const end = rest.indexOf('```')
      return (end >= 0 ? rest.slice(0, end) : rest).trim()
    }
    return final ? raw.trim() : ''
  }

  function noteCandidate(role, code, reasoning = '') {
    if (!code) return
    candidateCode = code
    candidateReason = reasoning || candidateReason
    candidateHistory = [...candidateHistory, { role, code, reasoning, ts: new Date().toLocaleTimeString([], { minute: '2-digit', second: '2-digit' }) }].slice(-8)
  }

  function clone(value) {
    if (value == null) return value
    try { return structuredClone(value) } catch { return JSON.parse(JSON.stringify(value)) }
  }

  function snapshotState() {
    return {
      prompt,
      selectedCaseId,
      repoPath,
      fixSource,
      sourceCode,
      agents: clone(agents),
      stages: clone(stages),
      ce: clone(ce),
      surgeon,
      spec: clone(spec),
      oracle: clone(oracle),
      test: clone(test),
      diff,
      testOutput: clone(testOutput),
      delivered: clone(delivered),
      candidateCode,
      candidateReason,
      candidateHistory: clone(candidateHistory),
      selectedStage,
      verdict,
      tab,
      base: clone({ ...base, running: false }),
      baseDoneElapsed,
      appHtml,
      appVerified,
    }
  }

  function saveModeSnapshot(id = mode) {
    const next = { ...modeSnapshots, [id]: snapshotState() }
    modeSnapshots = next
    try {
      localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(next))
    } catch {}
    return next
  }

  function restoreSnapshot(saved, id = mode) {
    const fallback = CASES[id]?.[0]
    selectedCaseId = saved?.selectedCaseId || fallback?.id || ''
    prompt = saved?.prompt ?? fallback?.prompt ?? MODES.find((m) => m.id === id)?.hint ?? ''
    repoPath = saved?.repoPath ?? (fallback?.repo && fallback.repo !== 'webrepo' ? fallback.repo : '')
    fixSource = saved?.fixSource || fallback?.source || 'snippet'
    sourceCode = saved?.sourceCode ?? fallback?.code ?? BROKEN_LIMITER
    agents = clone(saved?.agents || {})
    stages = clone(saved?.stages || [])
    ce = clone(saved?.ce || null)
    surgeon = saved?.surgeon || null
    spec = clone(saved?.spec || null)
    oracle = clone(saved?.oracle || null)
    test = clone(saved?.test || null)
    diff = saved?.diff || ''
    testOutput = clone(saved?.testOutput || null)
    delivered = clone(saved?.delivered || null)
    candidateCode = saved?.candidateCode || delivered?.code || ''
    candidateReason = saved?.candidateReason || ''
    candidateHistory = clone(saved?.candidateHistory || [])
    selectedStage = saved?.selectedStage || ''
    verdict = saved?.verdict || ''
    tab = saved?.tab || defaultTab(id, fixSource)
    base = clone(saved?.base || { provider: id === 'code' ? 'Google AI Studio' : '', code: '', raw: '', running: false })
    base.running = false
    baseDoneElapsed = saved?.baseDoneElapsed || 0
    appHtml = saved?.appHtml || ''
    appVerified = !!saved?.appVerified
    copyStatus = ''
    cbTps.set(0, { duration: 0 }); gpTps.set(0, { duration: 0 })
  }
  function upsertStage(name, patch) {
    let s = stages.find((x) => x.name === name)
    if (!s) { s = { name, status: 'running', detail: '' }; stages.push(s) }
    Object.assign(s, patch)
  }

  function inspectStage(name) {
    selectedStage = selectedStage === name ? '' : name
  }

  function stageDetail(name) {
    return stages.find((s) => s.name === name)?.detail || ''
  }

  function oracleExampleCount() {
    return oracle?.example_tests?.length || oracle?.example_count || 0
  }

  function oraclePropertyCount() {
    return oracle?.property_tests?.length || oracle?.property_names?.length || 0
  }

  function oracleHasBodies() {
    return Boolean((oracle?.example_tests || []).length || (oracle?.property_tests || []).length || oracle?.differential_reference)
  }

  function gauntletOutputTitle() {
    if (verdict === 'verified') return 'gauntlet passed'
    if (verdict === 'floor') return 'best partial output'
    if (verdict === 'error') return 'run error'
    if (running) return 'gauntlet running'
    return 'gauntlet output'
  }

  function apply(ev) {
    switch (ev.type) {
      case 'vanilla_start':
        base.running = true
        base.code = ''
        base.raw = ''
        if (ev.provider) base.provider = ev.provider
        break
      case 'vanilla_token':
        base.raw = (base.raw || '') + ev.text
        base.code = streamedCode(base.raw)
        break
      case 'vanilla_done':
        base.running = false
        base.code = ev.code || streamedCode(base.raw, true)
        baseDoneElapsed = ev.elapsed || baseElapsed
        gpTps.set(ev.tokens_per_sec || 0)
        break
      case 'agent_start': agents[ev.role] = 'active'; break
      case 'agent_done': agents[ev.role] = 'done'; break
      case 'spec_ready': spec = ev.spec; break
      case 'oracle_ready':
        oracle = {
          boundary_categories: ev.boundary_categories || [],
          property_names: ev.property_names || [],
          example_count: ev.example_count || 0,
          has_reference: !!ev.has_reference,
          example_tests: ev.example_tests || [],
          property_tests: ev.property_tests || [],
          differential_reference: ev.differential_reference || '',
        }
        if (mode === 'code') tab = 'tests'
        break
      case 'candidate_proposed':
        noteCandidate('Implementer', ev.code, ev.reasoning)
        if (mode === 'code') tab = 'code'
        break
      case 'test_ready': test = { path: ev.path, content: ev.content }; if (mode === 'repo' && fixSource === 'repo') tab = 'test'; break
      case 'diff_ready': diff = ev.diff || ''; if (mode === 'repo' && fixSource === 'repo') tab = 'diff'; break
      case 'test_output': testOutput = { text: ev.text, passed: ev.passed }; if (mode === 'repo' && fixSource === 'repo') tab = 'output'; break
      case 'iteration': stages = []; break
      case 'stage_start': upsertStage(ev.stage, { status: 'running' }); break
      case 'stage_result': {
        const r = ev.result
        const skipped = r.status === 'pass' && /^skipped/.test(r.detail || '')
        upsertStage(r.stage, { status: skipped ? 'skip' : r.status, detail: r.detail || '' })
        if (r.counterexample) ce = r.counterexample
        break
      }
      case 'surgeon_patch':
        surgeon = ev.diff_explanation
        noteCandidate('Surgeon', ev.code, ev.diff_explanation)
        if (mode === 'code') tab = 'code'
        break
      case 'metrics': cbTps.set(ev.tokens_per_sec || 0); break
      case 'app_ready': appHtml = ev.html || ''; appVerified = !!ev.verified; tab = 'app'; break
      case 'candidate_delivered':
        noteCandidate('Final', ev.code, 'verified by the gauntlet')
        delivered = { code: ev.code, kind: 'verified' }
        verdict = 'verified'
        if (mode === 'repo') {
          if (fixSource === 'repo') diff = ev.code
          tab = 'diff'
        } else if (mode === 'code') {
          tab = 'code'
        }
        break
      case 'floor_reached':
        noteCandidate('Floor', ev.code, ev.unverified_property)
        delivered = { code: ev.code, kind: 'floor', label: ev.unverified_property }
        verdict = verdict || 'floor'
        if (mode === 'code') tab = 'code'
        if (mode === 'repo') tab = 'diff'
        break
      case 'run_error': verdict = 'error'; surgeon = ev.message; break
      case 'all_done': running = false; rememberRun(); saveModeSnapshot(); break
    }
  }

  function runPrompt() {
    return prompt
  }

  function requestMode() {
    return mode === 'repo' && fixSource === 'snippet' ? 'repair' : mode
  }

  function run() {
    if (running) return
    showMemory = false
    reset(); running = true
    const repo = repoPath.trim() || 'webrepo'
    let got = false
    stopFn = liveRun({ mode: requestMode(), prompt: runPrompt(), repo, sourceCode }, (e) => { got = true; apply(e) })
    setTimeout(() => {
      if (!got && running) {
        stopFn && stopFn()
        running = false
        verdict = 'error'
        surgeon = 'Live stream did not start. Check API keys and server logs.'
      }
    }, 3000)
  }

  function currentCase() {
    const cases = CASES[mode] || []
    return cases.find((c) => c.id === selectedCaseId) || cases[0]
  }

  function pickCase() {
    if (running) return
    const c = currentCase()
    if (!c) return
    prompt = c.prompt
    if (mode === 'repo') {
      fixSource = c.source || 'snippet'
      if (c.code) sourceCode = c.code
      repoPath = c.repo ? (c.repo === 'webrepo' ? '' : c.repo) : repoPath
      tab = fixSource === 'snippet' ? 'diff' : 'plan'
    } else {
      tab = 'app'
    }
    reset()
    saveModeSnapshot()
  }

  function pickFixSource(source) {
    if (running) return
    fixSource = source
    reset()
    tab = source === 'snippet' ? 'diff' : 'plan'
    saveModeSnapshot()
  }

  function persistMemories(next) {
    memories = next.slice(0, 12)
    try {
      localStorage.setItem(MEMORY_KEY, JSON.stringify(memories))
    } catch {}
  }

  function rememberRun() {
    const useful = delivered || appHtml || diff || verdict || stages.length || ce || surgeon
    if (!useful) return
    const item = {
      id: Date.now(),
      ts: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      mode,
      prompt,
      caseId: selectedCaseId,
      repoPath,
      fixSource,
      sourceCode: fixSource === 'snippet' ? sourceCode : '',
      verdict: verdict || (appVerified ? 'verified' : delivered ? delivered.kind : ''),
      stages: stages.map((s) => ({ ...s })),
      ce,
      surgeon,
      spec,
      oracle,
      delivered,
      candidateCode,
      candidateReason,
      candidateHistory,
      selectedStage,
      appHtml,
      appVerified,
      diff,
      testOutput,
      base,
      baseDoneElapsed,
    }
    persistMemories([item, ...memories.filter((m) => !(m.mode === mode && m.prompt === prompt && m.fixSource === fixSource)).slice(0, 11)])
  }

  function restoreMemory(item) {
    if (running && stopFn) stopFn()
    running = false
    mode = item.mode
    selectedCaseId = item.caseId || CASES[item.mode]?.[0]?.id
    prompt = item.prompt
    repoPath = item.repoPath || ''
    fixSource = item.fixSource || CASES[item.mode]?.find((c) => c.id === item.caseId)?.source || 'snippet'
    sourceCode = item.sourceCode || CASES[item.mode]?.find((c) => c.id === item.caseId)?.code || BROKEN_LIMITER
    agents = {}
    stages = (item.stages || []).map((s) => ({ ...s }))
    ce = item.ce || null
    surgeon = item.surgeon || null
    spec = item.spec || null
    oracle = item.oracle || null
    test = null
    diff = item.diff || ''
    testOutput = item.testOutput || null
    delivered = item.delivered || null
    candidateCode = item.candidateCode || delivered?.code || ''
    candidateReason = item.candidateReason || ''
    candidateHistory = item.candidateHistory || []
    selectedStage = item.selectedStage || ''
    verdict = item.verdict || ''
    appHtml = item.appHtml || ''
    appVerified = !!item.appVerified
    base = item.base || { provider: mode === 'code' ? 'Google AI Studio' : '', code: '', running: false }
    baseDoneElapsed = item.baseDoneElapsed || 0
    tab = mode === 'repo' ? (fixSource === 'snippet' ? 'diff' : (diff ? 'diff' : 'plan')) : 'app'
    showMemory = false
    saveModeSnapshot()
  }

  function clearMemory() {
    persistMemories([])
    showMemory = false
  }

  function getStory() {
    if (running) {
      return {
        kicker: 'live running',
        title: mode === 'code' ? 'Agents are racing the baseline.' : 'Crucible is building evidence.',
        body: 'Artifact, failure, repair, proof.',
        chips: ['architect', 'adversary', 'oracle'],
      }
    }
    if (mode === 'code' && delivered) {
      return {
        kicker: 'verified function',
        title: 'Baseline missed the edge case. Crucible shipped the repair.',
        body: 'Counterexample -> patch -> green gauntlet.',
        chips: ['baseline failed', 'counterexample', '200 fuzzed'],
      }
    }
    if (mode === 'app' && appVerified) {
      return {
        kicker: 'verified app',
        title: 'The app rendered, clicked, and passed visual QA.',
        body: 'Preview exercised before release.',
        chips: ['clicked path', 'render pass', 'vision pass'],
      }
    }
    if (mode === 'repo' && verdict === 'verified') {
      return {
        kicker: fixSource === 'snippet' ? 'verified repair' : 'verified patch',
        title: fixSource === 'snippet' ? 'Pasted code returned as a corrected implementation.' : 'Repo fix passed tests and visual QA.',
        body: fixSource === 'snippet' ? 'Broken input, adversarial tests, fixed output.' : 'Change, prove, return the patch.',
        chips: fixSource === 'snippet' ? ['preserved API', 'edge tests', 'fixed code'] : ['npm test green', 'visual pass', 'apply diff'],
      }
    }
    return STORY[mode]
  }

  function artifactText() {
    if (mode === 'code') return delivered?.code || ''
    if (mode === 'app') return appHtml || ''
    if (mode === 'repo') return fixSource === 'snippet' ? (delivered?.code || diff || '') : (diff || delivered?.code || '')
    return ''
  }

  function artifactLabel() {
    if (mode === 'code') return 'code'
    if (mode === 'app') return 'HTML'
    return fixSource === 'snippet' ? 'code' : 'diff'
  }

  function artifactFilename() {
    if (mode === 'code') return 'crucible-verified-function.py'
    if (mode === 'app') return 'crucible-verified-app.html'
    return fixSource === 'snippet' ? 'crucible-repaired-code.py' : 'crucible-verified.patch'
  }

  async function copyArtifact() {
    const text = artifactText()
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      copyStatus = 'copied'
    } catch {
      copyStatus = 'copy failed'
    }
    setTimeout(() => { copyStatus = '' }, 1400)
  }

  function downloadArtifact() {
    const text = artifactText()
    if (!text) return
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = artifactFilename()
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }
</script>

<div class="app">
  <header>
    <div class="brand"><div class="logo"></div><span class="name">Crucible</span></div>
    <div class="right">
      <span class="chip"><i class="dot"></i> Live agents</span>
      <button class="icon memory-toggle" onclick={() => (showMemory = !showMemory)} aria-label="open persistent run memory">memory {memories.length}</button>
      <button class="icon" onclick={() => (theme = theme === 'dark' ? 'light' : 'dark')} aria-label="toggle theme">◐</button>
    </div>
  </header>

  {#if showMemory}
    <div class="memory-popover">
      <div class="memory-head">
        <b>run memory</b>
        {#if memories.length}<button onclick={clearMemory}>clear</button>{/if}
      </div>
      {#if memories.length === 0}
        <div class="memory-empty">Completed runs persist here in this browser.</div>
      {:else}
        {#each memories.slice(0, 6) as item}
          <button class="memory-row" onclick={() => restoreMemory(item)}>
            <span>{item.mode} · {item.verdict || 'saved'}{item.fixSource === 'snippet' ? ' · pasted code' : ''}</span>
            <b>{item.prompt}</b>
            <em>{item.ts}</em>
          </button>
        {/each}
      {/if}
    </div>
  {/if}

  <div class="proof-strip" class:done={artifactReady && !running}>
    <div class="proof-copy">
      <span>{modeStory.kicker}</span>
      <b>{modeStory.title}</b>
      <em>{modeStory.body}</em>
    </div>
    <div class="proof-meta">
      {#each modeStory.chips as chip}
        <span>{chip}</span>
      {/each}
      {#if artifactReady && !running}
        <button class="mini-action" onclick={copyArtifact}>{copyStatus || `copy ${artifactKind}`}</button>
        <button class="mini-action" onclick={downloadArtifact}>download</button>
      {/if}
    </div>
  </div>

  <div class="bar">
    <div class="seg" style="--i:{modeIdx}">
      <div class="seg-pill"></div>
      {#each MODES as m}
        <button class="seg-btn" class:on={mode === m.id} onclick={() => pickMode(m.id)}>{m.label}</button>
      {/each}
    </div>
    <label class="case-picker">
      <span>case</span>
      <select bind:value={selectedCaseId} onchange={pickCase}>
        {#each modeCases as c}
          <option value={c.id}>{c.label}</option>
        {/each}
      </select>
    </label>
    <button class="run" class:busy={running} onclick={run} disabled={running}>{running ? 'running' : 'Run'}</button>
  </div>

  <div class="composer" class:repo={mode === 'repo'}>
    <div class="editor-card task-editor-card">
      <div class="editor-head">
        <span>{mode === 'repo' ? 'fix request' : 'task'}</span>
        {#if mode === 'repo'}
          <div class="source-tabs" role="group" aria-label="fix source">
            <button class:on={fixSource === 'snippet'} onclick={() => pickFixSource('snippet')}>paste code</button>
            <button class:on={fixSource === 'repo'} onclick={() => pickFixSource('repo')}>repo path</button>
          </div>
        {:else}
          <em>live prompt sent to the agents</em>
        {/if}
      </div>
      <textarea
        class="task-editor"
        bind:value={prompt}
        placeholder={mode === 'repo' ? 'Describe the bug, expected behavior, and constraints.' : 'Describe the thing to build or verify.'}
        onblur={() => saveModeSnapshot()}
        onkeydown={(e) => (e.metaKey || e.ctrlKey) && e.key === 'Enter' && run()}
      ></textarea>
    </div>

    {#if mode === 'repo' && fixSource === 'repo'}
      <div class="editor-card source-editor-card" transition:fade={{ duration: 160 }}>
        <div class="editor-head source-head">
          <span>source</span>
          <em>blank uses bundled webrepo</em>
        </div>
        <div class="repo-line">
          <span>path</span>
          <input bind:value={repoPath} placeholder="~/path/to/your/repo  (blank = bundled webrepo)" onblur={() => saveModeSnapshot()} />
        </div>
      </div>
    {/if}
  </div>

  <main class="stage {mode}" class:snippet={mode === 'repo' && fixSource === 'snippet'}>
    {#if mode === 'code'}
      <section class="card">
        <div class="card-h"><span class="t">{base.provider || 'GPU baseline'} code</span><span class="meta mono">{(base.running ? baseElapsed : baseDoneElapsed).toFixed(1)}s</span></div>
        <pre class="codepane">{base.code || (base.running ? 'waiting for code block...' : '...')}</pre>
        <div class="foot"><span class="tag warn">unverified</span><span class="mono muted">{Math.round($gpTps)} tok/s</span></div>
      </section>
    {/if}

    {#if mode !== 'app'}
      <section class="card" class:source-pane={mode === 'repo' && fixSource === 'snippet'}>
        <div class="card-h">
          <span class="t">{mode === 'repo' && fixSource === 'snippet' ? 'Broken code' : 'Crucible'}</span>
          {#if mode === 'code'}
            <div class="card-actions">
              <div class="tabs-mini">
                <button class:on={tab !== 'code' && tab !== 'tests'} onclick={() => (tab = 'flow')}>Flow</button>
                <button class:on={tab === 'code'} onclick={() => (tab = 'code')}>Code</button>
                <button class:on={tab === 'tests'} onclick={() => (tab = 'tests')}>Tests</button>
              </div>
              <span class="meta mono accent">{Math.round($cbTps).toLocaleString()} tok/s</span>
            </div>
          {:else}
            <span class="meta mono accent">{mode === 'repo' && fixSource === 'snippet' ? 'editable' : Math.round($cbTps).toLocaleString() + ' tok/s'}</span>
          {/if}
        </div>
        {#if mode === 'repo' && fixSource === 'snippet'}
          <textarea
            class="stage-code-editor"
            bind:value={sourceCode}
            spellcheck="false"
            placeholder="Paste the broken code here."
            onblur={() => saveModeSnapshot()}
          ></textarea>
        {:else if mode === 'code' && tab === 'code'}
          <div class="candidate-panel">
            <div class="candidate-head">
              <span>{candidateHistory.at(-1)?.role || 'current candidate'}</span>
              <em>{candidateHistory.length ? `${candidateHistory.length} version${candidateHistory.length === 1 ? '' : 's'}` : 'code appears as agents produce it'}</em>
            </div>
            <Code text={candidateCode || delivered?.code} />
          </div>
        {:else if mode === 'code' && tab === 'tests'}
          <div class="test-panel">
            {#if oracle}
              <div class="test-summary">
                <span>{oracleExampleCount()} examples</span>
                <span>{oraclePropertyCount()} properties</span>
                <span>{oracle.has_reference ? 'reference diff' : 'no reference diff'}</span>
              </div>
              {#if !oracleHasBodies()}
                <div class="note">This saved/current run only emitted test counts. Restart the Python server and rerun to inspect generated test bodies here.</div>
              {/if}
              <div class="test-list">
                {#each (oracle.example_tests || []).slice(0, 6) as ex}
                  <div class="test-item">
                    <b>[{ex.boundary_category}]</b>
                    <code>{ex.input_repr}</code>
                    <code>=> {ex.expected_repr}</code>
                  </div>
                {/each}
                {#each (oracle.property_tests || []).slice(0, 4) as prop}
                  <div class="test-item property">
                    <b>{prop.name}</b>
                    <code>{prop.strategy}</code>
                    <pre>{prop.code}</pre>
                  </div>
                {/each}
              </div>
            {:else}
              <div class="note">generated tests appear here after the adversary finishes</div>
            {/if}
          </div>
        {:else}
          <div class="agents">
            {#each agentList as [id, label, d]}
              <div class="agent {agents[id] || 'idle'}"><div class="ring"><svg viewBox="0 0 24 24"><path d={d} /></svg></div><span>{label}</span></div>
            {/each}
          </div>
          <div class="flow">
            {#if stages.length === 0 && !ce && !surgeon && !delivered}
              <div class="empty-flow">
                <span>spec frozen</span>
                <span>blind oracle</span>
                <span>execution owns the verdict</span>
              </div>
            {/if}
            {#each stages as s (s.name)}
              <details class="stage-details" animate:flip={{ duration: 300 }} in:fly={{ y: 8, duration: 300 }}>
                <summary class="row {s.status}">
                  <i class="mk"></i><span class="nm mono">{s.name}</span><span class="dt">{s.detail}</span>
                </summary>
                <div class="stage-inspector">
                <div class="inspect-head">
                  <span>{s.name}</span>
                  <em>{s.detail || 'stage details'}</em>
                </div>

                {#if s.name === 'parse' || s.name === 'typecheck'}
                  {#if candidateCode || delivered?.code}
                    <Code text={candidateCode || delivered?.code} />
                  {:else}
                    <div class="note">candidate code appears here once the implementer emits it</div>
                  {/if}
                {:else if s.name === 'smoke'}
                  <div class="inspect-stack">
                    <div class="test-item">
                      <b>smoke input</b>
                      <code>{oracle?.example_tests?.[0]?.input_repr || 'first valid generated input'}</code>
                      <code>{stageDetail('smoke')}</code>
                    </div>
                    {#if candidateCode || delivered?.code}<Code text={candidateCode || delivered?.code} />{/if}
                  </div>
                {:else if s.name === 'examples'}
                  {#if oracle?.example_tests?.length}
                    <div class="test-list">
                      {#each oracle.example_tests as ex}
                        <div class="test-item">
                          <b>[{ex.boundary_category}]</b>
                          <code>{ex.input_repr}</code>
                          <code>=> {ex.expected_repr}</code>
                        </div>
                      {/each}
                    </div>
                  {:else}
                    <div class="note">{oracle?.example_count || 0} example tests ran, but this run did not stream their bodies. Restart the Python server and rerun to inspect them.</div>
                  {/if}
                {:else if s.name === 'properties'}
                  {#if oracle?.property_tests?.length}
                    <div class="test-list">
                      {#each oracle.property_tests as prop}
                        <div class="test-item property">
                          <b>{prop.name}</b>
                          <code>{prop.strategy}</code>
                          <pre>{prop.code}</pre>
                        </div>
                      {/each}
                    </div>
                  {:else if oracle?.property_names?.length}
                    <div class="test-list">
                      {#each oracle.property_names as name}
                        <div class="test-item"><b>{name}</b><code>property body was not streamed for this run</code><code>{stageDetail('properties')}</code></div>
                      {/each}
                    </div>
                  {:else}
                    <div class="note">property tests appear here after the adversary emits them</div>
                  {/if}
                {:else if s.name === 'differential'}
                  {#if oracle?.differential_reference}
                    <Code text={oracle.differential_reference} />
                  {:else}
                    <div class="note">{oracle?.has_reference ? 'A differential reference ran, but this run did not stream the reference code. Restart the Python server and rerun.' : 'No differential reference was generated for this problem.'}</div>
                  {/if}
                {:else}
                  <div class="note">{s.detail || 'No artifact for this stage yet.'}</div>
                {/if}
                </div>
              </details>
            {/each}
            {#if ce}
              <div class="ce" in:fly={{ y: 14, duration: 420 }}>
                <div class="ce-h">counterexample</div>
                <div class="ce-row"><span>in</span><b class="mono">{ce.input_repr}</b></div>
                <div class="ce-row"><span>got</span><b class="mono bad">{ce.actual_repr}</b></div>
                <div class="ce-row"><span>want</span><b class="mono good">{ce.expected_repr}</b></div>
              </div>
            {/if}
            {#if surgeon}<div class="patch" in:fly={{ y: 10, duration: 320 }}>{surgeon}</div>{/if}
            {#if delivered && mode === 'code'}
              <div class="verified-code" in:scale={{ start: 0.97, duration: 360 }}>
                <div class="vc-h">{delivered.kind === 'verified' ? '✓ verified, shipped' : '⚠ floor'}</div>
                <Code text={delivered.code} />
              </div>
            {/if}
          </div>
        {/if}
      </section>
    {/if}

    {#if mode === 'app'}
      <section class="card pipeline">
        <div class="card-h"><span class="t">Crucible</span><span class="meta mono accent">{Math.round($cbTps).toLocaleString()} tok/s</span></div>
        <div class="agents col">
          {#each agentList as [id, label, d]}
            <div class="agent {agents[id] || 'idle'}"><div class="ring"><svg viewBox="0 0 24 24"><path d={d} /></svg></div><span>{label}</span></div>
          {/each}
        </div>
        <div class="flow">
          {#if stages.length === 0}
            <div class="empty-flow">
              <span>contract</span>
              <span>runtime check</span>
              <span>vision QA</span>
            </div>
          {/if}
          {#each stages as s (s.name)}
            <div class="row {s.status}" animate:flip={{ duration: 300 }} in:fly={{ y: 8, duration: 300 }}><i class="mk"></i><span class="nm mono">{s.name}</span></div>
          {/each}
        </div>
      </section>
      <section class="card preview">
        <div class="card-h">
          <div class="tabs-mini">
            <button class:on={tab === 'app'} onclick={() => (tab = 'app')}>Preview</button>
            <button class:on={tab === 'code'} onclick={() => (tab = 'code')}>Code</button>
          </div>
          {#if appHtml}<span class="tag {appVerified ? 'ok' : 'warn'}">{appVerified ? 'verified, clickable' : 'live'}</span>{/if}
        </div>
        <div class="art">
          {#if tab === 'app'}
            <div class="frame-wrap">
              {#if appHtml}<iframe title="app" srcdoc={appHtml} in:fade={{ duration: 400 }} sandbox="allow-scripts allow-same-origin allow-forms allow-modals allow-popups"></iframe>
              {:else}<div class="empty">it builds here, live and clickable</div>{/if}
            </div>
          {:else}
            <Code text={appHtml} />
          {/if}
        </div>
      </section>
    {/if}

    {#if mode === 'repo'}
      <section class="card artifacts">
        <div class="card-h">
          <div class="tabs-mini">
            <button class:on={tab === 'plan'} onclick={() => (tab = 'plan')}>Plan</button>
            <button class:on={tab === 'test'} onclick={() => (tab = 'test')}>Test</button>
            <button class:on={tab === 'diff'} onclick={() => (tab = 'diff')}>{fixSource === 'snippet' ? 'Fixed' : 'Diff'}</button>
            <button class:on={tab === 'output'} onclick={() => (tab = 'output')}>Output</button>
          </div>
          {#if verdict}<span class="tag {verdict === 'verified' ? 'ok' : 'warn'}">{verdict}</span>{/if}
        </div>
        <div class="art">
          {#if tab === 'plan'}
            <div class="plan">
              {#if spec}
                <div class="plan-row"><span>task</span><b>{spec.function_name}</b></div>
                <div class="plan-row"><span>verify</span><b class="mono">{spec.signature}</b></div>
                <div class="plan-row"><span>files</span><b class="mono">{spec.description}</b></div>
              {:else}<div class="note">{fixSource === 'snippet' ? 'Run to freeze the repair contract and generate adversarial tests.' : 'investigating the repo...'}</div>{/if}
            </div>
          {:else if tab === 'test'}
            {#if fixSource === 'snippet'}
              <div class="test-panel embedded">
                {#if oracle}
                  <div class="test-summary">
                    <span>{oracleExampleCount()} examples</span>
                    <span>{oraclePropertyCount()} properties</span>
                    <span>{oracle.has_reference ? 'reference diff' : 'no reference diff'}</span>
                  </div>
                  <div class="test-list">
                    {#each (oracle.example_tests || []).slice(0, 8) as ex}
                      <div class="test-item">
                        <b>[{ex.boundary_category}]</b>
                        <code>{ex.input_repr}</code>
                        <code>=> {ex.expected_repr}</code>
                      </div>
                    {/each}
                    {#each (oracle.property_tests || []).slice(0, 4) as prop}
                      <div class="test-item property">
                        <b>{prop.name}</b>
                        <code>{prop.strategy}</code>
                        <pre>{prop.code}</pre>
                      </div>
                    {/each}
                    {#if oracle.differential_reference}
                      <div class="test-item property">
                        <b>differential reference</b>
                        <pre>{oracle.differential_reference}</pre>
                      </div>
                    {/if}
                  </div>
                {:else}
                  <div class="note">generated tests appear here after the adversary finishes</div>
                {/if}
              </div>
            {:else}
              <div class="art-h">{test?.path || 'test the blind adversary wrote'}</div><Code text={test?.content} />
            {/if}
          {:else if tab === 'diff'}
            {#if fixSource === 'snippet'}
              {#if delivered?.code || diff}
                <Code text={delivered?.code || diff} />
              {:else}
                <div class="note">fixed code appears here after Run</div>
              {/if}
            {:else}
              <Code text={diff} diff={true} />
            {/if}
          {:else}
            {#if fixSource === 'snippet'}
              <div class="art-h">{gauntletOutputTitle()}</div>
              {#if stages.length || ce || surgeon || delivered}
                <div class="output-stack">
                  {#each stages as s (s.name)}
                    <div class="output-row {s.status}">
                      <i class="mk"></i>
                      <span class="nm mono">{s.name}</span>
                      <b>{s.detail || 'running'}</b>
                    </div>
                  {/each}
                  {#if ce}
                    <div class="ce compact">
                      <div class="ce-h">counterexample</div>
                      <div class="ce-row"><span>in</span><b class="mono">{ce.input_repr}</b></div>
                      <div class="ce-row"><span>got</span><b class="mono bad">{ce.actual_repr}</b></div>
                      <div class="ce-row"><span>want</span><b class="mono good">{ce.expected_repr}</b></div>
                    </div>
                  {/if}
                  {#if surgeon}<div class="patch">{surgeon}</div>{/if}
                </div>
              {:else}
                <div class="note">runtime output appears here while the pasted code is tested and repaired</div>
              {/if}
            {:else}
              <div class="art-h">{testOutput ? (testOutput.passed ? '✓ tests passed' : '✕ tests failed') : 'test output'}</div>
              <Code text={testOutput?.text} />
            {/if}
          {/if}
        </div>
      </section>
    {/if}
  </main>
</div>

<style>
  .app { position: relative; width: min(100%, 1300px); height: 100dvh; display: flex; flex-direction: column; margin: 0 auto; padding: 22px 28px 26px; gap: 16px; overflow: hidden; }
  header { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-width: 0; }
  .brand { display: flex; align-items: center; gap: 11px; min-width: 0; }
  .logo { width: 26px; height: 26px; border-radius: 8px; background: linear-gradient(140deg, var(--accent), var(--violet)); box-shadow: 0 6px 18px color-mix(in srgb, var(--accent) 40%, transparent); }
  .name { font-weight: 700; font-size: 17px; letter-spacing: 0; white-space: nowrap; }
  .right { display: flex; align-items: center; justify-content: flex-end; gap: 10px; min-width: 0; }
  .chip { font-size: 12px; color: var(--muted); display: inline-flex; align-items: center; gap: 7px; padding: 6px 11px; border-radius: 99px; background: var(--surface); box-shadow: var(--shadow); white-space: nowrap; }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--green); box-shadow: 0 0 8px var(--green); animation: pulse 1.8s infinite; }
  .icon { font-size: 11px; color: var(--muted); padding: 7px 10px; border-radius: 9px; background: var(--surface); box-shadow: var(--shadow); transition: transform .2s var(--ease); }
  .memory-toggle { min-width: 72px; }
  .icon:hover { transform: translateY(-1px); color: var(--ink); }

  .memory-popover { position: absolute; top: 58px; right: 28px; width: min(360px, calc(100% - 56px)); z-index: 20; padding: 10px; border-radius: 13px; background: color-mix(in srgb, var(--surface) 96%, var(--bg)); border: 1px solid var(--line); box-shadow: var(--shadow-lift); }
  .memory-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 3px 4px 8px; }
  .memory-head b { font-size: 12px; font-weight: 700; }
  .memory-head button { font-size: 11px; color: var(--muted); font-weight: 650; }
  .memory-empty { padding: 16px 8px; color: var(--faint); font-size: 12px; text-align: center; }
  .memory-row { width: 100%; display: grid; grid-template-columns: 1fr auto; gap: 3px 10px; align-items: baseline; text-align: left; padding: 9px 10px; border-radius: 10px; transition: background .2s var(--ease), transform .2s var(--ease); }
  .memory-row:hover { background: var(--bg); transform: translateY(-1px); }
  .memory-row span { grid-column: 1 / -1; color: var(--accent); font-size: 10px; font-weight: 750; text-transform: uppercase; letter-spacing: .06em; }
  .memory-row b { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink); font-size: 12.5px; font-weight: 650; }
  .memory-row em { color: var(--faint); font-style: normal; font-size: 11px; }

  .proof-strip { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 11px 14px; border: 1px solid var(--line); border-radius: 13px; background: color-mix(in srgb, var(--surface) 88%, var(--bg)); box-shadow: var(--shadow); }
  .proof-copy { min-width: 0; display: grid; grid-template-columns: auto minmax(0, max-content) minmax(180px, 1fr); align-items: baseline; gap: 10px; }
  .proof-copy span { color: var(--accent); font-size: 10.5px; font-weight: 750; letter-spacing: .09em; text-transform: uppercase; white-space: nowrap; }
  .proof-copy b { font-size: 13px; font-weight: 680; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .proof-copy em { min-width: 0; color: var(--muted); font-style: normal; font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .proof-meta { display: flex; align-items: center; justify-content: flex-end; gap: 6px; flex-wrap: wrap; flex-shrink: 0; }
  .proof-meta span, .mini-action { min-height: 24px; display: inline-flex; align-items: center; border-radius: 7px; padding: 4px 8px; font-size: 11px; font-weight: 650; line-height: 1; }
  .proof-meta span { color: var(--muted); background: var(--bg); }
  .proof-strip.done { border-color: color-mix(in srgb, var(--green) 26%, var(--line)); }
  .proof-strip.done .proof-copy span { color: var(--green); }
  .mini-action { color: var(--accent); background: var(--accent-soft); transition: transform .2s var(--ease), background .2s var(--ease); }
  .mini-action:hover { transform: translateY(-1px); background: color-mix(in srgb, var(--accent-soft) 70%, var(--surface)); }

  .bar { display: flex; gap: 10px; align-items: center; min-width: 0; }
  .seg { position: relative; display: grid; grid-template-columns: repeat(3, 1fr); background: var(--surface); border-radius: 12px; padding: 4px; box-shadow: var(--shadow); flex: 0 0 auto; min-width: 220px; }
  .seg-pill { position: absolute; top: 4px; bottom: 4px; left: 4px; width: calc((100% - 8px) / 3); border-radius: 9px; background: var(--accent-soft); transform: translateX(calc(var(--i) * 100%)); transition: transform .42s var(--ease); }
  .seg-btn { position: relative; padding: 8px 16px; font-size: 13.5px; font-weight: 600; color: var(--muted); border-radius: 9px; transition: color .3s var(--ease); }
  .seg-btn.on { color: var(--accent); }
  .case-picker { height: 46px; min-width: 162px; display: flex; align-items: center; gap: 8px; padding: 0 11px; border-radius: 12px; background: var(--surface); box-shadow: var(--shadow); flex-shrink: 0; }
  .case-picker span { color: var(--accent); font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: .07em; }
  .case-picker select { min-width: 0; max-width: 132px; border: 0; outline: 0; background: transparent; color: var(--muted); font: inherit; font-size: 12.5px; font-weight: 650; cursor: pointer; }
  .run { height: 46px; padding: 0 26px; border-radius: 12px; font-weight: 650; font-size: 14.5px; color: #fff; background: var(--accent); box-shadow: 0 8px 22px color-mix(in srgb, var(--accent) 36%, transparent); transition: transform .22s var(--ease); flex-shrink: 0; }
  .run:hover:not(:disabled) { transform: translateY(-2px); }
  .run.busy { background: color-mix(in srgb, var(--accent) 60%, var(--muted)); }

  .composer { display: grid; grid-template-columns: 1fr; gap: 10px; min-height: 0; }
  .composer.repo { grid-template-columns: minmax(0, .9fr) minmax(260px, .62fr); }
  .editor-card { min-width: 0; border-radius: 12px; background: var(--surface); box-shadow: var(--shadow); border: 1px solid var(--line); overflow: hidden; }
  .editor-head { min-height: 38px; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 12px 7px; border-bottom: 1px solid var(--line); }
  .editor-head span { color: var(--accent); font-size: 10px; font-weight: 800; letter-spacing: .07em; text-transform: uppercase; white-space: nowrap; }
  .editor-head em { color: var(--faint); font-size: 11.5px; font-style: normal; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .task-editor, .code-editor, .stage-code-editor { width: 100%; border: 0; outline: none; resize: none; color: var(--ink); background: transparent; }
  .task-editor { height: 96px; padding: 12px 14px; font-size: 13.5px; line-height: 1.45; }
  .source-tabs { display: inline-flex; align-items: center; gap: 3px; padding: 3px; border-radius: 9px; background: var(--bg); flex-shrink: 0; }
  .source-tabs button { min-height: 25px; padding: 4px 9px; border-radius: 7px; color: var(--muted); font-size: 11.5px; font-weight: 650; white-space: nowrap; }
  .source-tabs button.on { color: var(--ink); background: var(--surface); box-shadow: var(--shadow); }
  .repo-line { height: 96px; display: flex; align-items: center; gap: 10px; padding: 0 14px; }
  .repo-line span { color: var(--accent); font-size: 10px; font-weight: 800; letter-spacing: .07em; text-transform: uppercase; }
  .repo-line input { width: 100%; min-width: 0; border: 0; outline: none; background: transparent; color: var(--ink); font-size: 13.5px; }
  .stage-code-editor { flex: 1; min-height: 0; margin: 0 14px 14px; padding: 14px; border-radius: var(--r-sm); background: var(--bg); font-family: var(--mono); font-size: 12px; line-height: 1.55; white-space: pre; overflow: auto; }

  .stage { flex: 1; min-height: 0; display: grid; gap: 16px; }
  .stage.code { grid-template-columns: 1fr 1.2fr; }
  .stage.app { grid-template-columns: .72fr 1.55fr; }
  .stage.repo { grid-template-columns: .82fr 1.4fr; }
  .stage.repo.snippet { grid-template-columns: minmax(0, 1fr) minmax(0, 1.14fr); }

  .card { background: var(--surface); border-radius: var(--r); box-shadow: var(--shadow); display: flex; flex-direction: column; overflow: hidden; min-width: 0; min-height: 0; }
  .card-h { display: flex; align-items: center; justify-content: space-between; padding: 13px 16px 11px; gap: 10px; }
  .card-h .t { font-weight: 650; font-size: 14px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .card-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; min-width: 0; }
  .meta { font-size: 12.5px; color: var(--muted); flex-shrink: 0; }
  .accent { color: var(--accent); font-weight: 600; }

  .codepane { flex: 1; overflow: auto; margin: 0 14px 0; padding: 13px 14px; background: var(--bg); border-radius: var(--r-sm); font-family: var(--mono); font-size: 11.5px; line-height: 1.6; color: var(--muted); white-space: pre-wrap; }
  .foot { display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; }

  .agents { display: flex; justify-content: space-between; gap: 6px; padding: 4px 16px 14px; min-width: 0; }
  .agents.col { flex-direction: column; gap: 9px; padding-bottom: 12px; }
  .agents.col .agent { flex-direction: row; gap: 10px; justify-content: flex-start; }
  .agent { display: flex; flex-direction: column; align-items: center; gap: 6px; flex: 1 1 0; min-width: 0; color: var(--faint); font-size: 11px; font-weight: 500; transition: color .35s var(--ease); }
  .agent span { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .agent .ring { width: 38px; height: 38px; border-radius: 11px; display: grid; place-items: center; background: var(--bg); border: 1px solid var(--line); transition: all .4s var(--ease); flex-shrink: 0; }
  .agent svg { width: 17px; height: 17px; fill: none; stroke: var(--faint); stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; transition: stroke .35s var(--ease); }
  .agent.active { color: var(--ink); }
  .agent.active .ring { border-color: var(--accent); background: var(--accent-soft); transform: translateY(-3px) scale(1.08); box-shadow: 0 8px 20px color-mix(in srgb, var(--accent) 30%, transparent); }
  .agent.active svg { stroke: var(--accent); }
  .agent.done { color: var(--muted); }
  .agent.done .ring { border-color: color-mix(in srgb, var(--green) 45%, var(--line)); background: var(--green-soft); }
  .agent.done svg { stroke: var(--green); }

  .flow { flex: 1; overflow: auto; padding: 4px 14px 14px; display: flex; flex-direction: column; gap: 7px; }
  .empty-flow { flex: 1; min-height: 170px; display: grid; place-content: center; gap: 8px; color: var(--faint); font-size: 12px; text-align: center; }
  .empty-flow span { display: inline-flex; justify-content: center; padding: 6px 10px; border-radius: 8px; background: var(--bg); font-weight: 600; }
  .stage-details { display: block; }
  .stage-details summary { list-style: none; cursor: pointer; }
  .stage-details summary::-webkit-details-marker { display: none; }
  .row { width: 100%; display: flex; align-items: center; gap: 11px; padding: 9px 12px; border-radius: var(--r-sm); background: var(--bg); border: 1px solid transparent; text-align: left; transition: border-color .2s var(--ease), background .2s var(--ease), transform .2s var(--ease); }
  .row:hover, .stage-details[open] .row { border-color: color-mix(in srgb, var(--accent) 34%, var(--line)); background: color-mix(in srgb, var(--accent-soft) 44%, var(--bg)); }
  .stage-details[open] .row { transform: translateX(2px); }
  .row .mk { width: 16px; height: 16px; border-radius: 5px; flex-shrink: 0; background: var(--line-2); position: relative; transition: background .35s; }
  .row.running .mk { background: var(--accent); animation: pulse 1s infinite; }
  .row.pass .mk { background: var(--green); }
  .row.pass .mk::after { content: '✓'; position: absolute; inset: 0; display: grid; place-items: center; color: #fff; font-size: 10px; font-weight: 800; }
  .row.fail { background: var(--red-soft); }
  .row.fail .mk { background: var(--red); }
  .row.fail .mk::after { content: '✕'; position: absolute; inset: 0; display: grid; place-items: center; color: #fff; font-size: 10px; font-weight: 800; }
  .row.skip { opacity: .5; }
  .row .nm { font-size: 12.5px; color: var(--ink); min-width: 88px; }
  .row .dt { font-size: 11.5px; color: var(--faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .ce { border-radius: var(--r-sm); padding: 13px 15px; background: var(--red-soft); border: 1px solid color-mix(in srgb, var(--red) 30%, transparent); }
  .ce-h { font-size: 11px; text-transform: uppercase; letter-spacing: .1em; color: var(--red); font-weight: 700; margin-bottom: 7px; }
  .ce-row { display: grid; grid-template-columns: 40px 1fr; gap: 8px; font-size: 12.5px; padding: 1px 0; }
  .ce-row span { color: var(--muted); } .ce-row b { font-weight: 500; }
  .bad { color: var(--red); } .good { color: var(--green); }
  .patch { font-size: 12.5px; color: var(--ink); padding: 11px 14px; border-radius: var(--r-sm); background: color-mix(in srgb, var(--amber) 9%, var(--surface)); border: 1px solid color-mix(in srgb, var(--amber) 26%, transparent); }
  .verified-code { border-radius: var(--r-sm); overflow: hidden; border: 1px solid color-mix(in srgb, var(--green) 35%, var(--line)); }
  .vc-h { font-size: 12px; font-weight: 700; color: var(--green); padding: 9px 13px; background: var(--green-soft); }

  .stage-inspector { margin-top: 7px; border-radius: var(--r-sm); border: 1px solid color-mix(in srgb, var(--accent) 24%, var(--line)); background: var(--bg); overflow: auto; max-height: min(380px, 46dvh); }
  .inspect-head { min-height: 36px; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 12px; border-bottom: 1px solid var(--line); background: var(--surface); }
  .inspect-head span { color: var(--accent); font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
  .inspect-head em { min-width: 0; color: var(--muted); font-size: 11.5px; font-style: normal; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .stage-inspector .test-list, .inspect-stack { padding: 12px; }
  .inspect-stack { display: flex; flex-direction: column; gap: 10px; }
  :global(.stage-inspector .cv) { max-height: 310px; }

  .candidate-panel, .test-panel { flex: 1; min-height: 0; margin: 0 14px 14px; border-radius: var(--r-sm); background: var(--bg); overflow: hidden; display: flex; flex-direction: column; }
  .candidate-head { min-height: 34px; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 14px; border-bottom: 1px solid var(--line); }
  .candidate-head span { color: var(--accent); font-size: 11px; font-weight: 750; text-transform: uppercase; letter-spacing: .07em; }
  .candidate-head em { color: var(--faint); font-size: 11.5px; font-style: normal; }
  .test-panel { padding: 12px; gap: 10px; overflow: auto; }
  .test-summary { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .test-summary span { min-height: 24px; display: inline-flex; align-items: center; border-radius: 7px; padding: 4px 8px; color: var(--accent); background: var(--accent-soft); font-size: 11px; font-weight: 700; }
  .test-list { display: flex; flex-direction: column; gap: 8px; }
  .test-item { display: grid; grid-template-columns: minmax(90px, .45fr) minmax(0, 1fr) minmax(0, .65fr); gap: 8px; align-items: start; padding: 9px 10px; border-radius: 9px; background: var(--surface); border: 1px solid var(--line); }
  .test-item b { color: var(--ink); font-size: 11.5px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .test-item code, .test-item pre { min-width: 0; overflow: auto; color: var(--muted); font-family: var(--mono); font-size: 11px; line-height: 1.45; white-space: pre-wrap; }
  .test-item.property { grid-template-columns: minmax(90px, .35fr) minmax(0, .8fr) minmax(0, 1fr); }
  .test-panel.embedded { margin: 0; border-radius: 0; background: transparent; }
  .output-stack { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 8px; padding: 12px; }
  .output-row { display: grid; grid-template-columns: 16px minmax(86px, .32fr) minmax(0, 1fr); align-items: center; gap: 9px; padding: 9px 10px; border-radius: 9px; background: var(--surface); border: 1px solid var(--line); }
  .output-row .mk { width: 16px; height: 16px; border-radius: 5px; background: var(--line-2); position: relative; }
  .output-row.running .mk { background: var(--accent); animation: pulse 1s infinite; }
  .output-row.pass .mk { background: var(--green); }
  .output-row.pass .mk::after { content: '✓'; position: absolute; inset: 0; display: grid; place-items: center; color: #fff; font-size: 10px; font-weight: 800; }
  .output-row.fail .mk, .output-row.error .mk { background: var(--red); }
  .output-row.fail .mk::after, .output-row.error .mk::after { content: '✕'; position: absolute; inset: 0; display: grid; place-items: center; color: #fff; font-size: 10px; font-weight: 800; }
  .output-row .nm { color: var(--ink); font-size: 12px; }
  .output-row b { min-width: 0; color: var(--muted); font-size: 11.5px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ce.compact { padding: 11px 12px; }

  .tag { font-size: 11px; font-weight: 600; padding: 4px 9px; border-radius: 7px; }
  .tag.warn { background: color-mix(in srgb, var(--amber) 14%, transparent); color: var(--amber); }
  .tag.ok { background: var(--green-soft); color: var(--green); }

  .tabs-mini { display: flex; gap: 2px; background: var(--bg); border-radius: 9px; padding: 3px; }
  .tabs-mini button { font-size: 12px; font-weight: 600; color: var(--muted); padding: 5px 12px; border-radius: 7px; transition: all .25s var(--ease); }
  .tabs-mini button.on { background: var(--surface); color: var(--ink); box-shadow: var(--shadow); }

  .art { flex: 1; min-height: 0; margin: 2px 14px 14px; border-radius: var(--r-sm); background: var(--bg); overflow: hidden; display: flex; flex-direction: column; }
  .art-h { font-family: var(--mono); font-size: 11px; color: var(--muted); padding: 9px 14px 0; }
  .frame-wrap { flex: 1; position: relative; background: #fff; overflow: hidden; }
  iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }
  .preview iframe { left: -10%; width: 120%; height: 120%; transform: scale(.84); transform-origin: top center; }
  .frame-wrap .empty { position: absolute; inset: 0; display: grid; place-items: center; color: var(--faint); font-size: 13px; }
  .note { color: var(--faint); font-size: 12.5px; padding: 18px; }
  .plan { padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  .plan-row { display: grid; grid-template-columns: 56px 1fr; gap: 10px; font-size: 13px; align-items: baseline; }
  .plan-row span { color: var(--muted); text-transform: uppercase; font-size: 10px; letter-spacing: .08em; }
  .plan-row b { font-weight: 500; color: var(--ink); }

  @keyframes pulse { 50% { opacity: .4; } }
  @media (max-width: 900px) {
    .app { height: auto; min-height: 100dvh; overflow: visible; padding: 18px; }
    .bar { flex-wrap: wrap; align-items: stretch; }
    .seg { flex: 1 1 210px; min-width: 0; }
    .case-picker { flex: 1 1 150px; min-width: 145px; }
    .run { min-width: 96px; }
    .composer.repo { grid-template-columns: 1fr; }
    .task-editor { height: 122px; }
    .stage { flex: 0 0 auto; grid-template-columns: 1fr !important; grid-auto-rows: auto; }
    .card { min-height: 330px; }
    .source-pane { min-height: 380px; }
    .stage.app .preview { min-height: 520px; }
    .stage.repo .artifacts { min-height: 460px; }
  }
  @media (max-width: 560px) {
    .app { padding: 16px 14px 18px; gap: 12px; }
    header { flex-wrap: wrap; gap: 10px; }
    .right { flex: 1 1 auto; justify-content: flex-start; gap: 8px; }
    .chip { font-size: 11.5px; padding: 6px 10px; }
    .icon { padding: 7px 9px; }
    .memory-popover { top: 88px; right: 14px; width: calc(100% - 28px); }
    .proof-strip { align-items: stretch; flex-direction: column; gap: 10px; padding: 12px; }
    .proof-copy { grid-template-columns: 1fr; gap: 4px; }
    .proof-copy b, .proof-copy em { white-space: normal; overflow: visible; }
    .proof-meta { justify-content: flex-start; }
    .bar { gap: 8px; }
    .seg { min-width: 0; }
    .case-picker { height: 44px; }
    .case-picker select { max-width: 118px; }
    .seg-btn { padding: 8px 10px; font-size: 13px; }
    .run { height: 44px; padding: 0 20px; min-width: 84px; }
    .editor-head { align-items: flex-start; flex-direction: column; gap: 7px; }
    .task-editor { height: 136px; font-size: 13px; }
    .repo-line { height: 68px; }
    .stage-code-editor { margin: 0 10px 10px; font-size: 11.5px; }
    .card { border-radius: 14px; min-height: 300px; }
    .card-h { padding: 12px 14px 9px; }
    .card-actions { flex-wrap: wrap; gap: 7px; }
    .codepane { margin: 0 10px; padding: 12px; }
    .agents { padding: 4px 10px 12px; gap: 4px; }
    .agent { font-size: 10px; }
    .agent .ring { width: 34px; height: 34px; border-radius: 10px; }
    .agent svg { width: 16px; height: 16px; }
    .flow { padding: 4px 10px 12px; }
    .row { gap: 8px; padding: 8px 10px; }
    .row .nm { min-width: 72px; font-size: 11.5px; }
    .row .dt { font-size: 11px; }
    .foot { padding: 11px 14px; }
    .stage.app .preview,
    .stage.repo .artifacts { min-height: 430px; }
    .tabs-mini { overflow-x: auto; }
    .tabs-mini button { padding: 5px 10px; white-space: nowrap; }
    .art { margin: 2px 10px 10px; }
    .candidate-panel, .test-panel { margin: 0 10px 10px; }
    .test-item, .test-item.property { grid-template-columns: 1fr; }
    .plan-row { grid-template-columns: 48px 1fr; }
  }
  @media (max-width: 360px) {
    .name { font-size: 16px; }
    .seg-btn { padding-inline: 8px; }
    .chip { max-width: 156px; overflow: hidden; text-overflow: ellipsis; }
  }
  @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition-duration: .01ms !important; } }
</style>
