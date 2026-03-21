/**
 * SP-002: XState v5 Enforcement Actor
 *
 * A state machine that receives plan-attempt-requested events, evaluates
 * NEVER rules against the temporal store, and returns ALLOW or DENY.
 *
 * States:
 *   idle -> evaluating (on PLAN_ATTEMPT_REQUESTED)
 *   evaluating -> idle (after evaluation completes, emitting verdict)
 *
 * On ALLOW: records the attempt fact, starts cleanup timer (conceptual).
 * On PLAN_FAILED: records failure fact into temporal store.
 *
 * Uses XState v5 setup() + createMachine() + createActor() patterns.
 */

import { setup, assign, createActor } from 'xstate';
import { TemporalStore } from './temporal-store.js';
import {
  evaluateRule,
} from './rule-engine.js';
import {
  shouldEscapeHatch,
  recordFailureWithBeliefs,
} from './escape-hatch.js';

// --- Machine ---

export const enforcementMachine = setup({
  types: {
    context: {},
    events: {},
  },
  actions: {
    evaluateAndRecord: assign(({ context }) => {
      const { store, rules, pendingRequest } = context;
      if (!pendingRequest) {
        return {
          lastVerdict: {
            ruleId: 'SYSTEM',
            verdict: 'DENY',
            reason: 'No pending request',
            latencyMs: 0,
          },
        };
      }

      const ruleContext = {
        agentId: pendingRequest.agentId,
        planId: pendingRequest.planId,
        beliefs: pendingRequest.beliefs,
      };

      // Check escape hatch first if beliefs are provided
      if (pendingRequest.beliefs) {
        for (const rule of rules) {
          if (rule.windowMs) {
            const escape = shouldEscapeHatch(
              store,
              pendingRequest.agentId,
              pendingRequest.planId,
              pendingRequest.beliefs,
              rule.windowMs,
            );
            if (escape === true) {
              // Beliefs changed — allow despite time window
              store.assert({
                entity: pendingRequest.agentId,
                attribute: 'plan-attempted',
                value: pendingRequest.planId,
              });
              return {
                lastVerdict: {
                  ruleId: rule.id,
                  verdict: 'ALLOW',
                  reason: 'Belief-change escape hatch: beliefs changed since last failure',
                  latencyMs: 0,
                },
                pendingRequest: null,
              };
            }
          }
        }
      }

      // Evaluate rules
      let finalVerdict = null;
      for (const rule of rules) {
        const result = evaluateRule(rule, store, ruleContext);
        finalVerdict = result;
        if (result.verdict === 'DENY') break;
      }

      if (!finalVerdict) {
        finalVerdict = {
          ruleId: 'SYSTEM',
          verdict: 'ALLOW',
          reason: 'No rules to evaluate',
          latencyMs: 0,
        };
      }

      // On ALLOW, record the attempt
      if (finalVerdict.verdict === 'ALLOW') {
        store.assert({
          entity: pendingRequest.agentId,
          attribute: 'plan-attempted',
          value: pendingRequest.planId,
        });
      }

      return { lastVerdict: finalVerdict, pendingRequest: null };
    }),

    recordFailure: assign(({ context, event }) => {
      if (event.type !== 'PLAN_FAILED') return {};
      const { store } = context;
      const { agentId, planId, beliefs } = event.event;

      if (beliefs) {
        recordFailureWithBeliefs(store, agentId, planId, beliefs);
      } else {
        store.assert({ entity: agentId, attribute: 'plan-failed', value: planId });
      }
      return {};
    }),

    setPendingRequest: assign(({ event }) => {
      if (event.type !== 'PLAN_ATTEMPT_REQUESTED') return {};
      return { pendingRequest: event.request };
    }),
  },
}).createMachine({
  id: 'enforcement',
  context: {
    store: new TemporalStore(),
    rules: [],
    lastVerdict: null,
    pendingRequest: null,
  },
  initial: 'idle',
  states: {
    idle: {
      on: {
        PLAN_ATTEMPT_REQUESTED: {
          target: 'evaluating',
          actions: 'setPendingRequest',
        },
        PLAN_FAILED: {
          target: 'idle',
          actions: 'recordFailure',
        },
      },
    },
    evaluating: {
      entry: 'evaluateAndRecord',
      always: { target: 'idle' },
    },
  },
});

// --- Actor Factory ---

// createEnforcementActor removed — was broken (silently ignored store/rules params).
// Use createEnforcer() instead, which correctly injects store and rules.

/**
 * Create and start an enforcement actor with the given store and rules.
 * Returns a helper object for sending events and reading verdicts.
 *
 * @param {TemporalStore} store
 * @param {import('./rule-engine.js').NeverRule[]} rules
 */
export function createEnforcer(store, rules) {
  const actor = createActor(enforcementMachine, {
    snapshot: enforcementMachine.resolveState({
      value: 'idle',
      context: {
        store,
        rules,
        lastVerdict: null,
        pendingRequest: null,
      },
    }),
  });

  actor.start();

  return {
    actor,

    /**
     * Request to attempt a plan. Returns the verdict synchronously (evaluation is sync).
     * @param {{ agentId: string, planId: string, beliefs?: Record<string, unknown> }} request
     * @returns {import('./rule-engine.js').EvaluationResult}
     */
    requestPlanAttempt(request) {
      actor.send({ type: 'PLAN_ATTEMPT_REQUESTED', request });
      return actor.getSnapshot().context.lastVerdict;
    },

    /**
     * Notify the actor that a plan has failed.
     * @param {{ agentId: string, planId: string, beliefs?: Record<string, unknown> }} event
     */
    notifyPlanFailed(event) {
      actor.send({ type: 'PLAN_FAILED', event });
    },

    /**
     * Get the current verdict.
     * @returns {import('./rule-engine.js').EvaluationResult | null}
     */
    getLastVerdict() {
      return actor.getSnapshot().context.lastVerdict;
    },

    /** Stop the actor. */
    stop() {
      actor.stop();
    },
  };
}
