/**
 * SP-001 + SP-002 Integration Test
 *
 * Exercises BDI reasoning (SP-001) with temporal NEVER rule enforcement (SP-002)
 * against real repositories on the local filesystem.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

// SP-001: BDI engine
import {
  BeliefBase,
  PlanLibrary,
  ReasoningCycle,
  EventKind,
  BodyStepType,
  beliefKey,
} from '../../sp-001-bdi/src/index.js';

// SP-002: Temporal NEVER rules + escape hatch
import {
  TemporalStore,
  evaluateRule,
  evaluateAllRules,
  hashBeliefs,
  recordFailureWithBeliefs,
  shouldEscapeHatch,
} from '../../sp-002-temporal-never/src/index.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Real repo paths on disk */
const REPOS = {
  jsonRulesEngine: '/Users/ladislavbihari/myWork/Magic/json-rules-engine',
  xstate: '/Users/ladislavbihari/myWork/Magic/xstate',
};

/** A controllable clock so we can simulate time progression without sleeping. */
function createTestClock(startMs = 1000) {
  let now = startMs;
  return {
    now: () => now,
    advance: (ms) => { now += ms; },
  };
}

/** Read package.json from a real repo. Returns parsed object or null. */
function readRealPackageJson(repoPath) {
  const filePath = path.join(repoPath, 'package.json');
  if (!fs.existsSync(filePath)) return null;
  return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
}

/** Check for the presence of common repo patterns. */
function probeRepoPatterns(repoPath) {
  return {
    hasTests: fs.existsSync(path.join(repoPath, 'test')) ||
              fs.existsSync(path.join(repoPath, 'tests')) ||
              fs.existsSync(path.join(repoPath, '__tests__')),
    hasCI: fs.existsSync(path.join(repoPath, '.github')),
    hasTypes: fs.existsSync(path.join(repoPath, 'types')) ||
              fs.existsSync(path.join(repoPath, 'tsconfig.json')),
    hasReadme: fs.existsSync(path.join(repoPath, 'README.md')),
    hasLicense: fs.existsSync(path.join(repoPath, 'LICENSE')),
  };
}

// ---------------------------------------------------------------------------
// NEVER rules tailored to the integration scenario
// ---------------------------------------------------------------------------

const NEVER_WINDOW_MS = 60_000; // 60 seconds

/** NEVER-001: Don't re-analyze the same repo within 60 seconds. */
const neverReanalyzeRepo = {
  id: 'NEVER-001',
  description: 'Never re-analyze the same repo within 60 seconds',
  class: 'temporal-logical',
  windowMs: NEVER_WINDOW_MS,
  condition: (store, ctx) => {
    const cutoff = store.now() - NEVER_WINDOW_MS;
    const analyses = store.query(
      { entity: ctx.agentId, attribute: 'repo-analyzed', value: ctx.planId },
      cutoff,
    );
    return analyses.length === 0; // no recent analysis => allowed
  },
};

/** NEVER-002: Don't evaluate more than 5 engines simultaneously (cross-agent). */
const neverExceedConcurrentEvals = {
  id: 'NEVER-002',
  description: 'Never evaluate more than 5 engines simultaneously',
  class: 'cross-agent-aggregate',
  windowMs: 10_000,
  condition: (store, _ctx) => {
    const cutoff = store.now() - 10_000;
    // Count in-progress evaluations (started but not completed) across all agents
    const started = store.query({ attribute: 'eval-started' }, cutoff);
    const completed = store.query({ attribute: 'eval-completed' }, cutoff);
    const completedValues = new Set(completed.map((f) => `${f.entity}:${f.value}`));
    const inProgress = started.filter(
      (f) => !completedValues.has(`${f.entity}:${f.value}`),
    );
    return inProgress.length < 5;
  },
};

// ---------------------------------------------------------------------------
// BDI Plan Definitions
// ---------------------------------------------------------------------------

/**
 * Build plans for the repo-analysis agent.
 * Plans reference actions that the action handler will dispatch to real I/O.
 */
function buildPlans() {
  return [
    // Plan for +!analyze_repo: read package.json, count top-level entries
    {
      label: 'plan-analyze-repo',
      trigger: EventKind.GoalAdd,
      triggerFunctor: 'analyze_repo',
      context: (_beliefs) => true, // always applicable
      body: [
        { type: BodyStepType.Action, functor: 'read_package_json', args: [] },
        { type: BodyStepType.Action, functor: 'count_files', args: [] },
        { type: BodyStepType.AddBelief, functor: 'repo_analyzed', args: ['true'] },
      ],
    },

    // Plan for +!evaluate_engine: check for tests, CI, types
    {
      label: 'plan-evaluate-engine',
      trigger: EventKind.GoalAdd,
      triggerFunctor: 'evaluate_engine',
      context: (beliefs) => beliefs.has(beliefKey({ functor: 'repo_analyzed', args: ['true'] })),
      body: [
        { type: BodyStepType.Action, functor: 'probe_patterns', args: [] },
        { type: BodyStepType.Action, functor: 'compute_score', args: [] },
        { type: BodyStepType.AddBelief, functor: 'engine_evaluated', args: ['true'] },
      ],
    },

    // Plan for +!report_findings: compile verdict
    {
      label: 'plan-report-findings',
      trigger: EventKind.GoalAdd,
      triggerFunctor: 'report_findings',
      context: (beliefs) => beliefs.has(beliefKey({ functor: 'engine_evaluated', args: ['true'] })),
      body: [
        { type: BodyStepType.Action, functor: 'compile_verdict', args: [] },
        { type: BodyStepType.AddBelief, functor: 'verdict_ready', args: ['true'] },
      ],
    },
  ];
}

// ---------------------------------------------------------------------------
// Integration Tests
// ---------------------------------------------------------------------------

describe('SP-001 + SP-002 Integration: Agent Analyzes Real Repos', () => {
  /** Shared state across the BDI + NEVER pipeline. */
  let beliefs;
  let plans;
  let cycle;
  let store;
  let clock;
  /** Mutable result bag populated by the action handler. */
  let findings;

  /**
   * Create an action handler bound to a specific repo path.
   * Each action reads real files from disk.
   */
  function createActionHandler(repoPath) {
    return (functor, _args) => {
      switch (functor) {
        case 'read_package_json': {
          const pkg = readRealPackageJson(repoPath);
          if (!pkg) return { success: false };
          findings.packageName = pkg.name;
          findings.packageVersion = pkg.version;
          findings.packageDescription = pkg.description;
          findings.dependencyCount = Object.keys(pkg.dependencies ?? {}).length;
          findings.devDependencyCount = Object.keys(pkg.devDependencies ?? {}).length;
          return { success: true };
        }

        case 'count_files': {
          const entries = fs.readdirSync(repoPath);
          findings.topLevelEntryCount = entries.length;
          return { success: true };
        }

        case 'probe_patterns': {
          findings.patterns = probeRepoPatterns(repoPath);
          return { success: true };
        }

        case 'compute_score': {
          const p = findings.patterns ?? {};
          let score = 0;
          if (p.hasTests) score += 30;
          if (p.hasCI) score += 25;
          if (p.hasTypes) score += 20;
          if (p.hasReadme) score += 15;
          if (p.hasLicense) score += 10;
          findings.qualityScore = score;
          return { success: true };
        }

        case 'compile_verdict': {
          const score = findings.qualityScore ?? 0;
          if (score >= 80) findings.verdict = 'ADOPT';
          else if (score >= 60) findings.verdict = 'TRIAL';
          else if (score >= 40) findings.verdict = 'ASSESS';
          else findings.verdict = 'HOLD';
          return { success: true };
        }

        default:
          return { success: false };
      }
    };
  }

  beforeEach(() => {
    clock = createTestClock(10_000);
    store = new TemporalStore(clock);
    beliefs = new BeliefBase();
    plans = new PlanLibrary();
    plans.addAll(buildPlans());
    findings = {};
  });

  // -----------------------------------------------------------------------
  // Test 1: Full BDI cycle against json-rules-engine
  // -----------------------------------------------------------------------

  it('full BDI cycle reads real data from json-rules-engine repo', () => {
    cycle = new ReasoningCycle(beliefs, plans, createActionHandler(REPOS.jsonRulesEngine));

    // Post the three goals in sequence
    cycle.postGoal('analyze_repo');
    const results1 = cycle.runToCompletion();

    // analyze_repo should be completed and real file data read
    const allCompleted1 = results1.flatMap((r) => r.goalsCompleted);
    expect(allCompleted1).toContain('analyze_repo');
    expect(findings.packageName).toBe('json-rules-engine');
    expect(findings.packageVersion).toBeDefined();
    expect(findings.topLevelEntryCount).toBeGreaterThan(0);

    // Now evaluate the engine (requires repo_analyzed belief)
    cycle.postGoal('evaluate_engine');
    const results2 = cycle.runToCompletion();
    const allCompleted2 = results2.flatMap((r) => r.goalsCompleted);
    expect(allCompleted2).toContain('evaluate_engine');
    expect(findings.patterns.hasTests).toBe(true);
    expect(findings.patterns.hasCI).toBe(true);
    expect(findings.patterns.hasTypes).toBe(true);
    expect(findings.qualityScore).toBeGreaterThanOrEqual(70);

    // Report findings
    cycle.postGoal('report_findings');
    const results3 = cycle.runToCompletion();
    const allCompleted3 = results3.flatMap((r) => r.goalsCompleted);
    expect(allCompleted3).toContain('report_findings');
    expect(findings.verdict).toBe('ADOPT');
    expect(beliefs.has({ functor: 'verdict_ready', args: ['true'] })).toBe(true);
  });

  // -----------------------------------------------------------------------
  // Test 2: NEVER-001 blocks re-analysis within window
  // -----------------------------------------------------------------------

  it('NEVER-001 blocks re-analysis of same repo within 60s window', () => {
    const agentId = 'agent-alpha';
    const repoId = 'json-rules-engine';

    // Record that we already analyzed this repo
    store.assert({ entity: agentId, attribute: 'repo-analyzed', value: repoId });

    // Try to analyze again immediately — should be DENIED
    const ctx = { agentId, planId: repoId };
    const result = evaluateRule(neverReanalyzeRepo, store, ctx);
    expect(result.verdict).toBe('DENY');
    expect(result.ruleId).toBe('NEVER-001');

    // Advance time past the 60s window
    clock.advance(61_000);

    // Now it should be ALLOWED
    const result2 = evaluateRule(neverReanalyzeRepo, store, ctx);
    expect(result2.verdict).toBe('ALLOW');
  });

  // -----------------------------------------------------------------------
  // Test 3: NEVER-002 caps concurrent evaluations
  // -----------------------------------------------------------------------

  it('NEVER-002 caps concurrent evaluations at 5', () => {
    // Simulate 5 agents starting evaluations
    for (let i = 0; i < 5; i++) {
      store.assert({ entity: `agent-${i}`, attribute: 'eval-started', value: `repo-${i}` });
    }

    const ctx = { agentId: 'agent-new', planId: 'repo-new' };
    const result = evaluateRule(neverExceedConcurrentEvals, store, ctx);
    expect(result.verdict).toBe('DENY');

    // Complete one evaluation
    store.assert({ entity: 'agent-0', attribute: 'eval-completed', value: 'repo-0' });

    const result2 = evaluateRule(neverExceedConcurrentEvals, store, ctx);
    expect(result2.verdict).toBe('ALLOW');
  });

  // -----------------------------------------------------------------------
  // Test 4: Escape hatch allows re-analysis when beliefs change
  // -----------------------------------------------------------------------

  it('escape hatch allows re-analysis when beliefs change', () => {
    const agentId = 'agent-beta';
    const planId = 'analyze-json-rules-engine';
    const originalBeliefs = { repoPath: REPOS.jsonRulesEngine, fileCount: 10 };

    // Record a failure with original beliefs
    recordFailureWithBeliefs(store, agentId, planId, originalBeliefs);

    // Same beliefs — escape hatch should NOT open
    const escape1 = shouldEscapeHatch(store, agentId, planId, originalBeliefs, NEVER_WINDOW_MS);
    expect(escape1).toBe(false);

    // Beliefs change (new data discovered) — escape hatch SHOULD open
    const changedBeliefs = { repoPath: REPOS.jsonRulesEngine, fileCount: 15, newDiscovery: true };
    const escape2 = shouldEscapeHatch(store, agentId, planId, changedBeliefs, NEVER_WINDOW_MS);
    expect(escape2).toBe(true);
  });

  // -----------------------------------------------------------------------
  // Test 5: Integrated pipeline — BDI + NEVER + escape hatch
  // -----------------------------------------------------------------------

  it('integrated pipeline: BDI goal blocked by NEVER, then unblocked by escape hatch', () => {
    const agentId = 'agent-gamma';
    const repoPath = REPOS.jsonRulesEngine;

    // --- Phase 1: First analysis succeeds ---
    cycle = new ReasoningCycle(beliefs, plans, createActionHandler(repoPath));
    cycle.postGoal('analyze_repo');
    cycle.runToCompletion();

    expect(findings.packageName).toBe('json-rules-engine');

    // Record in temporal store that analysis happened
    store.assert({ entity: agentId, attribute: 'repo-analyzed', value: 'json-rules-engine' });

    // --- Phase 2: Re-analysis blocked by NEVER-001 ---
    const ctx = { agentId, planId: 'json-rules-engine' };
    const blocked = evaluateRule(neverReanalyzeRepo, store, ctx);
    expect(blocked.verdict).toBe('DENY');

    // --- Phase 3: Record failure with belief snapshot ---
    const beliefsAtFailure = {
      packageName: findings.packageName,
      topLevelEntryCount: findings.topLevelEntryCount,
    };
    recordFailureWithBeliefs(store, agentId, 'json-rules-engine', beliefsAtFailure);

    // With same beliefs, escape hatch is closed
    const noEscape = shouldEscapeHatch(
      store, agentId, 'json-rules-engine', beliefsAtFailure, NEVER_WINDOW_MS,
    );
    expect(noEscape).toBe(false);

    // --- Phase 4: New data discovered — beliefs change ---
    const updatedBeliefs = {
      packageName: findings.packageName,
      topLevelEntryCount: findings.topLevelEntryCount,
      hasNewRelease: true, // new information
    };
    const escapeOpens = shouldEscapeHatch(
      store, agentId, 'json-rules-engine', updatedBeliefs, NEVER_WINDOW_MS,
    );
    expect(escapeOpens).toBe(true);

    // --- Phase 5: Re-analysis proceeds with escape hatch ---
    // Reset BDI state for fresh cycle
    beliefs.clear();
    findings = {};
    cycle = new ReasoningCycle(beliefs, plans, createActionHandler(repoPath));
    cycle.postGoal('analyze_repo');
    cycle.runToCompletion();

    // Verify we got fresh real data
    expect(findings.packageName).toBe('json-rules-engine');
    expect(findings.topLevelEntryCount).toBeGreaterThan(0);
  });

  // -----------------------------------------------------------------------
  // Test 6: Full pipeline against xstate repo
  // -----------------------------------------------------------------------

  it('full pipeline against xstate repo — cross-repo behavior', () => {
    cycle = new ReasoningCycle(beliefs, plans, createActionHandler(REPOS.xstate));

    // Analyze xstate
    cycle.postGoal('analyze_repo');
    cycle.runToCompletion();

    expect(findings.packageName).toBe('xstate-monorepo');
    expect(findings.topLevelEntryCount).toBeGreaterThan(0);

    // Evaluate
    cycle.postGoal('evaluate_engine');
    cycle.runToCompletion();

    expect(findings.patterns.hasTests).toBe(false); // xstate has no root test/ dir
    expect(findings.patterns.hasCI).toBe(true);
    expect(findings.patterns.hasTypes).toBe(true); // has tsconfig.json
    expect(findings.qualityScore).toBeGreaterThanOrEqual(50);

    // Report
    cycle.postGoal('report_findings');
    cycle.runToCompletion();

    expect(['ADOPT', 'TRIAL']).toContain(findings.verdict);
  });

  // -----------------------------------------------------------------------
  // Test 7: NEVER rules evaluated together (evaluateAllRules)
  // -----------------------------------------------------------------------

  it('evaluateAllRules short-circuits on first DENY', () => {
    const agentId = 'agent-delta';

    // Record recent analysis (will trigger NEVER-001 DENY)
    store.assert({ entity: agentId, attribute: 'repo-analyzed', value: 'xstate' });

    const ctx = { agentId, planId: 'xstate' };
    const results = evaluateAllRules([neverReanalyzeRepo, neverExceedConcurrentEvals], store, ctx);

    // First rule should DENY and short-circuit
    expect(results).toHaveLength(1);
    expect(results[0].verdict).toBe('DENY');
    expect(results[0].ruleId).toBe('NEVER-001');
  });

  // -----------------------------------------------------------------------
  // Test 8: Cross-repo NEVER independence
  // -----------------------------------------------------------------------

  it('NEVER-001 is repo-scoped — analyzing repo A does not block repo B', () => {
    const agentId = 'agent-epsilon';

    // Record analysis of json-rules-engine
    store.assert({ entity: agentId, attribute: 'repo-analyzed', value: 'json-rules-engine' });

    // json-rules-engine should be blocked
    const ctx1 = { agentId, planId: 'json-rules-engine' };
    expect(evaluateRule(neverReanalyzeRepo, store, ctx1).verdict).toBe('DENY');

    // xstate should be allowed (different planId = different repo)
    const ctx2 = { agentId, planId: 'xstate' };
    expect(evaluateRule(neverReanalyzeRepo, store, ctx2).verdict).toBe('ALLOW');
  });

  // -----------------------------------------------------------------------
  // Test 9: BDI plan context guards prevent out-of-order goals
  // -----------------------------------------------------------------------

  it('BDI context guards prevent evaluate_engine before analyze_repo', () => {
    cycle = new ReasoningCycle(beliefs, plans, createActionHandler(REPOS.jsonRulesEngine));

    // Try to evaluate without analyzing first
    cycle.postGoal('evaluate_engine');
    const results = cycle.runToCompletion();

    // evaluate_engine should fail (no repo_analyzed belief)
    const failed = results.flatMap((r) => r.goalsFailed);
    expect(failed).toContain('evaluate_engine');
    expect(findings.patterns).toBeUndefined();
  });

  // -----------------------------------------------------------------------
  // Test 10: Real file content verification
  // -----------------------------------------------------------------------

  it('reads accurate real data — json-rules-engine description matches', () => {
    cycle = new ReasoningCycle(beliefs, plans, createActionHandler(REPOS.jsonRulesEngine));

    cycle.postGoal('analyze_repo');
    cycle.runToCompletion();

    expect(findings.packageDescription).toMatch(/rules?\s*engine/i);
    expect(findings.dependencyCount).toBeGreaterThanOrEqual(0);
    expect(findings.devDependencyCount).toBeGreaterThan(0);
  });
});
