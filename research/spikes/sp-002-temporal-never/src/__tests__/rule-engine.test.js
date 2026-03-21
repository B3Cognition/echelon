import { describe, it, expect, beforeEach } from 'vitest';
import { TemporalStore } from '../temporal-store.js';
import { neverRepeatFailedPlan, evaluateRule, evaluateAllRules } from '../rule-engine.js';

function createTestClock(start = 1000) {
  const clock = {
    time: start,
    now() { return this.time; },
    advance(ms) { this.time += ms; },
  };
  return clock;
}

describe('Rule Engine', () => {
  let clock;
  let store;

  beforeEach(() => {
    clock = createTestClock(1_000_000); // start high enough so window math works
    store = new TemporalStore(clock);
  });

  describe('NEVER-001: neverRepeatFailedPlan', () => {
    const ctx = { agentId: 'agent-1', planId: 'goto-room' };

    it('ALLOWS attempt when no prior failures exist', () => {
      const result = evaluateRule(neverRepeatFailedPlan, store, ctx);
      expect(result.verdict).toBe('ALLOW');
    });

    it('DENIES re-attempt within 300s of failure', () => {
      store.assert({ entity: 'agent-1', attribute: 'plan-failed', value: 'goto-room' });
      clock.advance(100_000); // 100s later

      const result = evaluateRule(neverRepeatFailedPlan, store, ctx);
      expect(result.verdict).toBe('DENY');
      expect(result.reason).toContain('goto-room');
    });

    it('ALLOWS re-attempt after 300s have passed', () => {
      store.assert({ entity: 'agent-1', attribute: 'plan-failed', value: 'goto-room' });
      clock.advance(300_001); // just over 300s

      const result = evaluateRule(neverRepeatFailedPlan, store, ctx);
      expect(result.verdict).toBe('ALLOW');
    });

    it('ALLOWS attempt for a different plan even if another plan failed', () => {
      store.assert({ entity: 'agent-1', attribute: 'plan-failed', value: 'other-plan' });
      clock.advance(10_000);

      const result = evaluateRule(neverRepeatFailedPlan, store, { agentId: 'agent-1', planId: 'goto-room' });
      expect(result.verdict).toBe('ALLOW');
    });

    it('ALLOWS attempt for a different agent even if same plan failed for another', () => {
      store.assert({ entity: 'agent-2', attribute: 'plan-failed', value: 'goto-room' });
      clock.advance(10_000);

      const result = evaluateRule(neverRepeatFailedPlan, store, ctx);
      expect(result.verdict).toBe('ALLOW');
    });

    it('DENIES when multiple failures exist within window', () => {
      store.assert({ entity: 'agent-1', attribute: 'plan-failed', value: 'goto-room' });
      clock.advance(50_000);
      store.assert({ entity: 'agent-1', attribute: 'plan-failed', value: 'goto-room' });
      clock.advance(50_000);

      const result = evaluateRule(neverRepeatFailedPlan, store, ctx);
      expect(result.verdict).toBe('DENY');
    });

    it('reports latency in the result', () => {
      const result = evaluateRule(neverRepeatFailedPlan, store, ctx);
      expect(result.latencyMs).toBeGreaterThanOrEqual(0);
    });
  });

  describe('evaluateAllRules', () => {
    it('returns ALLOW for all rules when no failures', () => {
      const results = evaluateAllRules([neverRepeatFailedPlan], store, { agentId: 'a', planId: 'p' });
      expect(results).toHaveLength(1);
      expect(results[0].verdict).toBe('ALLOW');
    });

    it('short-circuits on first DENY', () => {
      store.assert({ entity: 'a', attribute: 'plan-failed', value: 'p' });
      clock.advance(1000);

      const secondRule = { ...neverRepeatFailedPlan, id: 'NEVER-002' };
      const results = evaluateAllRules([neverRepeatFailedPlan, secondRule], store, { agentId: 'a', planId: 'p' });
      expect(results).toHaveLength(1); // short-circuited, didn't evaluate second
      expect(results[0].verdict).toBe('DENY');
    });
  });
});
