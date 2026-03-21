import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { TemporalStore } from '../temporal-store.js';
import { neverRepeatFailedPlan } from '../rule-engine.js';
import { createEnforcer } from '../enforcement-actor.js';

function createTestClock(start = 1000) {
  const clock = {
    time: start,
    now() { return this.time; },
    advance(ms) { this.time += ms; },
  };
  return clock;
}

describe('Enforcement Actor (XState)', () => {
  let clock;
  let store;
  let enforcer;

  beforeEach(() => {
    clock = createTestClock(1_000_000);
    store = new TemporalStore(clock);
    enforcer = createEnforcer(store, [neverRepeatFailedPlan]);
  });

  afterEach(() => {
    enforcer.stop();
  });

  it('ALLOWS first plan attempt', () => {
    const verdict = enforcer.requestPlanAttempt({ agentId: 'agent-1', planId: 'goto-room' });
    expect(verdict.verdict).toBe('ALLOW');
  });

  it('records plan-attempted fact on ALLOW', () => {
    enforcer.requestPlanAttempt({ agentId: 'agent-1', planId: 'goto-room' });
    const attempts = store.query({ entity: 'agent-1', attribute: 'plan-attempted', value: 'goto-room' });
    expect(attempts).toHaveLength(1);
  });

  it('DENIES re-attempt after failure within 300s', () => {
    // First attempt succeeds
    enforcer.requestPlanAttempt({ agentId: 'agent-1', planId: 'goto-room' });
    clock.advance(1000);

    // Plan fails
    enforcer.notifyPlanFailed({ agentId: 'agent-1', planId: 'goto-room' });
    clock.advance(100_000); // 100s later

    // Re-attempt within window => DENY
    const verdict = enforcer.requestPlanAttempt({ agentId: 'agent-1', planId: 'goto-room' });
    expect(verdict.verdict).toBe('DENY');
  });

  it('ALLOWS re-attempt after 300s cooldown', () => {
    enforcer.notifyPlanFailed({ agentId: 'agent-1', planId: 'goto-room' });
    clock.advance(300_001); // just over 300s

    const verdict = enforcer.requestPlanAttempt({ agentId: 'agent-1', planId: 'goto-room' });
    expect(verdict.verdict).toBe('ALLOW');
  });

  it('records failure fact on PLAN_FAILED', () => {
    enforcer.notifyPlanFailed({ agentId: 'agent-1', planId: 'goto-room' });
    const failures = store.query({ entity: 'agent-1', attribute: 'plan-failed', value: 'goto-room' });
    expect(failures).toHaveLength(1);
  });

  it('handles multiple agents independently', () => {
    enforcer.notifyPlanFailed({ agentId: 'agent-1', planId: 'goto-room' });
    clock.advance(100_000);

    // Agent-1 denied
    const v1 = enforcer.requestPlanAttempt({ agentId: 'agent-1', planId: 'goto-room' });
    expect(v1.verdict).toBe('DENY');

    // Agent-2 allowed (different agent, no failure)
    const v2 = enforcer.requestPlanAttempt({ agentId: 'agent-2', planId: 'goto-room' });
    expect(v2.verdict).toBe('ALLOW');
  });

  it('handles multiple plans independently', () => {
    enforcer.notifyPlanFailed({ agentId: 'agent-1', planId: 'goto-room' });
    clock.advance(100_000);

    // goto-room denied
    const v1 = enforcer.requestPlanAttempt({ agentId: 'agent-1', planId: 'goto-room' });
    expect(v1.verdict).toBe('DENY');

    // pickup-item allowed (different plan)
    const v2 = enforcer.requestPlanAttempt({ agentId: 'agent-1', planId: 'pickup-item' });
    expect(v2.verdict).toBe('ALLOW');
  });

  describe('belief-change escape hatch integration', () => {
    it('ALLOWS re-attempt when beliefs changed despite being in window', () => {
      // Fail with old beliefs
      enforcer.notifyPlanFailed({
        agentId: 'agent-1',
        planId: 'goto-room',
        beliefs: { doorOpen: false, batteryLevel: 80 },
      });
      clock.advance(100_000);

      // Re-attempt with changed beliefs (door is now open!)
      const verdict = enforcer.requestPlanAttempt({
        agentId: 'agent-1',
        planId: 'goto-room',
        beliefs: { doorOpen: true, batteryLevel: 80 },
      });
      expect(verdict.verdict).toBe('ALLOW');
      expect(verdict.reason).toContain('escape hatch');
    });

    it('DENIES re-attempt when beliefs are unchanged within window', () => {
      const beliefs = { doorOpen: false, batteryLevel: 80 };

      enforcer.notifyPlanFailed({
        agentId: 'agent-1',
        planId: 'goto-room',
        beliefs,
      });
      clock.advance(100_000);

      const verdict = enforcer.requestPlanAttempt({
        agentId: 'agent-1',
        planId: 'goto-room',
        beliefs,
      });
      expect(verdict.verdict).toBe('DENY');
    });
  });

  describe('full lifecycle', () => {
    it('attempt -> fail -> denied -> wait -> allowed', () => {
      // 1. First attempt - allowed
      const v1 = enforcer.requestPlanAttempt({ agentId: 'agent-1', planId: 'goto-room' });
      expect(v1.verdict).toBe('ALLOW');
      clock.advance(5000);

      // 2. Plan fails
      enforcer.notifyPlanFailed({ agentId: 'agent-1', planId: 'goto-room' });
      clock.advance(10_000);

      // 3. Immediate re-attempt - denied
      const v2 = enforcer.requestPlanAttempt({ agentId: 'agent-1', planId: 'goto-room' });
      expect(v2.verdict).toBe('DENY');
      clock.advance(150_000);

      // 4. Half-way re-attempt - still denied
      const v3 = enforcer.requestPlanAttempt({ agentId: 'agent-1', planId: 'goto-room' });
      expect(v3.verdict).toBe('DENY');
      clock.advance(150_000);

      // 5. After 300s total - allowed
      const v4 = enforcer.requestPlanAttempt({ agentId: 'agent-1', planId: 'goto-room' });
      expect(v4.verdict).toBe('ALLOW');
    });
  });
});
