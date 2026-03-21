/**
 * Benchmark: 1000 cycles with 50 beliefs and 10 plans.
 * Measures average cycle time for the ADOPT/TRIAL/DROP decision.
 */

import { BeliefBase } from "./belief-base.js";
import { PlanLibrary } from "./plan-library.js";
import { ReasoningCycle } from "./reasoning-cycle.js";
import { EventKind, BodyStepType } from "./types.js";

function buildBenchmarkEngine() {
  const beliefs = new BeliefBase();
  const plans = new PlanLibrary();

  // Populate 50 beliefs
  for (let i = 0; i < 50; i++) {
    beliefs.add({ functor: "fact", args: [i, `value_${i}`] });
  }
  beliefs.drainEvents(); // clear initial events

  // Populate 10 plans with various context conditions
  for (let i = 0; i < 10; i++) {
    const plan = {
      label: `plan_${i}`,
      trigger: EventKind.GoalAdd,
      triggerFunctor: `goal_${i % 5}`, // 5 distinct goal functors, 2 plans each
      context: (bs) => bs.has(`fact(${i * 5},value_${i * 5})`),
      body: [
        { type: BodyStepType.Action, functor: `action_${i}_a`, args: [] },
        {
          type: BodyStepType.AddBelief,
          functor: "step_done",
          args: [i],
        },
        { type: BodyStepType.Action, functor: `action_${i}_b`, args: [] },
      ],
    };
    plans.add(plan);
  }

  let actionCount = 0;
  const engine = new ReasoningCycle(beliefs, plans, () => {
    actionCount++;
    return { success: true };
  });

  return engine;
}

function runBenchmark() {
  const CYCLES = 1000;
  const engine = buildBenchmarkEngine();

  // Pre-populate event queue with goals
  for (let i = 0; i < CYCLES; i++) {
    engine.postGoal(`goal_${i % 5}`, i);
  }

  // Warm up
  for (let i = 0; i < 10; i++) {
    const warmEngine = buildBenchmarkEngine();
    warmEngine.postGoal("goal_0");
    warmEngine.runToCompletion();
  }

  // Benchmark individual cycles
  const cycleTimes = [];
  const start = performance.now();

  for (let i = 0; i < CYCLES; i++) {
    const cycleStart = performance.now();
    engine.cycle();
    const cycleEnd = performance.now();
    cycleTimes.push(cycleEnd - cycleStart);
  }

  const totalMs = performance.now() - start;
  const avgCycleMs = totalMs / CYCLES;
  const medianCycleMs = cycleTimes.sort((a, b) => a - b)[
    Math.floor(CYCLES / 2)
  ];
  const p99CycleMs = cycleTimes[Math.floor(CYCLES * 0.99)];
  const maxCycleMs = cycleTimes[CYCLES - 1];

  console.log("=== SP-001 BDI Benchmark ===");
  console.log(`Cycles:      ${CYCLES}`);
  console.log(`Beliefs:     50`);
  console.log(`Plans:       10`);
  console.log(`Total time:  ${totalMs.toFixed(3)} ms`);
  console.log(`Avg cycle:   ${(avgCycleMs * 1000).toFixed(1)} us (${avgCycleMs.toFixed(4)} ms)`);
  console.log(`Median:      ${(medianCycleMs * 1000).toFixed(1)} us`);
  console.log(`P99:         ${(p99CycleMs * 1000).toFixed(1)} us`);
  console.log(`Max:         ${(maxCycleMs * 1000).toFixed(1)} us`);
  console.log();

  // Decision thresholds
  if (avgCycleMs < 1) {
    console.log("VERDICT: ADOPT (cycle < 1ms)");
  } else if (avgCycleMs < 5) {
    console.log("VERDICT: TRIAL (cycle 1-5ms)");
  } else {
    console.log("VERDICT: DROP (cycle > 5ms)");
  }
}

runBenchmark();
