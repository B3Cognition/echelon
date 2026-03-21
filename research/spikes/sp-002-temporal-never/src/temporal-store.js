/**
 * SP-002: Temporal Fact Store
 *
 * In-memory implementation of Datahike-style temporal fact storage.
 * Supports as-of (snapshot at time T) and since (facts added after time T) queries.
 *
 * Design: append-only log of immutable facts with monotonic transaction IDs.
 * Each fact records entity/attribute/value plus wall-clock timestamp and tx_id.
 */

/**
 * @typedef {Object} TemporalFact
 * @property {string} entity
 * @property {string} attribute
 * @property {unknown} value
 * @property {number} timestamp - monotonic time (performance.now or injected clock)
 * @property {number} tx_id
 */

/**
 * @typedef {Object} FactPattern
 * @property {string} [entity]
 * @property {string} [attribute]
 * @property {unknown} [value]
 */

/**
 * @typedef {Object} Clock
 * @property {() => number} now
 */

/** Default clock using performance.now() for monotonic guarantees. */
export const monotonicClock = {
  now: () => performance.now(),
};

/** Wall-clock (for tests or when absolute time is needed). */
export const wallClock = {
  now: () => Date.now(),
};

export class TemporalStore {
  #facts = [];
  #nextTxId = 1;
  #clock;

  /** @param {Clock} clock */
  constructor(clock = monotonicClock) {
    this.#clock = clock;
  }

  /**
   * Assert a new temporal fact. Appends to the immutable log.
   * @param {{ entity: string, attribute: string, value: unknown }} fact
   * @returns {TemporalFact}
   */
  assert(fact) {
    const temporal = {
      ...fact,
      timestamp: this.#clock.now(),
      tx_id: this.#nextTxId++,
    };
    this.#facts.push(temporal);
    return temporal;
  }

  /**
   * Query facts matching a pattern, optionally restricted to facts asserted since `since`.
   * Pattern fields that are undefined are treated as wildcards.
   * @param {FactPattern} pattern
   * @param {number} [since]
   * @returns {TemporalFact[]}
   */
  query(pattern, since) {
    return this.#facts.filter((f) => {
      if (since !== undefined && f.timestamp < since) return false;
      if (pattern.entity !== undefined && f.entity !== pattern.entity) return false;
      if (pattern.attribute !== undefined && f.attribute !== pattern.attribute) return false;
      if (pattern.value !== undefined && f.value !== pattern.value) return false;
      return true;
    });
  }

  /**
   * Snapshot: return all facts that existed at or before the given timestamp.
   * @param {number} timestamp
   * @returns {TemporalFact[]}
   */
  asOf(timestamp) {
    return this.#facts.filter((f) => f.timestamp <= timestamp);
  }

  /**
   * Return all facts asserted strictly after the given timestamp.
   * @param {number} timestamp
   * @returns {TemporalFact[]}
   */
  since(timestamp) {
    return this.#facts.filter((f) => f.timestamp > timestamp);
  }

  /** Total number of facts in the store (for memory measurement). */
  get size() {
    return this.#facts.length;
  }

  /** Current time from the injected clock. */
  now() {
    return this.#clock.now();
  }

  /**
   * Remove facts older than the given timestamp to prevent unbounded growth.
   * @param {number} olderThan
   * @returns {number}
   */
  compact(olderThan) {
    const before = this.#facts.length;
    this.#facts = this.#facts.filter((f) => f.timestamp >= olderThan);
    return before - this.#facts.length;
  }

  /** Clear all facts (for benchmarking resets). */
  clear() {
    this.#facts = [];
    this.#nextTxId = 1;
  }
}
