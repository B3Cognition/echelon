/**
 * XState Integration — BDI agent as an XState actor.
 *
 * Demonstrates the BDI engine running inside XState v5 using fromCallback
 * actor logic. XState sends events, BDI processes them, results flow back.
 *
 * This is the critical integration point: if this is clean and small,
 * the approach is viable for the cognitive-squad architecture.
 */

import { fromCallback, setup, assign } from "xstate";
import { BeliefBase } from "./belief-base.js";
import { PlanLibrary } from "./plan-library.js";
import { ReasoningCycle } from "./reasoning-cycle.js";
import { EventKind } from "./types.js";

// ---------------------------------------------------------------------------
// BDI Actor Logic — wraps the reasoning cycle as an XState callback actor
// ---------------------------------------------------------------------------

/**
 * @typedef {Object} BdiActorInput
 * @property {import('./types.js').Plan[]} plans
 * @property {import('./types.js').ActionHandler} [actionHandler]
 * @property {Array<{functor: string, args: (string|number|boolean)[]}>} [initialBeliefs]
 */

/**
 * @typedef {Object} BdiGoalEvent
 * @property {"BDI_GOAL"} type
 * @property {string} functor
 * @property {(string|number|boolean)[]} args
 */

/**
 * @typedef {Object} BdiPerceiveEvent
 * @property {"BDI_PERCEIVE"} type
 * @property {Array<{functor: string, args: (string|number|boolean)[]}>} beliefs
 */

/**
 * @typedef {Object} BdiCycleResult
 * @property {"BDI_RESULT"} type
 * @property {import('./reasoning-cycle.js').CycleResult} result
 */

/**
 * @typedef {Object} BdiCompleteEvent
 * @property {"BDI_COMPLETE"} type
 * @property {import('./reasoning-cycle.js').CycleResult[]} results
 */

/**
 * Create a BDI callback actor for XState v5.
 *
 * Usage:
 *   const bdiActor = createBdiActor({ plans: [...], actionHandler: ... });
 *   // Use in a machine via invoke/spawn
 *
 * @param {BdiActorInput} input
 */
export function createBdiActor(input) {
  return fromCallback(
    ({ sendBack, receive, input }) => {
      const beliefs = new BeliefBase();
      const planLib = new PlanLibrary();
      const engine = new ReasoningCycle(
        beliefs,
        planLib,
        input.actionHandler,
      );

      // Load plans
      planLib.addAll(input.plans);

      // Load initial beliefs
      if (input.initialBeliefs) {
        for (const b of input.initialBeliefs) {
          beliefs.add(b);
        }
        // Drain initial belief-add events (we don't want to process them)
        beliefs.drainEvents();
      }

      receive((event) => {
        if (event.type === "BDI_GOAL") {
          engine.postGoal(event.functor, ...event.args);
          const results = engine.runToCompletion();
          sendBack({
            type: "BDI_COMPLETE",
            results,
          });
        } else if (event.type === "BDI_PERCEIVE") {
          for (const b of event.beliefs) {
            beliefs.add(b);
          }
          const results = engine.runToCompletion();
          sendBack({
            type: "BDI_COMPLETE",
            results,
          });
        }
      });
    },
  );
}

// ---------------------------------------------------------------------------
// Demo Machine — a simple XState machine that uses the BDI actor
// ---------------------------------------------------------------------------

/**
 * Create a demo XState machine that delegates goals to a BDI actor.
 * @param {BdiActorInput} bdiInput
 */
export function createDemoMachine(bdiInput) {
  return setup({
    types: {},
    actors: {
      bdiAgent: createBdiActor(bdiInput),
    },
  }).createMachine({
    id: "bdi-demo",
    initial: "idle",
    context: {
      bdiResults: [],
      actionsLog: [],
    },
    states: {
      idle: {
        invoke: {
          id: "bdi",
          src: "bdiAgent",
          input: bdiInput,
        },
        on: {
          START_GOAL: {
            actions: [
              // Forward goal to BDI actor
              ({ event }) => {
                // This sends to the invoked actor — handled via sendTo in real usage
              },
            ],
          },
          BDI_COMPLETE: {
            actions: assign({
              bdiResults: ({ context, event }) => [
                ...context.bdiResults,
                ...event.results,
              ],
              actionsLog: ({ context, event }) => {
                const newActions = event.results.flatMap(
                  (r) => r.actionsExecuted,
                );
                return [...context.actionsLog, ...newActions];
              },
            }),
          },
        },
      },
    },
  });
}
