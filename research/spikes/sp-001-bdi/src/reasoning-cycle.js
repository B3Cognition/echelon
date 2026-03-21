/**
 * Reasoning Cycle — the core BDI deliberation loop from AgentSpeak(L).
 *
 * One call to `cycle()` executes one full reasoning step:
 * 1. Process external events + belief-change events
 * 2. Select an unprocessed event
 * 3. Find applicable plans
 * 4. Select a plan (first-match for MVP)
 * 5. Create/push intention
 * 6. Execute one step of the selected intention
 * 7. Handle success/failure
 *
 * Reference: Bordini, Hubner & Wooldridge (2007) ch.3-4
 */

import { BeliefBase } from "./belief-base.js";
import { PlanLibrary } from "./plan-library.js";
import { attemptRecovery } from "./failure.js";
import { EventKind, BodyStepType } from "./types.js";

/**
 * @typedef {Object} CycleResult
 * @property {boolean} acted - Whether any work was done this cycle
 * @property {number} eventsProcessed - Events processed
 * @property {string[]} actionsExecuted - Actions executed
 * @property {string[]} goalsCompleted - Goals completed
 * @property {string[]} goalsFailed - Goals failed
 */

export class ReasoningCycle {
  /** @type {BeliefBase} */
  beliefs;
  /** @type {PlanLibrary} */
  plans;
  /** @type {import('./types.js').AgentEvent[]} */
  #eventQueue = [];
  /** @type {Map<string, import('./types.js').Intention>} */
  #intentions = new Map();
  /** @type {import('./types.js').ActionHandler} */
  #actionHandler;
  #intentionCounter = 0;

  #nextIntentionId() {
    return `i-${++this.#intentionCounter}`;
  }

  /**
   * @param {BeliefBase} beliefs
   * @param {PlanLibrary} plans
   * @param {import('./types.js').ActionHandler} [actionHandler]
   */
  constructor(beliefs, plans, actionHandler) {
    this.beliefs = beliefs;
    this.plans = plans;
    this.#actionHandler = actionHandler ?? (() => ({ success: true }));
  }

  /** Set the action handler (environment callback) */
  setActionHandler(handler) {
    this.#actionHandler = handler;
  }

  /** Post an external event into the event queue */
  postEvent(event) {
    this.#eventQueue.push(event);
  }

  /** Post an achievement goal adoption event */
  postGoal(functor, ...args) {
    this.postEvent({ kind: EventKind.GoalAdd, functor, args });
  }

  /** Number of pending events */
  get pendingEventCount() {
    return this.#eventQueue.length;
  }

  /** Number of active (non-finished) intentions */
  get activeIntentionCount() {
    let count = 0;
    for (const i of this.#intentions.values()) {
      if (!i.finished) count++;
    }
    return count;
  }

  /**
   * Execute one full reasoning cycle.
   * @returns {CycleResult}
   */
  cycle() {
    const result = {
      acted: false,
      eventsProcessed: 0,
      actionsExecuted: [],
      goalsCompleted: [],
      goalsFailed: [],
    };

    // Step 1: Collect belief-change events
    const beliefEvents = this.beliefs.drainEvents();
    for (const e of beliefEvents) {
      this.#eventQueue.push(e);
    }

    // Step 2: Select event (FIFO for MVP)
    const event = this.#eventQueue.shift();
    if (event) {
      result.eventsProcessed = 1;
      result.acted = true;
      this.#processEvent(event, result);
    }

    // Step 3: Execute one step from each active intention
    for (const intention of this.#intentions.values()) {
      if (intention.finished) continue;
      this.#executeIntentionStep(intention, result);
    }

    // Cleanup finished intentions
    for (const [id, intention] of this.#intentions) {
      if (intention.finished) {
        this.#intentions.delete(id);
      }
    }

    return result;
  }

  /**
   * Run cycles until no more events and no active intentions.
   * Safety limit prevents infinite loops.
   * @param {number} [maxCycles=1000]
   * @returns {CycleResult[]}
   */
  runToCompletion(maxCycles = 1000) {
    const results = [];
    for (let i = 0; i < maxCycles; i++) {
      // Check termination: no pending events, no belief events, no active intentions
      const hasPendingBeliefEvents = this.beliefs.pendingEventCount > 0;
      if (this.#eventQueue.length === 0 && !hasPendingBeliefEvents && this.activeIntentionCount === 0) {
        break;
      }

      // cycle() handles draining belief events — single drain point
      const r = this.cycle();
      results.push(r);
      if (!r.acted && this.activeIntentionCount === 0) break;
    }
    return results;
  }

  // -------------------------------------------------------------------------
  // Private: event processing
  // -------------------------------------------------------------------------

  #processEvent(event, result) {
    // Find applicable plans
    const applicable = this.plans.findApplicable(event, this.beliefs.keySet);

    if (applicable.length === 0) {
      // No plan for this event — if it was a goal, report failure
      if (event.kind === EventKind.GoalAdd) {
        result.goalsFailed.push(event.functor);
      }
      return;
    }

    // Select plan: first applicable (MVP deliberation)
    const selected = applicable[0];
    const alternatives = applicable.slice(1);

    // Create intention
    const intention = {
      id: this.#nextIntentionId(),
      event,
      planBody: [...selected.body],
      stepIndex: 0,
      alternatives,
      parentId: event.sourceIntentionId,
      finished: false,
      failed: false,
    };

    this.#intentions.set(intention.id, intention);
  }

  // -------------------------------------------------------------------------
  // Private: intention execution
  // -------------------------------------------------------------------------

  #executeIntentionStep(intention, result) {
    if (intention.stepIndex >= intention.planBody.length) {
      // Plan body completed successfully
      intention.finished = true;
      if (intention.event.kind === EventKind.GoalAdd) {
        result.goalsCompleted.push(intention.event.functor);
      }
      result.acted = true;
      return;
    }

    const step = intention.planBody[intention.stepIndex];
    const success = this.#executeStep(step, intention, result);

    if (success) {
      intention.stepIndex++;
      result.acted = true;
    } else {
      // Step failed — attempt recovery
      this.#handleStepFailure(intention, result);
    }
  }

  #executeStep(step, intention, result) {
    switch (step.type) {
      case BodyStepType.Action: {
        const actionResult = this.#actionHandler(
          step.functor,
          step.args,
        );
        if (actionResult.success) {
          result.actionsExecuted.push(step.functor);
        }
        return actionResult.success;
      }

      case BodyStepType.SubGoal: {
        // Post a goal-adoption event with this intention as source
        this.#eventQueue.push({
          kind: EventKind.GoalAdd,
          functor: step.functor,
          args: step.args,
          sourceIntentionId: intention.id,
        });
        // Advance past this step — the sub-goal will create its own intention
        result.acted = true;
        return true;
      }

      case BodyStepType.TestGoal: {
        // Query belief base for the belief
        const b = { functor: step.functor, args: step.args };
        return this.beliefs.has(b);
      }

      case BodyStepType.AddBelief: {
        this.beliefs.add({ functor: step.functor, args: step.args });
        return true;
      }

      case BodyStepType.DelBelief: {
        this.beliefs.remove({ functor: step.functor, args: step.args });
        return true;
      }

      default:
        return false;
    }
  }

  #handleStepFailure(intention, result) {
    const recovery = attemptRecovery(intention);

    if (recovery.recovered && recovery.newBody) {
      // Swap to alternative plan
      intention.planBody = recovery.newBody;
      intention.stepIndex = 0;
      intention.alternatives = recovery.remainingAlternatives ?? [];
      result.acted = true;
    } else {
      // Goal failure
      intention.finished = true;
      intention.failed = true;
      result.goalsFailed.push(intention.event.functor);
      result.acted = true;

      // Propagate failure to parent intention (if any)
      if (recovery.failureEvent) {
        this.#eventQueue.push(recovery.failureEvent);
      }
    }
  }
}
