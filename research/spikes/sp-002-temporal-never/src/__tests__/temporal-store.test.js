import { describe, it, expect, beforeEach } from 'vitest';
import { TemporalStore } from '../temporal-store.js';

/** Controllable clock for deterministic tests. */
function createTestClock(start = 1000) {
  const clock = {
    time: start,
    now() { return this.time; },
    advance(ms) { this.time += ms; },
  };
  return clock;
}

describe('TemporalStore', () => {
  let clock;
  let store;

  beforeEach(() => {
    clock = createTestClock(10_000);
    store = new TemporalStore(clock);
  });

  describe('assert', () => {
    it('adds a fact with auto-generated timestamp and tx_id', () => {
      const fact = store.assert({ entity: 'agent-1', attribute: 'plan-failed', value: 'goto-room' });
      expect(fact.entity).toBe('agent-1');
      expect(fact.attribute).toBe('plan-failed');
      expect(fact.value).toBe('goto-room');
      expect(fact.timestamp).toBe(10_000);
      expect(fact.tx_id).toBe(1);
    });

    it('increments tx_id for each assertion', () => {
      store.assert({ entity: 'a', attribute: 'b', value: 'c' });
      const f2 = store.assert({ entity: 'x', attribute: 'y', value: 'z' });
      expect(f2.tx_id).toBe(2);
    });

    it('uses clock timestamp', () => {
      store.assert({ entity: 'a', attribute: 'b', value: 'c' });
      clock.advance(500);
      const f2 = store.assert({ entity: 'a', attribute: 'b', value: 'c' });
      expect(f2.timestamp).toBe(10_500);
    });
  });

  describe('query', () => {
    it('returns facts matching all specified pattern fields', () => {
      store.assert({ entity: 'agent-1', attribute: 'plan-failed', value: 'goto-room' });
      store.assert({ entity: 'agent-1', attribute: 'plan-attempted', value: 'goto-room' });
      store.assert({ entity: 'agent-2', attribute: 'plan-failed', value: 'goto-room' });

      const results = store.query({ entity: 'agent-1', attribute: 'plan-failed' });
      expect(results).toHaveLength(1);
      expect(results[0].value).toBe('goto-room');
    });

    it('treats undefined pattern fields as wildcards', () => {
      store.assert({ entity: 'agent-1', attribute: 'plan-failed', value: 'plan-a' });
      store.assert({ entity: 'agent-2', attribute: 'plan-failed', value: 'plan-b' });

      const results = store.query({ attribute: 'plan-failed' });
      expect(results).toHaveLength(2);
    });

    it('returns empty array when no facts match', () => {
      store.assert({ entity: 'agent-1', attribute: 'plan-failed', value: 'plan-a' });
      const results = store.query({ entity: 'agent-99' });
      expect(results).toHaveLength(0);
    });

    it('filters by since parameter', () => {
      store.assert({ entity: 'a', attribute: 'b', value: 'old' });
      clock.advance(1000);
      store.assert({ entity: 'a', attribute: 'b', value: 'new' });

      const results = store.query({ entity: 'a' }, 10_500);
      expect(results).toHaveLength(1);
      expect(results[0].value).toBe('new');
    });
  });

  describe('asOf', () => {
    it('returns only facts at or before the given timestamp', () => {
      store.assert({ entity: 'a', attribute: 'x', value: 1 });
      clock.advance(1000);
      store.assert({ entity: 'a', attribute: 'x', value: 2 });
      clock.advance(1000);
      store.assert({ entity: 'a', attribute: 'x', value: 3 });

      const snapshot = store.asOf(11_000);
      expect(snapshot).toHaveLength(2);
      expect(snapshot.map((f) => f.value)).toEqual([1, 2]);
    });

    it('returns empty for timestamp before any facts', () => {
      store.assert({ entity: 'a', attribute: 'x', value: 1 });
      expect(store.asOf(9_999)).toHaveLength(0);
    });
  });

  describe('since', () => {
    it('returns facts strictly after the given timestamp', () => {
      store.assert({ entity: 'a', attribute: 'x', value: 1 });
      clock.advance(1000);
      store.assert({ entity: 'a', attribute: 'x', value: 2 });

      const recent = store.since(10_000);
      expect(recent).toHaveLength(1);
      expect(recent[0].value).toBe(2);
    });

    it('returns all facts when since is before all timestamps', () => {
      store.assert({ entity: 'a', attribute: 'x', value: 1 });
      store.assert({ entity: 'a', attribute: 'x', value: 2 });
      expect(store.since(0)).toHaveLength(2);
    });
  });

  describe('size and clear', () => {
    it('tracks fact count', () => {
      expect(store.size).toBe(0);
      store.assert({ entity: 'a', attribute: 'b', value: 'c' });
      expect(store.size).toBe(1);
    });

    it('clears all facts and resets tx_id', () => {
      store.assert({ entity: 'a', attribute: 'b', value: 'c' });
      store.clear();
      expect(store.size).toBe(0);
      const f = store.assert({ entity: 'a', attribute: 'b', value: 'c' });
      expect(f.tx_id).toBe(1);
    });
  });
});
