import { describe, it, expect, beforeEach } from "vitest";
import { PlanLibrary } from "../plan-library.js";
import { EventKind, BodyStepType } from "../types.js";

describe("PlanLibrary", () => {
  let lib;

  beforeEach(() => {
    lib = new PlanLibrary();
  });

  const makePlan = (
    label,
    triggerFunctor,
    contextFn = () => true,
  ) => ({
    label,
    trigger: EventKind.GoalAdd,
    triggerFunctor,
    context: contextFn,
    body: [{ type: BodyStepType.Action, functor: `do_${label}`, args: [] }],
  });

  it("starts empty", () => {
    expect(lib.size).toBe(0);
  });

  it("adds plans and reports size", () => {
    lib.add(makePlan("p1", "go"));
    lib.add(makePlan("p2", "go"));
    expect(lib.size).toBe(2);
  });

  it("finds applicable plans by trigger functor", () => {
    lib.add(makePlan("p1", "go"));
    lib.add(makePlan("p2", "fetch"));
    lib.add(makePlan("p3", "go"));

    const event = {
      kind: EventKind.GoalAdd,
      functor: "go",
      args: [],
    };
    const applicable = lib.findApplicable(event, new Set());
    expect(applicable).toHaveLength(2);
    expect(applicable[0].label).toBe("p1");
    expect(applicable[1].label).toBe("p3");
  });

  it("filters by trigger kind", () => {
    const beliefPlan = {
      label: "on-belief",
      trigger: EventKind.BeliefAdd,
      triggerFunctor: "detected",
      context: () => true,
      body: [],
    };
    lib.add(beliefPlan);

    // Goal event should not match belief-triggered plan
    const goalEvent = {
      kind: EventKind.GoalAdd,
      functor: "detected",
      args: [],
    };
    expect(lib.findApplicable(goalEvent, new Set())).toHaveLength(0);

    // Belief event should match
    const beliefEvent = {
      kind: EventKind.BeliefAdd,
      functor: "detected",
      args: [],
    };
    expect(lib.findApplicable(beliefEvent, new Set())).toHaveLength(1);
  });

  it("filters by context condition", () => {
    lib.add(
      makePlan("with-key", "open_door", (bs) => bs.has("holding(key)")),
    );
    lib.add(
      makePlan("force-open", "open_door", () => true),
    );

    const event = {
      kind: EventKind.GoalAdd,
      functor: "open_door",
      args: [],
    };

    // Without the key belief: only force-open is applicable
    const noKey = lib.findApplicable(event, new Set());
    expect(noKey).toHaveLength(1);
    expect(noKey[0].label).toBe("force-open");

    // With the key belief: both are applicable
    const withKey = lib.findApplicable(event, new Set(["holding(key)"]));
    expect(withKey).toHaveLength(2);
    expect(withKey[0].label).toBe("with-key"); // first match
  });

  it("returns empty array when no plans match", () => {
    lib.add(makePlan("p1", "go"));
    const event = {
      kind: EventKind.GoalAdd,
      functor: "nonexistent",
      args: [],
    };
    expect(lib.findApplicable(event, new Set())).toHaveLength(0);
  });

  it("addAll adds multiple plans", () => {
    lib.addAll([makePlan("a", "go"), makePlan("b", "go")]);
    expect(lib.size).toBe(2);
  });
});
