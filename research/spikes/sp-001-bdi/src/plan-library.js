/**
 * Plan Library — stores plans and finds applicable plans for events.
 *
 * AgentSpeak(L) plan selection:
 * 1. Filter plans whose trigger matches the event (kind + functor)
 * 2. Filter by context condition (evaluated against current beliefs)
 * 3. Return ordered list of applicable plans
 */

export class PlanLibrary {
  /** @type {import('./types.js').Plan[]} */
  #plans = [];

  /** Number of plans in the library */
  get size() {
    return this.#plans.length;
  }

  /** Add a plan to the library */
  add(plan) {
    this.#plans.push(plan);
  }

  /** Add multiple plans */
  addAll(plans) {
    for (const p of plans) this.#plans.push(p);
  }

  /**
   * Find all applicable plans for an event.
   *
   * A plan is applicable if:
   * 1. Its trigger kind matches the event kind
   * 2. Its trigger functor matches the event functor
   * 3. Its context condition returns true given current beliefs
   *
   * Returns plans in library order (first-match priority for MVP).
   *
   * @param {import('./types.js').AgentEvent} event
   * @param {ReadonlySet<string>} beliefKeys
   * @returns {import('./types.js').Plan[]}
   */
  findApplicable(event, beliefKeys) {
    const applicable = [];
    for (const plan of this.#plans) {
      if (plan.trigger !== event.kind) continue;
      if (plan.triggerFunctor !== event.functor) continue;
      if (!plan.context(beliefKeys)) continue;
      applicable.push(plan);
    }
    return applicable;
  }

  /** Get all plans (for inspection/debugging) */
  all() {
    return this.#plans;
  }

  /** Clear all plans */
  clear() {
    this.#plans.length = 0;
  }
}
