/**
 * Failure Recovery — handles plan and goal failure per AgentSpeak(L) semantics.
 *
 * When a plan step fails:
 * 1. Try next applicable plan for the same triggering event (plan failure recovery)
 * 2. If no alternatives remain, the goal fails
 * 3. Goal failure propagates to parent intention (if sub-goal)
 */

import { EventKind } from "./types.js";

/**
 * @typedef {Object} FailureResult
 * @property {boolean} recovered - Whether recovery succeeded
 * @property {import('./types.js').BodyStep[]} [newBody] - If recovered: the new plan body
 * @property {import('./types.js').Plan[]} [remainingAlternatives] - If recovered: remaining alternatives
 * @property {import('./types.js').AgentEvent} [failureEvent] - If not recovered: the failure event to propagate
 */

/**
 * Attempt to recover from a plan failure by trying the next alternative.
 * @param {import('./types.js').Intention} intention
 * @returns {FailureResult}
 */
export function attemptRecovery(intention) {
  if (intention.alternatives.length > 0) {
    const nextPlan = intention.alternatives[0];
    const remaining = intention.alternatives.slice(1);
    return {
      recovered: true,
      newBody: [...nextPlan.body],
      remainingAlternatives: remaining,
    };
  }

  // No alternatives: goal failure
  return {
    recovered: false,
    failureEvent: {
      kind: EventKind.GoalDel,
      functor: intention.event.functor,
      args: intention.event.args,
      sourceIntentionId: intention.parentId,
    },
  };
}
