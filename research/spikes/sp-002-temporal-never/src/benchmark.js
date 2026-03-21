/**
 * SP-002: Performance Benchmark
 *
 * Measures:
 * - End-to-end latency: single agent, 10 agents, 100 agents
 * - Rule evaluation time (isolated)
 * - Store query time (isolated)
 * - Memory usage per 1000 temporal facts
 */

import { TemporalStore, monotonicClock } from './temporal-store.js';
import { neverRepeatFailedPlan, evaluateRule } from './rule-engine.js';
import { createEnforcer } from './enforcement-actor.js';

function median(arr) {
  const sorted = [...arr].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function p99(arr) {
  const sorted = [...arr].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length * 0.99)];
}

function formatMs(ms) {
  return ms < 0.01 ? `${(ms * 1000).toFixed(1)}us` : `${ms.toFixed(3)}ms`;
}

// --- Benchmark: Store Query ---
function benchStoreQuery() {
  console.log('\n=== Store Query Benchmark ===');
  const store = new TemporalStore(monotonicClock);

  // Pre-populate with 1000 facts across 10 agents
  for (let i = 0; i < 1000; i++) {
    store.assert({
      entity: `agent-${i % 10}`,
      attribute: i % 3 === 0 ? 'plan-failed' : 'plan-attempted',
      value: `plan-${i % 20}`,
    });
  }

  const iterations = 10_000;
  const times = [];

  for (let i = 0; i < iterations; i++) {
    const start = performance.now();
    store.query(
      { entity: 'agent-3', attribute: 'plan-failed', value: 'plan-5' },
      performance.now() - 300_000,
    );
    times.push(performance.now() - start);
  }

  console.log(`  Store size: ${store.size} facts`);
  console.log(`  Iterations: ${iterations}`);
  console.log(`  Median: ${formatMs(median(times))}`);
  console.log(`  P99:    ${formatMs(p99(times))}`);
}

// --- Benchmark: Rule Evaluation ---
function benchRuleEvaluation() {
  console.log('\n=== Rule Evaluation Benchmark ===');
  const store = new TemporalStore(monotonicClock);

  // Add some failures
  for (let i = 0; i < 100; i++) {
    store.assert({
      entity: `agent-${i % 10}`,
      attribute: 'plan-failed',
      value: `plan-${i % 5}`,
    });
  }

  const ctx = { agentId: 'agent-3', planId: 'plan-2' };
  const iterations = 10_000;
  const times = [];

  for (let i = 0; i < iterations; i++) {
    const result = evaluateRule(neverRepeatFailedPlan, store, ctx);
    times.push(result.latencyMs);
  }

  console.log(`  Iterations: ${iterations}`);
  console.log(`  Median: ${formatMs(median(times))}`);
  console.log(`  P99:    ${formatMs(p99(times))}`);
}

// --- Benchmark: End-to-End (N agents) ---
function benchEndToEnd(agentCount) {
  console.log(`\n=== End-to-End Benchmark: ${agentCount} agents ===`);
  const store = new TemporalStore(monotonicClock);
  const enforcer = createEnforcer(store, [neverRepeatFailedPlan]);

  // Each agent has had 5 plan failures
  for (let a = 0; a < agentCount; a++) {
    for (let p = 0; p < 5; p++) {
      store.assert({
        entity: `agent-${a}`,
        attribute: 'plan-failed',
        value: `plan-${p}`,
      });
    }
  }

  const iterations = 1000;
  const times = [];

  for (let i = 0; i < iterations; i++) {
    const agentId = `agent-${i % agentCount}`;
    const planId = `plan-${i % 10}`; // some will be denied, some allowed

    const start = performance.now();
    enforcer.requestPlanAttempt({ agentId, planId });
    times.push(performance.now() - start);
  }

  enforcer.stop();

  console.log(`  Store size: ${store.size} facts`);
  console.log(`  Iterations: ${iterations}`);
  console.log(`  Median: ${formatMs(median(times))}`);
  console.log(`  P99:    ${formatMs(p99(times))}`);
  console.log(`  Max:    ${formatMs(Math.max(...times))}`);
}

// --- Benchmark: Memory ---
function benchMemory() {
  console.log('\n=== Memory Benchmark ===');
  const before = process.memoryUsage().heapUsed;
  const store = new TemporalStore(monotonicClock);

  for (let i = 0; i < 10_000; i++) {
    store.assert({
      entity: `agent-${i % 100}`,
      attribute: 'plan-failed',
      value: `plan-${i % 50}`,
    });
  }

  const after = process.memoryUsage().heapUsed;
  const perFact = (after - before) / 10_000;

  console.log(`  Facts: ${store.size}`);
  console.log(`  Total heap delta: ${((after - before) / 1024).toFixed(1)} KB`);
  console.log(`  Per fact: ~${perFact.toFixed(0)} bytes`);
  console.log(`  Per 1000 facts: ~${((perFact * 1000) / 1024).toFixed(1)} KB`);
}

// --- Run All ---
console.log('SP-002 Temporal NEVER Rule — Performance Benchmark');
console.log('='.repeat(55));

benchStoreQuery();
benchRuleEvaluation();
benchEndToEnd(1);
benchEndToEnd(10);
benchEndToEnd(100);
benchMemory();

console.log('\n' + '='.repeat(55));
console.log('Benchmark complete.');
