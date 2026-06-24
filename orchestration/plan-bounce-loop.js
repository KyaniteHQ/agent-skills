export const meta = {
  name: 'plan-bounce-loop',
  description:
    'Recursive adversarial plan-bounce (v2 of the adversarial-plan-bounce skill): bounce a plan with Codex -> auto-maximize the plan to fold in blockers -> re-bounce, accumulating open items in a ledger and auto-detecting convergence, until EXECUTE / SHIP-AS-IS / NEEDS-HUMAN.',
  phases: [
    { title: 'Bounce', detail: 'Codex adversarial scoring round over the plan (read-only)' },
    { title: 'Maximize', detail: 'fold accumulated blockers + high/critical findings into the plan file' },
  ],
}

// ----------------------------------------------------------------------------------------------------
// Config (from Workflow args). plan + repo are required; everything else has a default.
// ----------------------------------------------------------------------------------------------------
const cfg = typeof args === 'string' ? JSON.parse(args) : args || {}
const PLAN = cfg.plan
const REPO = cfg.repo
if (!PLAN || !REPO) throw new Error('plan-bounce-loop: args must include { plan, repo }')
const SCOPE = cfg.scope || 'full plan'
const FOCUS = cfg.focus || ''
const TARGET = cfg.target || 95
const MAX_ROUNDS = cfg.maxRounds || 6
const IMPROVE_DELTA = cfg.improveDelta != null ? cfg.improveDelta : 3
// slug is derived from the plan path only (so the file bounced is always the file maximized).
const slug = (cfg.slug || PLAN.replace(/\\/g, '/').split('/').pop().replace(/\.md$/i, '')).trim()
const WORKSPACE = `plan-bounce/${slug}`
const DRIVER = 'skills/adversarial-plan-bounce/scripts/bounce_codex.py'

const sq = (s) => "'" + String(s).replace(/'/g, "'\\''") + "'"
const iterDirFor = (round) => `${WORKSPACE}/iteration-${String(round).padStart(3, '0')}`
const normKey = (t) => (t || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().slice(0, 80)

// ----------------------------------------------------------------------------------------------------
// Structured-output schemas (full plan-review.schema.json field set -- findings KEEP body/plan_section/
// confidence so high/critical findings survive into the ledger and accumulated-blockers.json).
// ----------------------------------------------------------------------------------------------------
const BOUNCE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: [
    'score', 'verdict', 'summary', 'structural_blockers', 'findings',
    'held_decisions', 'execution_mode_clear', 'done',
  ],
  properties: {
    score: { type: 'integer', minimum: 0, maximum: 100 },
    verdict: { type: 'string' },
    summary: { type: 'string' },
    structural_blockers: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['title', 'why', 'plan_section', 'recommendation'],
        properties: {
          title: { type: 'string' }, why: { type: 'string' },
          plan_section: { type: 'string' }, recommendation: { type: 'string' },
        },
      },
    },
    findings: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['severity', 'title', 'body', 'plan_section', 'confidence', 'recommendation'],
        properties: {
          severity: { type: 'string' }, title: { type: 'string' }, body: { type: 'string' },
          plan_section: { type: 'string' }, confidence: { type: 'number' },
          recommendation: { type: 'string' },
        },
      },
    },
    held_decisions: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['decision', 'why_held', 'owner'],
        properties: {
          decision: { type: 'string' }, why_held: { type: 'string' }, owner: { type: 'string' },
        },
      },
    },
    execution_mode_clear: { type: 'boolean' },
    done: { type: 'boolean' },
  },
}

const MAXIMIZE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['edited', 'plan_path', 'changelog', 'moved_to_held', 'unaddressed'],
  properties: {
    edited: { type: 'boolean' },
    plan_path: { type: 'string' },
    changelog: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['item', 'plan_section', 'change'],
        properties: { item: { type: 'string' }, plan_section: { type: 'string' }, change: { type: 'string' } },
      },
    },
    moved_to_held: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['item', 'why_human'],
        properties: { item: { type: 'string' }, why_human: { type: 'string' } },
      },
    },
    unaddressed: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['item', 'reason'],
        properties: { item: { type: 'string' }, reason: { type: 'string' } },
      },
    },
  },
}

// ----------------------------------------------------------------------------------------------------
// Accumulated ledger (the fix for blocker reappearance / oscillation). Keyed by normalized title; each
// entry keeps full schema fields + firstRound/lastRound/timesOpened/status. An item Codex stops
// reporting is marked 'resolved'; timesOpened catches whack-a-mole even across non-consecutive rounds.
// ----------------------------------------------------------------------------------------------------
const seen = new Map()
const trajectory = []

function currentOpen(review) {
  const items = []
  for (const b of review.structural_blockers) items.push({ kind: 'blocker', ...b })
  for (const f of review.findings) {
    if (f.severity === 'critical' || f.severity === 'high') items.push({ kind: 'finding', ...f })
  }
  return items
}

function mergeLedger(round, openItems) {
  const openKeys = new Set(openItems.map((i) => normKey(i.title)))
  for (const [k, v] of seen) {
    if (v.status === 'open' && !openKeys.has(k)) v.status = 'resolved'
  }
  for (const it of openItems) {
    const k = normKey(it.title)
    const prev = seen.get(k)
    if (prev) {
      seen.set(k, { ...prev, ...it, lastRound: round, timesOpened: prev.timesOpened + 1, status: 'open' })
    } else {
      seen.set(k, { ...it, firstRound: round, lastRound: round, timesOpened: 1, status: 'open' })
    }
  }
}

function openLedger() {
  return [...seen.values()].filter((v) => v.status === 'open')
}

// Synthetic prior-round review in the EXACT plan-review.schema.json shape (all required keys, full
// per-item fields incl. finding.body) so the driver's extract_prev_blockers consumes it unchanged.
function buildLedgerReview(prevReview) {
  const open = openLedger()
  return {
    score: prevReview.score,
    verdict: prevReview.verdict,
    summary: 'Synthetic accumulated-open-items ledger from prior rounds (not a fresh review).',
    structural_blockers: open
      .filter((v) => v.kind === 'blocker')
      .map((v) => ({ title: v.title, why: v.why, plan_section: v.plan_section, recommendation: v.recommendation })),
    findings: open
      .filter((v) => v.kind === 'finding')
      .map((v) => ({
        severity: v.severity, title: v.title, body: v.body,
        plan_section: v.plan_section, confidence: v.confidence, recommendation: v.recommendation,
      })),
    held_decisions: [],
    execution_mode_clear: prevReview.execution_mode_clear,
    resolved_prior_blockers: [],
    remaining_prior_blockers: [],
  }
}

// ----------------------------------------------------------------------------------------------------
// Convergence decision -- encodes the documented stop heuristic. Reads the accumulated open set + the
// score trajectory. Both success terminals REQUIRE execution_mode_clear=true.
// ----------------------------------------------------------------------------------------------------
function decide(round, review, openBlockers, openHigh, whackAMole) {
  if (review.done) {
    return { recommendation: 'EXECUTE', reason: 'score>=target, 0 structural blockers, execution_mode_clear' }
  }
  const s = trajectory.map((t) => t.score)
  const n = s.length
  const regressed2 = n >= 3 && s[n - 1] - s[n - 3] < 0 // net negative over the last 2 rounds
  const plateau = n >= 3 && s[n - 1] - s[n - 2] < IMPROVE_DELTA && s[n - 2] - s[n - 3] < IMPROVE_DELTA
  const noStructural = openBlockers.length === 0 && openHigh.length === 0

  if (review.execution_mode_clear && plateau && noStructural) {
    return {
      recommendation: 'SHIP-AS-IS',
      reason: 'plateaued, executable, with no open structural blockers or high/critical findings; remaining surface = held decisions',
    }
  }
  if (regressed2) {
    return { recommendation: 'NEEDS-HUMAN', reason: 'score regressed over the last 2 rounds; the loop is not converging' }
  }
  if (whackAMole) {
    return { recommendation: 'NEEDS-HUMAN', reason: 'a blocker/finding has stayed open across >=3 rounds (whack-a-mole / unfixable in-plan)' }
  }
  if (plateau && !review.execution_mode_clear) {
    return { recommendation: 'NEEDS-HUMAN', reason: 'plateaued but execution_mode_clear is still false' }
  }
  if (round >= MAX_ROUNDS) {
    return { recommendation: 'NEEDS-HUMAN', reason: `maxRounds (${MAX_ROUNDS}) reached with open structural blockers / high findings` }
  }
  return null // keep looping
}

function finalReport(decision, lastReview) {
  const open = openLedger()
  return {
    recommendation: decision.recommendation,
    reason: decision.reason,
    trajectory: trajectory.map((t) => t.score),
    rounds: trajectory.length,
    final_score: lastReview ? lastReview.score : null,
    final_verdict: lastReview ? lastReview.verdict : null,
    final_done: lastReview ? lastReview.done : false,
    execution_mode_clear: lastReview ? lastReview.execution_mode_clear : false,
    open_items: open.map((v) => ({ kind: v.kind, title: v.title, recommendation: v.recommendation })),
    held_decisions: lastReview ? lastReview.held_decisions.map((h) => ({ decision: h.decision, owner: h.owner })) : [],
    artifacts_dir: WORKSPACE,
    plan_path: PLAN,
  }
}

// ----------------------------------------------------------------------------------------------------
// Agent prompts.
// ----------------------------------------------------------------------------------------------------
function bounceCmd(round, prevPath) {
  const parts = [
    'uv run --with jsonschema python', DRIVER,
    '--plan', sq(PLAN), '--repo', sq(REPO),
    '--iteration', String(round),
    '--workspace', sq(WORKSPACE),
    '--target-score', String(TARGET),
    '--scope', sq(SCOPE),
  ]
  if (FOCUS) parts.push('--focus', sq(FOCUS))
  if (round > 1) parts.push('--prev-blockers', sq(prevPath))
  return parts.join(' ')
}

function bouncePrompt(round, prevReview) {
  const iterDir = iterDirFor(round)
  const prevPath = `${iterDir}/accumulated-blockers.json`
  const ledgerStep =
    round > 1
      ? `2. Write this accumulated-open-items ledger to \`${prevPath}\` VERBATIM (already valid plan-review JSON):\n\`\`\`json\n${JSON.stringify(buildLedgerReview(prevReview), null, 2)}\n\`\`\``
      : `2. (Round 1 -- no prior blockers; skip the ledger file.)`
  return [
    `You are running ONE adversarial plan-bounce scoring round (round ${round}) inside the recursive loop for the target repo. This is READ-ONLY review: do NOT edit the plan or any repo file.`,
    ``,
    `Steps, in order:`,
    `1. \`mkdir -p ${iterDir}\``,
    ledgerStep,
    `3. Run the bounce driver EXACTLY as written (it invokes Codex in a read-only sandbox and can take several minutes; let it finish):`,
    `   ${bounceCmd(round, prevPath)}`,
    `4. Read \`${iterDir}/codex-review.json\` and \`${iterDir}/score.json\`. Return a structured object with the codex-review fields (score, verdict, summary, structural_blockers, findings, held_decisions, execution_mode_clear) PLUS \`done\` taken from score.json's "done". Preserve every finding's body / plan_section / confidence. Omit resolved_prior_blockers / remaining_prior_blockers from your return.`,
    ``,
    `If the driver exits non-zero or writes no codex-review.json even after its own fallback retries, return score 0, verdict "unsafe", execution_mode_clear false, done false, empty arrays, and put the failure reason in summary.`,
  ].join('\n')
}

function maximizePrompt(round, review, openItems) {
  return [
    `You are the MAXIMIZE step of the recursive plan-bounce loop. Round ${round} scored ${review.score}/100 (verdict ${review.verdict}); the plan is not yet execution-ready.`,
    ``,
    `Edit ONLY the plan markdown at: ${PLAN}`,
    `It MUST be under ~/.claude/plans/. If it is not, make NO edits and return edited:false (plan_path set, all arrays empty).`,
    `Do NOT touch any repo source/config/test file -- only the plan file. Use the Edit/Write tools.`,
    ``,
    `Fold in EVERY open item below so the next Codex round can mark it resolved. Use EXACT artifacts: real file paths, real commands WITH their flags, real symbol names. Use ASCII arrows (-> , <-) -- never unicode arrows (Codex flags those as paste corruption).`,
    ``,
    `Open structural blockers + high/critical findings:`,
    '```json',
    JSON.stringify(openItems, null, 2),
    '```',
    ``,
    `For each item choose exactly one:`,
    `- ADDRESS it: revise the plan so the blocker/finding no longer holds; record {item, plan_section, change} in changelog.`,
    `- It is genuinely a HUMAN/OWNER decision (provisioning, security sign-off, a scope choice only the owner can make): add it to a "Held decisions" section in the plan and record {item, why_human} in moved_to_held. Do NOT thrash on it round after round.`,
    `- You truly cannot address it here: record {item, reason} in unaddressed.`,
    ``,
    `Keep edits surgical and consistent with the plan's existing style. Return the structured changelog (edited, plan_path, changelog, moved_to_held, unaddressed).`,
  ].join('\n')
}

// One round of an agent can die on a transient API error (e.g. "Overloaded"). Retry once before
// treating it as terminal -- a transient blip must not end the whole loop.
async function agentOnce(prompt, opts) {
  let r = await agent(prompt, opts)
  if (!r) {
    log(`${opts.label}: agent returned nothing (transient?); retrying once ...`)
    r = await agent(prompt, opts)
  }
  return r
}

// ----------------------------------------------------------------------------------------------------
// The loop.
// ----------------------------------------------------------------------------------------------------
log(`plan-bounce-loop: ${slug} | target ${TARGET} | maxRounds ${MAX_ROUNDS} | improveDelta ${IMPROVE_DELTA}`)
let lastReview = null
let result = null

for (let round = 1; round <= MAX_ROUNDS; round++) {
  phase('Bounce')
  log(`Round ${round}: bouncing ${slug} ...`)
  const review = await agentOnce(bouncePrompt(round, lastReview), {
    label: `bounce r${round}`,
    phase: 'Bounce',
    schema: BOUNCE_SCHEMA,
  })
  if (!review) {
    result = finalReport(
      { recommendation: 'NEEDS-HUMAN', reason: `bounce agent died (infra) on round ${round}, even after a retry` },
      lastReview,
    )
    break
  }
  lastReview = review
  const openItems = currentOpen(review)
  mergeLedger(round, openItems)
  const openBlockers = openItems.filter((i) => i.kind === 'blocker')
  const openHigh = openItems.filter((i) => i.kind === 'finding')
  trajectory.push({
    round, score: review.score, nBlockers: openBlockers.length, nHigh: openHigh.length,
    executionModeClear: review.execution_mode_clear, done: review.done,
  })
  log(`Round ${round}: score ${review.score}/100, verdict ${review.verdict}, blockers ${openBlockers.length}, high-findings ${openHigh.length}, exec_mode_clear ${review.execution_mode_clear}, done ${review.done}`)

  // Driver-failure sentinel (the bounce agent returns score 0 + no items on a hard driver failure).
  if (review.score === 0 && openItems.length === 0 && !review.done) {
    result = finalReport({ recommendation: 'NEEDS-HUMAN', reason: `bounce driver failed on round ${round}: ${review.summary}` }, review)
    break
  }

  const whackAMole = openLedger().some((v) => v.timesOpened >= 3)
  const decision = decide(round, review, openBlockers, openHigh, whackAMole)
  if (decision) {
    result = finalReport(decision, review)
    break
  }

  phase('Maximize')
  log(`Round ${round}: maximizing the plan to fold in ${openItems.length} open item(s) ...`)
  const maxed = await agentOnce(maximizePrompt(round, review, openItems), {
    label: `maximize r${round}`,
    phase: 'Maximize',
    schema: MAXIMIZE_SCHEMA,
  })
  if (!maxed) {
    result = finalReport(
      { recommendation: 'NEEDS-HUMAN', reason: `maximize agent died (infra) on round ${round}, even after a retry` },
      review,
    )
    break
  }
  if (!maxed.edited) {
    result = finalReport(
      { recommendation: 'NEEDS-HUMAN', reason: `maximize declined to edit the plan on round ${round} (likely an owner-only decision)` },
      review,
    )
    break
  }
  log(`Round ${round}: plan updated (${maxed.changelog.length} changes, ${maxed.moved_to_held.length} held, ${maxed.unaddressed.length} unaddressed).`)
}

if (!result) {
  result = finalReport({ recommendation: 'NEEDS-HUMAN', reason: `maxRounds (${MAX_ROUNDS}) reached without convergence` }, lastReview)
}
log(`DONE: ${result.recommendation} after ${result.rounds} round(s). Trajectory: ${result.trajectory.join(' -> ')}`)
return result
