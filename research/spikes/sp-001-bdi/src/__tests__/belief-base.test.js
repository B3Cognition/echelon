import { describe, it, expect, beforeEach } from "vitest";
import { BeliefBase } from "../belief-base.js";
import { EventKind } from "../types.js";

describe("BeliefBase", () => {
  let bb;

  beforeEach(() => {
    bb = new BeliefBase();
  });

  it("starts empty", () => {
    expect(bb.size).toBe(0);
    expect(bb.all()).toEqual([]);
  });

  it("adds a belief and reports size", () => {
    bb.add({ functor: "at", args: ["agent1", "room1"] });
    expect(bb.size).toBe(1);
  });

  it("returns true for new belief, false for duplicate", () => {
    const b = { functor: "at", args: ["agent1", "room1"] };
    expect(bb.add(b)).toBe(true);
    expect(bb.add(b)).toBe(false);
    expect(bb.size).toBe(1);
  });

  it("checks membership with has()", () => {
    const b = { functor: "holding", args: ["block1"] };
    expect(bb.has(b)).toBe(false);
    bb.add(b);
    expect(bb.has(b)).toBe(true);
  });

  it("removes a belief", () => {
    const b = { functor: "at", args: ["agent1", "room1"] };
    bb.add(b);
    expect(bb.remove(b)).toBe(true);
    expect(bb.size).toBe(0);
    expect(bb.has(b)).toBe(false);
  });

  it("returns false when removing a non-existent belief", () => {
    expect(bb.remove({ functor: "at", args: ["x"] })).toBe(false);
  });

  it("queries beliefs by functor", () => {
    bb.add({ functor: "at", args: ["a1", "r1"] });
    bb.add({ functor: "at", args: ["a2", "r2"] });
    bb.add({ functor: "holding", args: ["b1"] });

    const atBeliefs = bb.query("at");
    expect(atBeliefs).toHaveLength(2);
    expect(atBeliefs.map((b) => b.args[0])).toContain("a1");
    expect(atBeliefs.map((b) => b.args[0])).toContain("a2");
  });

  it("generates BeliefAdd events on add", () => {
    bb.add({ functor: "at", args: ["a1", "r1"] });
    bb.add({ functor: "open", args: ["door1"] });
    const events = bb.drainEvents();

    expect(events).toHaveLength(2);
    expect(events[0].kind).toBe(EventKind.BeliefAdd);
    expect(events[0].functor).toBe("at");
    expect(events[1].kind).toBe(EventKind.BeliefAdd);
    expect(events[1].functor).toBe("open");
  });

  it("generates BeliefDel events on remove", () => {
    bb.add({ functor: "at", args: ["a1", "r1"] });
    bb.drainEvents(); // clear add events
    bb.remove({ functor: "at", args: ["a1", "r1"] });
    const events = bb.drainEvents();

    expect(events).toHaveLength(1);
    expect(events[0].kind).toBe(EventKind.BeliefDel);
    expect(events[0].functor).toBe("at");
  });

  it("drainEvents clears the event buffer", () => {
    bb.add({ functor: "at", args: ["a1", "r1"] });
    bb.drainEvents();
    expect(bb.drainEvents()).toHaveLength(0);
  });

  it("hasKey checks by canonical string", () => {
    bb.add({ functor: "at", args: ["a1", "r1"] });
    expect(bb.hasKey("at(a1,r1)")).toBe(true);
    expect(bb.hasKey("at(a1,r2)")).toBe(false);
  });

  it("handles beliefs with numeric and boolean args", () => {
    bb.add({ functor: "temp", args: [42, true] });
    expect(bb.has({ functor: "temp", args: [42, true] })).toBe(true);
    expect(bb.hasKey("temp(42,true)")).toBe(true);
  });

  it("clear resets everything", () => {
    bb.add({ functor: "a", args: [] });
    bb.add({ functor: "b", args: [] });
    bb.clear();
    expect(bb.size).toBe(0);
    expect(bb.drainEvents()).toHaveLength(0);
  });
});
