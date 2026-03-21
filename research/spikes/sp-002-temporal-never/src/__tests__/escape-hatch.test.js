import { describe, it, expect, beforeEach } from 'vitest';
import { TemporalStore } from '../temporal-store.js';
import { hashBeliefs, recordFailureWithBeliefs, shouldEscapeHatch } from '../escape-hatch.js';

function createTestClock(start = 1000) {
  const clock = {
    time: start,
    now() { return this.time; },
    advance(ms) { this.time += ms; },
  };
  return clock;
}

describe('Escape Hatch', () => {
  let clock;
  let store;

  beforeEach(() => {
    clock = createTestClock(1_000_000);
    store = new TemporalStore(clock);
  });

  describe('hashBeliefs', () => {
    it('produces consistent hash for same beliefs', () => {
      const beliefs = { roomOpen: true, batteryLevel: 80 };
      expect(hashBeliefs(beliefs)).toBe(hashBeliefs(beliefs));
    });

    it('produces same hash regardless of key insertion order', () => {
      const a = { x: 1, y: 2 };
      const b = { y: 2, x: 1 };
      expect(hashBeliefs(a)).toBe(hashBeliefs(b));
    });

    it('produces different hash for different beliefs', () => {
      const a = { roomOpen: true };
      const b = { roomOpen: false };
      expect(hashBeliefs(a)).not.toBe(hashBeliefs(b));
    });
  });

  describe('recordFailureWithBeliefs', () => {
    it('records both plan-failed and failure-belief-hash facts', () => {
      recordFailureWithBeliefs(store, 'agent-1', 'goto-room', { roomOpen: false });
      expect(store.size).toBe(2);

      const failures = store.query({ attribute: 'plan-failed' });
      expect(failures).toHaveLength(1);

      const hashes = store.query({ attribute: 'failure-belief-hash' });
      expect(hashes).toHaveLength(1);
      expect(hashes[0].value).toMatch(/^goto-room:belief-/);
    });
  });

  describe('shouldEscapeHatch', () => {
    it('returns null when no failure belief hash exists', () => {
      const result = shouldEscapeHatch(store, 'agent-1', 'goto-room', { roomOpen: true }, 300_000);
      expect(result).toBeNull();
    });

    it('returns false when beliefs are the same (no escape)', () => {
      const beliefs = { roomOpen: false, batteryLevel: 50 };
      recordFailureWithBeliefs(store, 'agent-1', 'goto-room', beliefs);
      clock.advance(100_000);

      const result = shouldEscapeHatch(store, 'agent-1', 'goto-room', beliefs, 300_000);
      expect(result).toBe(false);
    });

    it('returns true when beliefs have changed (escape allowed)', () => {
      const oldBeliefs = { roomOpen: false, batteryLevel: 50 };
      recordFailureWithBeliefs(store, 'agent-1', 'goto-room', oldBeliefs);
      clock.advance(100_000);

      const newBeliefs = { roomOpen: true, batteryLevel: 50 }; // door is now open!
      const result = shouldEscapeHatch(store, 'agent-1', 'goto-room', newBeliefs, 300_000);
      expect(result).toBe(true);
    });

    it('returns null when failure is outside the time window', () => {
      const beliefs = { roomOpen: false };
      recordFailureWithBeliefs(store, 'agent-1', 'goto-room', beliefs);
      clock.advance(300_001); // outside window

      const result = shouldEscapeHatch(store, 'agent-1', 'goto-room', beliefs, 300_000);
      expect(result).toBeNull(); // hash fact is too old, not in window
    });

    it('uses the most recent failure hash when multiple exist', () => {
      const beliefs1 = { roomOpen: false };
      recordFailureWithBeliefs(store, 'agent-1', 'goto-room', beliefs1);
      clock.advance(50_000);

      const beliefs2 = { roomOpen: false, newSensor: true };
      recordFailureWithBeliefs(store, 'agent-1', 'goto-room', beliefs2);
      clock.advance(50_000);

      // Current beliefs match beliefs2 => no escape
      const result = shouldEscapeHatch(store, 'agent-1', 'goto-room', beliefs2, 300_000);
      expect(result).toBe(false);

      // Current beliefs differ from beliefs2 => escape
      const result2 = shouldEscapeHatch(store, 'agent-1', 'goto-room', { roomOpen: true }, 300_000);
      expect(result2).toBe(true);
    });
  });
});
