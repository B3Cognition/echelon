# B-001: Lock Contention Benchmark

Generated: 2026-03-19T20:42:58Z

| Writers | Hold (s) | P50 wait (ms) | P95 wait (ms) | P99 wait (ms) | Timeouts | Pending queue |
|---------|----------|---------------|---------------|---------------|----------|---------------|
| 2 | 30 | 29940 | 29940 | 29940 | 0 | 0 |
| 2 | 29 | 29931 | 29931 | 29931 | 1 | 1 |
| 2 | 31 | 29350 | 29350 | 29350 | 1 | 1 |
| 2 | 30 | 30344 | 30344 | 30344 | 1 | 1 |
| 5 | 10 | 11366 | 13042 | 13202 | 0 | 0 |

## Acceptance Checks

- 2 writers hold=29s, second succeeds: **FAIL: 1 timeouts**
- 2 writers hold=31s, second times out: **PASS**
| 2 | 31 | 8654 | 8654 | 8654 | 0 | 0 |
| 5 | 10 | 11514 | 12290 | 12324 | 0 | 0 |

## Acceptance Checks

- 2 writers hold=29s, second succeeds: **FAIL: 1 timeouts**
- 2 writers hold=31s, second times out: **PASS**
