/**
 * SP-002: Belief-Change Escape Hatch
 *
 * When a plan fails, we hash the relevant belief subset. On re-attempt within
 * the NEVER window, we compare current beliefs to the failure-time snapshot.
 * If beliefs have materially changed, we allow the re-attempt despite the
 * time window — circumstances have changed.
 *
 * Uses a simple JSON-based hash (no crypto needed for prototype).
 */

import { TemporalStore } from './temporal-store.js';

/**
 * Simple deterministic hash of a JS value. DJB2 on the JSON string.
 * @param {Record<string, unknown>} beliefs
 * @returns {string}
 */
export function hashBeliefs(beliefs) {
  const json = JSON.stringify(beliefs, Object.keys(beliefs).sort());
  let hash = 5381;
  for (let i = 0; i < json.length; i++) {
    hash = ((hash << 5) + hash + json.charCodeAt(i)) | 0; // force 32-bit int
  }
  return `belief-${(hash >>> 0).toString(16).padStart(8, '0')}`;
}

/**
 * Record a failure along with the belief snapshot hash.
 * @param {TemporalStore} store
 * @param {string} agentId
 * @param {string} planId
 * @param {Record<string, unknown>} beliefs
 */
export function recordFailureWithBeliefs(store, agentId, planId, beliefs) {
  store.assert({ entity: agentId, attribute: 'plan-failed', value: planId });
  store.assert({
    entity: agentId,
    attribute: 'failure-belief-hash',
    value: `${planId}:${hashBeliefs(beliefs)}`,
  });
}

/**
 * Check whether a re-attempt should be allowed via the belief-change escape hatch.
 *
 * Returns true if beliefs have changed since the last failure (escape hatch opens).
 * Returns false if beliefs are the same (standard NEVER rule applies).
 * Returns null if no failure-time belief hash is found (no escape hatch data).
 *
 * @param {TemporalStore} store
 * @param {string} agentId
 * @param {string} planId
 * @param {Record<string, unknown>} currentBeliefs
 * @param {number} windowMs
 * @returns {boolean | null}
 */
export function shouldEscapeHatch(store, agentId, planId, currentBeliefs, windowMs) {
  const cutoff = store.now() - windowMs;
  const currentHash = hashBeliefs(currentBeliefs);

  const hashFacts = store.query(
    { entity: agentId, attribute: 'failure-belief-hash' },
    cutoff,
  );

  // Find the most recent hash for this plan
  const planHashes = hashFacts.filter(
    (f) => typeof f.value === 'string' && f.value.startsWith(`${planId}:`),
  );

  if (planHashes.length === 0) return null;

  const latestHash = planHashes[planHashes.length - 1];
  const storedHash = latestHash.value.split(':').slice(1).join(':');

  return storedHash !== currentHash; // true = beliefs changed, escape allowed
}
