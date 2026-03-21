/**
 * SP-002: Failure Mode Handling
 *
 * Per ADR-004 (fail-safe default): when enforcement infrastructure fails,
 * the system MUST deny the transition. This module wraps the rule engine
 * with defensive error handling for each failure mode:
 *
 * 1. Store query throws => DENY
 * 2. Actor/evaluator crashes => DENY
 * 3. Clock skew => mitigated by monotonic clock (performance.now)
 * 4. Evaluation timeout => DENY after 50ms
 */

import { TemporalStore } from './temporal-store.js';
import { evaluateRule } from './rule-engine.js';

/**
 * Fail-safe rule evaluation wrapper.
 * Catches ALL exceptions and returns DENY with diagnostic info.
 *
 * @param {import('./rule-engine.js').NeverRule} rule
 * @param {TemporalStore} store
 * @param {import('./rule-engine.js').RuleContext} context
 * @param {{ timeoutMs?: number }} [_options]
 * @returns {import('./rule-engine.js').EvaluationResult}
 */
export function failSafeEvaluate(rule, store, context, _options = {}) {
  try {
    return evaluateRule(rule, store, context);
  } catch (err) {
    return {
      ruleId: rule.id,
      verdict: 'DENY',
      reason: `FAIL-SAFE: Unhandled error in evaluation: ${err instanceof Error ? err.message : String(err)}`,
      latencyMs: 0,
    };
  }
}

/**
 * Create a store proxy that throws on query, for testing fail-safe behavior.
 * @param {string} errorMessage
 * @returns {TemporalStore}
 */
export function createFailingStore(errorMessage) {
  const store = new TemporalStore();
  const original = store.query.bind(store);
  store.query = (_pattern, _since) => {
    void original; // suppress unused
    throw new Error(errorMessage);
  };
  return store;
}

/**
 * Create a rule whose condition always throws, for testing fail-safe behavior.
 * @param {string} ruleId
 * @param {string} errorMessage
 * @returns {import('./rule-engine.js').NeverRule}
 */
export function createCrashingRule(ruleId, errorMessage) {
  return {
    id: ruleId,
    description: `Crashing test rule: ${errorMessage}`,
    class: 'temporal-logical',
    windowMs: 300_000,
    condition: () => {
      throw new Error(errorMessage);
    },
  };
}

/**
 * Create a rule that takes too long to evaluate (simulated via busy loop).
 * In real production this would be an async timeout, but for the spike
 * we demonstrate the timeout detection in evaluateRule.
 *
 * @param {string} ruleId
 * @param {number} busyMs
 * @returns {import('./rule-engine.js').NeverRule}
 */
export function createSlowRule(ruleId, busyMs) {
  return {
    id: ruleId,
    description: `Slow test rule: busy for ${busyMs}ms`,
    class: 'temporal-logical',
    windowMs: 300_000,
    condition: () => {
      const start = performance.now();
      while (performance.now() - start < busyMs) {
        // busy wait
      }
      return true; // would allow, but timeout check should catch it
    },
  };
}
