# ISS-001: LIDA Broadcast — Reliability as a WME

**Investigator:** INVESTIGATOR (SCIENTIST)
**Date:** 2026-04-03
**Spec:** 018-soar-overlay
**Files examined:**
- `scripts/bash/lida_broadcast.sh`
- `COMMANDER.md` (Pre-Dispatch Sequence, Overlay Specifications §3)

---

## Step 1: QUESTION

**What exactly do we not know?**
Is `lida_broadcast` a reliable Working Memory Element (WME) that SOAR seed rules can
condition on across every dispatch cycle, or is it a conditional, consume-once artifact
that may be absent in most cycles?

**What decision depends on this answer?**
Whether SOAR production rules in the spec 018 overlay may use `lida_broadcast` as a
primary condition — e.g., `if context_pack["lida_broadcast"]["urgency"] == "HIGH"`.
Rules that condition on an absent key will never match (or crash), making them
dead rules or error sources.

**What would "good enough" evidence look like?**
Direct code inspection of the injection path and lifetime management in the two source
files. No external research needed — both files are available.

**What is the cost of being wrong?**
A production rule that conditions on `lida_broadcast` would silently fire on a small
minority of dispatches, creating unreliable context enrichment with no deterministic
failure signal. SOAR rules that fail silently are worse than no rules.

---

## Step 2–3: RESEARCH AND EVIDENCE

### Source A — `scripts/bash/lida_broadcast.sh` (Grade B: source code)

Key findings:

1. **Payload file**: `.specify/squad/lida-payload.json`
2. **`broadcast` subcommand**: writes (overwrites, per FR-CAO-003) the payload JSON to
   the file. This call is NOT automatic — something external must invoke it explicitly.
3. **`cleanup` subcommand**: unconditionally deletes `lida-payload.json`.
4. **No periodic trigger**: there is no cron, timer, or automatic mechanism in this
   script that produces a broadcast. It is purely on-demand.

```bash
# From lida_broadcast.sh — the only write path:
printf '%s' "${payload}" > "${PAYLOAD_FILE}"

# From lida_broadcast.sh — cleanup deletes whatever remains:
rm -f "${PAYLOAD_FILE}"
```

### Source B — `COMMANDER.md` Pre-Dispatch Sequence (Grade B: source code)

COMMANDER injects `lida_broadcast` via:

```python
lida_payload_path = ".specify/squad/lida-payload.json"
if os.path.isfile(lida_payload_path):           # <-- CONDITIONAL check
    with open(lida_payload_path) as f:
        lida_payload = json.load(f)
    os.remove(lida_payload_path)                 # <-- FILE DELETED AFTER READ
    context_pack["lida_broadcast"] = lida_payload
```

Critical observations:
- The injection is **guarded by `os.path.isfile`** — if the file does not exist, no key
  is injected. The key `lida_broadcast` is **absent** from `context_pack` in the
  majority of cycles.
- The file is **deleted immediately after reading** (`os.remove`). Even if a broadcast
  was injected for dispatch N, it is gone before dispatch N+1. This is the consume-once
  semantic (FR-CAO-003 explicitly named "consume-once").
- Cleanup at run-end (`lida_broadcast.sh cleanup <run_id>`) removes any unconsumed
  payload, ensuring no stale broadcast bleeds across runs.

### Injection frequency analysis

For `lida_broadcast` to be present in `context_pack`, the following must all be true
for that specific dispatch cycle:
1. Some external caller invoked `lida_broadcast.sh broadcast <json>` before this cycle.
2. No previous dispatch in this same cycle already consumed the file.
3. The cleanup subcommand has not been called yet.

Given that COMMANDER calls overlays in sequence (Goal Stack → ACT-R → LIDA → GWT →
Episodic), and the file is deleted at step 3, only one dispatch per "broadcast event"
can receive the payload. In a typical run with multiple agent dispatches and no explicit
broadcast calls, the file will be absent for every dispatch.

---

## Step 4: HYPOTHESIS

**H1:** `lida_broadcast` is present in `context_pack` only when an external caller has
written `.specify/squad/lida-payload.json` since the last dispatch cycle consumed it.

**H1 is falsifiable:** It would be false if the pre-dispatch sequence contained an
automatic payload generator. Inspection of `COMMANDER.md` confirms no such generator
exists — the sequence shows only the file-check-and-consume path.

**H1 verdict: CONFIRMED** by direct code inspection.

---

## Step 5: EXPERIMENT

No code experiment needed. The mechanism is fully determined by source inspection.
The conditional guard (`os.path.isfile`) and the `os.remove` call are unambiguous.

---

## Step 7: SYNTHESIS

| Property | Finding | Evidence Grade |
|----------|---------|----------------|
| Injection mechanism | Conditional file-check only | B (source code) |
| Key always present? | NO — absent when file is missing | B |
| Lifetime | Consume-once: deleted on first read | B |
| Automatic generation? | No — requires explicit external call | B |
| Fraction of dispatches with payload | Near-zero in normal operation | B |
| Stale bleed across dispatches? | Impossible — file deleted before next cycle | B |
| Stale bleed across runs? | Impossible — cleanup removes unconsumed payload | B |

---

## Step 8: RECOMMENDATION

```
Recommendation: SOAR seed rules in spec 018 MUST NOT use `lida_broadcast` as a
                primary condition. Any rule that conditions on this key will fire
                on a small, unpredictable fraction of dispatches only (near-zero
                in normal operation). Such rules must be treated as
                optional/opportunistic enrichment rules, not reliable production rules.

Confidence: 0.97
Evidence: Grade B — direct source code inspection of lida_broadcast.sh and
          COMMANDER.md Pre-Dispatch Sequence. Both files are unambiguous.
Caveats: If the calling system systematically fires lida_broadcast.sh before every
         dispatch, the key would be present more reliably. However, this is not the
         current design and would require an architectural change outside spec 018.
Alternatives: Rules that want LIDA-like prioritization should condition on
              `active_goal` (always present) or `gwt_workspace` (always present)
              instead. `lida_broadcast` may be used as an optional condition modifier
              via a guard: `if "lida_broadcast" in context_pack`.
```

---

## Conclusion

**SOAR seed rules MUST NOT use `lida_broadcast` as a reliable condition.**

Three independent mechanisms enforce this:
1. **Conditional injection**: the key is only set when `.specify/squad/lida-payload.json`
   exists at dispatch time.
2. **Consume-once deletion**: the file is deleted immediately after reading, so no
   subsequent dispatch in the same run can see the same payload.
3. **External trigger required**: no automatic mechanism produces the broadcast file;
   an explicit external call to `lida_broadcast.sh broadcast` is required.

Any SOAR production rule that conditions on `lida_broadcast` is an **opportunistic rule**
— it can enrich context when a broadcast happens to be present, but it must degrade
gracefully (not fire) when the key is absent. It cannot be a foundational rule for the
SOAR overlay's core behavior.
