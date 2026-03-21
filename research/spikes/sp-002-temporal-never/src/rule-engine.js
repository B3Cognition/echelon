/**
 * SP-002: NEVER Rule Engine
 *
 * Implements the four rule classes from the cognitive-squad taxonomy:
 * - stateless: no temporal component
 * - temporal-behavioral: time-windowed behavioral constraint
 * - temporal-logical: time-windowed logical constraint (our primary target)
 * - cross-agent-aggregate: spans multiple agents
 *
 * Each rule returns true = ALLOWED, false = DENIED.
 * Fail-safe default (ADR-004): any exception during evaluation => DENY.
 */

import { TemporalStore } from './temporal-store.js';

/**
 * @typedef {Object} RuleContext
 * @property {string} agentId
 * @property {string} planId
 * @property {Record<string, unknown>} [beliefs]
 */

/**
 * @typedef {'stateless' | 'temporal-behavioral' | 'temporal-logical' | 'cross-agent-aggregate'} RuleClass
 */

/**
 * @typedef {Object} NeverRule
 * @property {string} id
 * @property {string} description
 * @property {RuleClass} class
 * @property {number} [windowMs]
 * @property {(store: TemporalStore, context: RuleContext) => boolean} condition - Returns true if the action is ALLOWED, false if DENIED.
 */

/**
 * @typedef {'ALLOW' | 'DENY'} RuleVerdict
 */

/**
 * @typedef {Object} EvaluationResult
 * @property {string} ruleId
 * @property {RuleVerdict} verdict
 * @property {string} reason
 * @property {number} latencyMs
 */

/** NEVER-001: Never re-attempt a failed plan within 300 seconds. */
export const neverRepeatFailedPlan = {
  id: 'NEVER-001',
  description: 'Never re-attempt a failed plan within 300 seconds',
  class: 'temporal-logical',
  windowMs: 300_000,
  condition: (store, ctx) => {
    const cutoff = store.now() - 300_000;
    const failures = store.query(
      { entity: ctx.agentId, attribute: 'plan-failed', value: ctx.planId },
      cutoff,
    );
    return failures.length === 0; // no recent failures => allowed
  },
};

/** Timeout threshold for rule evaluation (ADR-004). */
const EVALUATION_TIMEOUT_MS = 50;

/**
 * Evaluate a single rule with fail-safe semantics.
 * - Any thrown exception => DENY
 * - Evaluation exceeding EVALUATION_TIMEOUT_MS => DENY
 *
 * @param {NeverRule} rule
 * @param {TemporalStore} store
 * @param {RuleContext} context
 * @returns {EvaluationResult}
 */
export function evaluateRule(rule, store, context) {
  const start = performance.now();
  try {
    const allowed = rule.condition(store, context);
    const latencyMs = performance.now() - start;

    if (latencyMs > EVALUATION_TIMEOUT_MS) {
      return {
        ruleId: rule.id,
        verdict: 'DENY',
        reason: `Evaluation timeout: ${latencyMs.toFixed(2)}ms > ${EVALUATION_TIMEOUT_MS}ms`,
        latencyMs,
      };
    }

    return {
      ruleId: rule.id,
      verdict: allowed ? 'ALLOW' : 'DENY',
      reason: allowed
        ? 'No matching failures in time window'
        : `Failed plan "${context.planId}" found within ${rule.windowMs}ms window`,
      latencyMs,
    };
  } catch (err) {
    const latencyMs = performance.now() - start;
    return {
      ruleId: rule.id,
      verdict: 'DENY',
      reason: `Fail-safe DENY: ${err instanceof Error ? err.message : String(err)}`,
      latencyMs,
    };
  }
}

/**
 * Evaluate all rules for a given context. ALL must ALLOW for the action to proceed.
 * Short-circuits on first DENY.
 *
 * @param {NeverRule[]} rules
 * @param {TemporalStore} store
 * @param {RuleContext} context
 * @returns {EvaluationResult[]}
 */
export function evaluateAllRules(rules, store, context) {
  const results = [];
  for (const rule of rules) {
    const result = evaluateRule(rule, store, context);
    results.push(result);
    if (result.verdict === 'DENY') break; // short-circuit
  }
  return results;
}
