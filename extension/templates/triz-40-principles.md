# TRIZ 40 Principles Reference

Use these as prompts for software design alternatives. Apply only the principles selected by the contradiction matrix or a clearly stated analogy.

| # | Principle | Software interpretation |
|---|-----------|-------------------------|
| 1 | Segmentation | Split a component, deployment, data model, or workflow into independently changeable parts. |
| 2 | Taking out | Isolate the harmful or expensive part behind an adapter, queue, feature flag, or worker. |
| 3 | Local quality | Tune behavior by context instead of forcing one uniform mechanism. |
| 4 | Asymmetry | Use different paths for read/write, hot/cold, trusted/untrusted, or simple/complex cases. |
| 5 | Merging | Co-locate related operations to reduce coordination or latency. |
| 6 | Universality | Let one component serve multiple compatible roles without hiding responsibility. |
| 7 | Nested doll | Layer abstractions or containment so inner details can vary safely. |
| 8 | Anti-weight | Offset load with caching, batching, precomputation, or autoscaling. |
| 9 | Preliminary anti-action | Add validation, linting, dry-runs, or canaries before irreversible work. |
| 10 | Preliminary action | Prepare indexes, warm caches, seed data, or provision resources ahead of demand. |
| 11 | Cushion in advance | Add fallback, retries, circuit breakers, backups, and rollback paths. |
| 12 | Equipotentiality | Reduce needless transitions, privilege changes, format conversions, or network hops. |
| 13 | Inversion | Reverse control flow, ownership, dependency direction, or push/pull behavior. |
| 14 | Spheroidality | Replace rigid linear flow with event, graph, or feedback-loop structure. |
| 15 | Dynamics | Make configuration, routing, scaling, or policy adjustable at runtime. |
| 16 | Partial/excessive action | Do a bounded approximation when perfect completion is too expensive. |
| 17 | Another dimension | Move work across time, process, service boundary, cache layer, or storage model. |
| 18 | Mechanical vibration | Use polling, heartbeats, streaming, or repeated sampling when useful. |
| 19 | Periodic action | Batch, schedule, checkpoint, or sample instead of continuous work. |
| 20 | Continuity of useful action | Keep pipelines flowing; avoid idle waits between dependent steps. |
| 21 | Skipping | Fast-path common cases and bypass unnecessary heavy work. |
| 22 | Blessing in disguise | Convert failures or rejected paths into telemetry, training data, or fallback signals. |
| 23 | Feedback | Add measurement and closed-loop correction. |
| 24 | Intermediary | Introduce a broker, adapter, facade, gateway, or staging layer. |
| 25 | Self-service | Let components validate, describe, heal, or provision themselves. |
| 26 | Copying | Use replicas, snapshots, simulations, mocks, or cached projections. |
| 27 | Cheap short-living objects | Use disposable environments, ephemeral workers, or temporary indexes. |
| 28 | Mechanics substitution | Replace manual/process constraints with automation, static analysis, or policy engines. |
| 29 | Pneumatics/hydraulics | Use buffers, queues, backpressure, or elastic resource pools. |
| 30 | Flexible shells | Use interfaces, schemas, plugins, or compatibility layers around volatile parts. |
| 31 | Porous materials | Allow controlled extension points, filters, or partial visibility. |
| 32 | Color changes | Improve observability with explicit states, labels, traces, and dashboards. |
| 33 | Homogeneity | Standardize protocols, formats, naming, or dependencies where variation adds no value. |
| 34 | Discarding/recovering | Retire stale data, rotate resources, compact logs, or rebuild derived state. |
| 35 | Parameter changes | Tune thresholds, consistency, timeouts, retries, or resource limits. |
| 36 | Phase transitions | Change mode under load, failure, migration, or lifecycle stage. |
| 37 | Thermal expansion | Scale up/down or widen/narrow capacity as conditions change. |
| 38 | Strong oxidants | Add stronger enforcement: auth, validation, isolation, or formal checks. |
| 39 | Inert atmosphere | Sandbox, freeze, mock, or isolate volatile dependencies. |
| 40 | Composite materials | Combine complementary techniques such as cache plus source of truth, static plus dynamic checks. |
