/**
 * Core BDI types derived from AgentSpeak(L) formal specification.
 * Reference: Rao (1996), Bordini et al. (2007)
 */

// ---------------------------------------------------------------------------
// Beliefs — ground atoms: functor(arg0, arg1, ...)
// ---------------------------------------------------------------------------

/**
 * @typedef {Object} Belief
 * @property {string} functor - Predicate name, e.g. "at", "holding", "open"
 * @property {ReadonlyArray<string|number|boolean>} args - Ground terms. No variables in MVP.
 */

/** Canonical string key for a belief, used for O(1) lookup. */
export function beliefKey(b) {
  return `${b.functor}(${b.args.join(",")})`;
}

// ---------------------------------------------------------------------------
// Goals
// ---------------------------------------------------------------------------

/**
 * @enum {string}
 */
export const GoalType = /** @type {const} */ ({
  /** Achievement goal: !g — agent commits to making g true */
  Achievement: "!",
  /** Test goal: ?g — agent queries belief base for g */
  Test: "?",
});

/**
 * @typedef {Object} Goal
 * @property {string} type - GoalType value
 * @property {string} functor
 * @property {ReadonlyArray<string|number|boolean>} args
 */

// ---------------------------------------------------------------------------
// Events — trigger the reasoning cycle
// ---------------------------------------------------------------------------

/**
 * @enum {string}
 */
export const EventKind = /** @type {const} */ ({
  /** +belief: a belief was added */
  BeliefAdd: "+belief",
  /** -belief: a belief was removed */
  BeliefDel: "-belief",
  /** +!goal: an achievement goal was adopted */
  GoalAdd: "+!goal",
  /** -!goal: an achievement goal was dropped/failed */
  GoalDel: "-!goal",
  /** External event from the environment (e.g. XState) */
  External: "external",
});

/**
 * @typedef {Object} AgentEvent
 * @property {string} kind - EventKind value
 * @property {string} functor - The belief or goal functor this event relates to
 * @property {ReadonlyArray<string|number|boolean>} args
 * @property {string} [sourceIntentionId] - Optional: the intention that generated this event
 */

// ---------------------------------------------------------------------------
// Plans — reactive rules: trigger : context <- body
// ---------------------------------------------------------------------------

/**
 * @enum {string}
 */
export const BodyStepType = /** @type {const} */ ({
  /** Perform an external action */
  Action: "action",
  /** Adopt a sub-goal: !g */
  SubGoal: "subgoal",
  /** Test a belief: ?g */
  TestGoal: "test",
  /** Add a belief: +b */
  AddBelief: "+belief",
  /** Remove a belief: -b */
  DelBelief: "-belief",
});

/**
 * @typedef {Object} BodyStep
 * @property {string} type - BodyStepType value
 * @property {string} functor
 * @property {ReadonlyArray<string|number|boolean>} args
 */

/**
 * @typedef {Object} Plan
 * @property {string} [label] - Human-readable label (optional)
 * @property {string} trigger - Triggering event kind (EventKind value)
 * @property {string} triggerFunctor - Functor that must match the event
 * @property {(beliefs: ReadonlySet<string>) => boolean} context - Context condition
 * @property {BodyStep[]} body - Ordered sequence of body steps
 */

// ---------------------------------------------------------------------------
// Intentions — executing plan instances
// ---------------------------------------------------------------------------

/**
 * @typedef {Object} Intention
 * @property {string} id
 * @property {AgentEvent} event - The event that spawned this intention
 * @property {BodyStep[]} planBody - Stack of plan body steps remaining
 * @property {number} stepIndex - Current step index
 * @property {Plan[]} alternatives - Alternative applicable plans not yet tried
 * @property {string} [parentId] - Parent intention id (for sub-goal chaining)
 * @property {boolean} finished - Whether this intention has completed
 * @property {boolean} failed - Whether this intention failed
 */

// ---------------------------------------------------------------------------
// Action results — returned by the environment/action handler
// ---------------------------------------------------------------------------

/**
 * @typedef {Object} ActionResult
 * @property {boolean} success
 * @property {*} [data]
 */

/**
 * Callback the engine invokes to execute external actions.
 * @callback ActionHandler
 * @param {string} functor
 * @param {ReadonlyArray<string|number|boolean>} args
 * @returns {ActionResult}
 */
