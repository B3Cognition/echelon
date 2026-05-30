# Software TRIZ Contradiction Matrix

Use this as a lightweight selector. Pick the parameter to improve and the parameter that gets worse, then apply the listed TRIZ principle numbers from `templates/triz-40-principles.md`.

## Parameters

1. Latency
2. Throughput
3. Reliability
4. Security
5. Maintainability
6. Developer speed
7. Cost
8. Scalability
9. Consistency
10. Flexibility
11. Observability
12. Simplicity
13. Data quality
14. Compatibility
15. Deployment safety
16. User experience

## Common Contradictions

| Improve | Degrades | Principles |
|---------|----------|------------|
| Latency | Consistency | 1, 10, 21, 35 |
| Latency | Security | 2, 11, 24, 38 |
| Throughput | Reliability | 15, 19, 23, 29 |
| Throughput | Cost | 8, 19, 21, 35 |
| Reliability | Developer speed | 9, 11, 23, 28 |
| Reliability | Cost | 10, 11, 26, 34 |
| Security | User experience | 3, 24, 30, 35 |
| Security | Developer speed | 9, 24, 28, 39 |
| Maintainability | Latency | 1, 7, 24, 30 |
| Maintainability | Flexibility | 6, 30, 33, 35 |
| Developer speed | Reliability | 9, 23, 25, 28 |
| Developer speed | Maintainability | 1, 5, 24, 33 |
| Cost | Reliability | 11, 16, 26, 27 |
| Cost | Scalability | 8, 19, 29, 35 |
| Scalability | Consistency | 1, 13, 17, 23 |
| Scalability | Simplicity | 1, 5, 7, 24 |
| Consistency | Availability | 13, 15, 23, 36 |
| Flexibility | Simplicity | 3, 15, 30, 35 |
| Observability | Cost | 16, 19, 26, 32 |
| Observability | User experience | 2, 24, 32, 39 |
| Data quality | Developer speed | 9, 23, 28, 33 |
| Compatibility | Maintainability | 24, 30, 33, 34 |
| Deployment safety | Developer speed | 9, 10, 11, 28 |
| User experience | Security | 3, 24, 30, 35 |

If a pair is not listed, choose the closest row and state the analogy explicitly.
