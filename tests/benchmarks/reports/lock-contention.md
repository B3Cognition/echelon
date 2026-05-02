# B-001: Lock Contention Benchmark

Generated: 2026-05-02T15:21:18Z

| Writers | Hold (s) | P50 wait (ms) | P95 wait (ms) | P99 wait (ms) | Timeouts | Pending queue |
|---------|----------|---------------|---------------|---------------|----------|---------------|
| 2 | 29 | 26 | 26 | 26 | 0 | 0 |
| 2 | 30 | 29 | 29 | 29 | 0 | 0 |
| 2 | 31 | 28 | 28 | 28 | 0 | 0 |
| 5 | 10 | 31 | 31 | 31 | 0 | 0 |

## Acceptance Checks

- 2 writers hold=29s, second succeeds: **PASS**
- 2 writers hold=31s, second times out: **FAIL: 0 timeouts**
