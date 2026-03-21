import { describe, it, expect, beforeEach } from "vitest";
import { BeliefBase } from "../belief-base.js";
import { PlanLibrary } from "../plan-library.js";
import { ReasoningCycle } from "../reasoning-cycle.js";
import { EventKind, BodyStepType } from "../types.js";

describe("ReasoningCycle", () => {
  let beliefs;
  let plans;
  let engine;
  let actionLog;

  beforeEach(() => {
    beliefs = new BeliefBase();
    plans = new PlanLibrary();
    actionLog = [];
    engine = new ReasoningCycle(beliefs, plans, (functor, args) => {
      actionLog.push(`${functor}(${args.join(",")})`);
      return { success: true };
    });
  });

  describe("basic goal-plan execution", () => {
    it("executes a simple goal with one plan", () => {
      plans.add({
        label: "greet-plan",
        trigger: EventKind.GoalAdd,
        triggerFunctor: "greet",
        context: () => true,
        body: [
          { type: BodyStepType.Action, functor: "say_hello", args: [] },
          { type: BodyStepType.Action, functor: "wave", args: [] },
        ],
      });

      engine.postGoal("greet");
      const results = engine.runToCompletion();

      // Cycle 1: process event, create intention, execute step 1
      // Cycle 2: execute step 2
      // Cycle 3: intention completes
      expect(actionLog).toEqual(["say_hello()", "wave()"]);
      const allCompleted = results.flatMap((r) => r.goalsCompleted);
      expect(allCompleted).toContain("greet");
    });

    it("passes args through to actions", () => {
      plans.add({
        trigger: EventKind.GoalAdd,
        triggerFunctor: "move",
        context: () => true,
        body: [
          {
            type: BodyStepType.Action,
            functor: "goto",
            args: ["room2"],
          },
        ],
      });

      engine.postGoal("move", "room2");
      engine.runToCompletion();
      expect(actionLog).toEqual(["goto(room2)"]);
    });
  });

  describe("belief manipulation in plans", () => {
    it("adds and tests beliefs within plan body", () => {
      plans.add({
        trigger: EventKind.GoalAdd,
        triggerFunctor: "setup",
        context: () => true,
        body: [
          { type: BodyStepType.AddBelief, functor: "ready", args: [true] },
          { type: BodyStepType.TestGoal, functor: "ready", args: [true] },
          { type: BodyStepType.Action, functor: "proceed", args: [] },
        ],
      });

      engine.postGoal("setup");
      engine.runToCompletion();

      expect(beliefs.has({ functor: "ready", args: [true] })).toBe(true);
      expect(actionLog).toContain("proceed()");
    });

    it("test goal fails if belief not present", () => {
      plans.add({
        trigger: EventKind.GoalAdd,
        triggerFunctor: "check",
        context: () => true,
        body: [
          // Test for a belief that doesn't exist — should fail
          {
            type: BodyStepType.TestGoal,
            functor: "nonexistent",
            args: [],
          },
          { type: BodyStepType.Action, functor: "should_not_run", args: [] },
        ],
      });

      engine.postGoal("check");
      const results = engine.runToCompletion();

      expect(actionLog).not.toContain("should_not_run()");
      const allFailed = results.flatMap((r) => r.goalsFailed);
      expect(allFailed).toContain("check");
    });
  });

  describe("plan context conditions", () => {
    it("selects plan based on belief context", () => {
      plans.add({
        label: "with-tool",
        trigger: EventKind.GoalAdd,
        triggerFunctor: "fix",
        context: (bs) => bs.has("holding(wrench)"),
        body: [
          { type: BodyStepType.Action, functor: "use_wrench", args: [] },
        ],
      });
      plans.add({
        label: "without-tool",
        trigger: EventKind.GoalAdd,
        triggerFunctor: "fix",
        context: () => true,
        body: [
          { type: BodyStepType.Action, functor: "use_hands", args: [] },
        ],
      });

      // Without wrench — should use hands
      engine.postGoal("fix");
      engine.runToCompletion();
      expect(actionLog).toEqual(["use_hands()"]);

      // Reset and add wrench
      actionLog.length = 0;
      beliefs.add({ functor: "holding", args: ["wrench"] });
      beliefs.drainEvents();
      engine.postGoal("fix");
      engine.runToCompletion();
      expect(actionLog).toEqual(["use_wrench()"]);
    });
  });

  describe("failure recovery", () => {
    it("falls back to alternative plan on action failure", () => {
      const failActions = new Set(["pick_lock"]);

      engine.setActionHandler((functor, args) => {
        if (failActions.has(functor)) {
          return { success: false };
        }
        actionLog.push(`${functor}(${args.join(",")})`);
        return { success: true };
      });

      plans.add({
        label: "pick-lock",
        trigger: EventKind.GoalAdd,
        triggerFunctor: "open_door",
        context: () => true,
        body: [
          { type: BodyStepType.Action, functor: "pick_lock", args: [] },
        ],
      });
      plans.add({
        label: "break-door",
        trigger: EventKind.GoalAdd,
        triggerFunctor: "open_door",
        context: () => true,
        body: [
          { type: BodyStepType.Action, functor: "kick_door", args: [] },
        ],
      });

      engine.postGoal("open_door");
      engine.runToCompletion();

      // pick_lock fails, falls back to kick_door
      expect(actionLog).toEqual(["kick_door()"]);
    });

    it("reports goal failure when all plans exhausted", () => {
      engine.setActionHandler(() => ({ success: false }));

      plans.add({
        label: "plan-a",
        trigger: EventKind.GoalAdd,
        triggerFunctor: "impossible",
        context: () => true,
        body: [
          { type: BodyStepType.Action, functor: "try_a", args: [] },
        ],
      });
      plans.add({
        label: "plan-b",
        trigger: EventKind.GoalAdd,
        triggerFunctor: "impossible",
        context: () => true,
        body: [
          { type: BodyStepType.Action, functor: "try_b", args: [] },
        ],
      });

      engine.postGoal("impossible");
      const results = engine.runToCompletion();
      const allFailed = results.flatMap((r) => r.goalsFailed);
      expect(allFailed).toContain("impossible");
    });

    it("reports failure when no plan exists for a goal", () => {
      engine.postGoal("unknown_goal");
      const results = engine.runToCompletion();
      const allFailed = results.flatMap((r) => r.goalsFailed);
      expect(allFailed).toContain("unknown_goal");
    });
  });

  describe("sub-goals", () => {
    it("executes sub-goals via plan decomposition", () => {
      // Top-level plan: !build_house decomposes into sub-goals
      plans.add({
        label: "build-house",
        trigger: EventKind.GoalAdd,
        triggerFunctor: "build_house",
        context: () => true,
        body: [
          {
            type: BodyStepType.SubGoal,
            functor: "lay_foundation",
            args: [],
          },
          { type: BodyStepType.SubGoal, functor: "build_walls", args: [] },
          { type: BodyStepType.Action, functor: "celebrate", args: [] },
        ],
      });

      plans.add({
        label: "foundation-plan",
        trigger: EventKind.GoalAdd,
        triggerFunctor: "lay_foundation",
        context: () => true,
        body: [
          { type: BodyStepType.Action, functor: "dig", args: [] },
          { type: BodyStepType.Action, functor: "pour_concrete", args: [] },
        ],
      });

      plans.add({
        label: "walls-plan",
        trigger: EventKind.GoalAdd,
        triggerFunctor: "build_walls",
        context: () => true,
        body: [
          { type: BodyStepType.Action, functor: "stack_bricks", args: [] },
        ],
      });

      engine.postGoal("build_house");
      engine.runToCompletion();

      expect(actionLog).toContain("dig()");
      expect(actionLog).toContain("pour_concrete()");
      expect(actionLog).toContain("stack_bricks()");
      expect(actionLog).toContain("celebrate()");
    });
  });

  describe("belief-triggered plans", () => {
    it("reacts to belief additions", () => {
      plans.add({
        label: "on-fire-detected",
        trigger: EventKind.BeliefAdd,
        triggerFunctor: "fire",
        context: () => true,
        body: [
          { type: BodyStepType.Action, functor: "sound_alarm", args: [] },
          { type: BodyStepType.Action, functor: "call_911", args: [] },
        ],
      });

      // Adding a belief generates a BeliefAdd event
      beliefs.add({ functor: "fire", args: ["building1"] });
      engine.runToCompletion();

      expect(actionLog).toContain("sound_alarm()");
      expect(actionLog).toContain("call_911()");
    });
  });

  describe("3-goal scenario (spec requirement)", () => {
    it("handles primary plan, fallback, and goal failure across 3 goals", () => {
      const failSet = new Set(["flimsy_bridge"]);

      engine.setActionHandler((functor, args) => {
        if (failSet.has(functor)) return { success: false };
        actionLog.push(`${functor}(${args.join(",")})`);
        return { success: true };
      });

      // Goal 1: "cross_river" — primary plan (bridge) fails, fallback (swim) succeeds
      plans.add({
        label: "bridge",
        trigger: EventKind.GoalAdd,
        triggerFunctor: "cross_river",
        context: () => true,
        body: [
          {
            type: BodyStepType.Action,
            functor: "flimsy_bridge",
            args: [],
          },
        ],
      });
      plans.add({
        label: "swim",
        trigger: EventKind.GoalAdd,
        triggerFunctor: "cross_river",
        context: () => true,
        body: [
          { type: BodyStepType.Action, functor: "swim_across", args: [] },
        ],
      });

      // Goal 2: "find_treasure" — succeeds on first plan
      plans.add({
        label: "dig",
        trigger: EventKind.GoalAdd,
        triggerFunctor: "find_treasure",
        context: () => true,
        body: [
          { type: BodyStepType.Action, functor: "dig_here", args: [] },
          {
            type: BodyStepType.AddBelief,
            functor: "has_treasure",
            args: [true],
          },
        ],
      });

      // Goal 3: "fly" — no viable plan (total failure)
      plans.add({
        label: "flap-arms",
        trigger: EventKind.GoalAdd,
        triggerFunctor: "fly",
        context: (bs) => bs.has("has_wings(true)"), // agent has no wings
        body: [
          { type: BodyStepType.Action, functor: "flap", args: [] },
        ],
      });

      engine.postGoal("cross_river");
      engine.postGoal("find_treasure");
      engine.postGoal("fly");

      const results = engine.runToCompletion();
      const allCompleted = results.flatMap((r) => r.goalsCompleted);
      const allFailed = results.flatMap((r) => r.goalsFailed);

      // Goal 1: bridge failed, swim succeeded
      expect(actionLog).toContain("swim_across()");
      expect(actionLog).not.toContain("flimsy_bridge()");
      expect(allCompleted).toContain("cross_river");

      // Goal 2: dig succeeded, belief added
      expect(actionLog).toContain("dig_here()");
      expect(allCompleted).toContain("find_treasure");
      expect(beliefs.has({ functor: "has_treasure", args: [true] })).toBe(
        true,
      );

      // Goal 3: no applicable plan — failure
      expect(allFailed).toContain("fly");
    });
  });
});
