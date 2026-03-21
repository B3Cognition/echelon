import { describe, it, expect } from 'vitest';
import { TemporalStore } from '../temporal-store.js';
import { neverRepeatFailedPlan, evaluateRule } from '../rule-engine.js';
import {
  failSafeEvaluate,
  createFailingStore,
  createCrashingRule,
  createSlowRule,
} from '../failure-modes.js';

describe('Failure Modes', () => {
  describe('store query throws => DENY', () => {
    it('returns DENY when store.query throws', () => {
      const failStore = createFailingStore('Database connection lost');
      const ctx = { agentId: 'agent-1', planId: 'goto-room' };

      const result = evaluateRule(neverRepeatFailedPlan, failStore, ctx);
      expect(result.verdict).toBe('DENY');
      expect(result.reason).toContain('Database connection lost');
    });
  });

  describe('rule condition throws => DENY', () => {
    it('returns DENY when rule condition crashes', () => {
      const store = new TemporalStore();
      const crashRule = createCrashingRule('CRASH-001', 'Null pointer in condition');
      const ctx = { agentId: 'agent-1', planId: 'goto-room' };

      const result = evaluateRule(crashRule, store, ctx);
      expect(result.verdict).toBe('DENY');
      expect(result.reason).toContain('Null pointer in condition');
    });
  });

  describe('failSafeEvaluate wrapper', () => {
    it('wraps evaluateRule with additional safety', () => {
      const store = new TemporalStore();
      const ctx = { agentId: 'agent-1', planId: 'goto-room' };

      const result = failSafeEvaluate(neverRepeatFailedPlan, store, ctx);
      expect(result.verdict).toBe('ALLOW');
    });

    it('catches errors from evaluateRule itself', () => {
      const failStore = createFailingStore('total failure');
      const ctx = { agentId: 'agent-1', planId: 'goto-room' };

      const result = failSafeEvaluate(neverRepeatFailedPlan, failStore, ctx);
      expect(result.verdict).toBe('DENY');
    });
  });

  describe('timeout => DENY', () => {
    it('returns DENY when evaluation exceeds 50ms', () => {
      const store = new TemporalStore();
      const slowRule = createSlowRule('SLOW-001', 60); // 60ms busy wait
      const ctx = { agentId: 'agent-1', planId: 'goto-room' };

      const result = evaluateRule(slowRule, store, ctx);
      expect(result.verdict).toBe('DENY');
      expect(result.reason).toContain('timeout');
      expect(result.latencyMs).toBeGreaterThan(50);
    });
  });
});
