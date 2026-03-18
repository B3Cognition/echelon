# TRIZ 40 Inventive Principles

Source: Genrich Altshuller, analysis of 400,000 patents (1946-1985)
Standard: ISO/TR 18686:2017 — Guidelines for TRIZ application
Reference: https://triz.org/principles/

Used by: INNOVATE agent (Phase 2: AutoTRIZ)

Each principle includes the original engineering definition and a **software engineering adaptation** showing how to apply it to code, architecture, and system design.

---

## Principle 1: Segmentation

**Original:** Divide an object into independent parts.
**Software:** Split a monolith into independent modules/services. Decompose a large function into smaller, focused functions. Separate concerns.

- Divide a system into modules that can be developed, tested, and deployed independently
- Split a database into domain-specific stores
- Break a complex algorithm into pipeline stages

## Principle 2: Taking Out (Extraction)

**Original:** Separate an interfering part or property from an object.
**Software:** Extract cross-cutting concerns (logging, auth, caching) from business logic. Move configuration out of code. Separate data from behavior.

- Extract a library from a monorepo
- Move secrets out of code into environment variables
- Separate read and write models (CQRS)

## Principle 3: Local Quality

**Original:** Change from uniform structure to non-uniform. Make each part function in conditions most suitable for its operation.
**Software:** Use different technologies for different components. Cache hot data differently from cold data. Apply different quality gates to different risk levels.

- Different databases for different data patterns (SQL for transactions, NoSQL for analytics)
- Different testing strategies per component risk level
- Different deployment strategies per service criticality

## Principle 4: Asymmetry

**Original:** Change the shape of an object from symmetrical to asymmetrical.
**Software:** Asymmetric API design (simple writes, complex reads). Different scaling strategies for different services. Asymmetric retry policies.

- Read replicas vs single write primary
- Simple ingestion API + complex query API
- Fast path for common cases, thorough path for edge cases

## Principle 5: Merging

**Original:** Bring closer together identical or similar objects or operations.
**Software:** Batch operations. Combine multiple API calls into one. Merge microservices that always deploy together.

- Batch database inserts instead of one-by-one
- GraphQL (one request for multiple resources)
- Merge services that have high coupling into one

## Principle 6: Universality

**Original:** Make a part perform multiple functions.
**Software:** Generic components that handle multiple use cases. Configuration-driven behavior instead of code-per-case.

- A generic data table component used for standings, statistics, rankings
- A plugin architecture where one framework handles all extension types
- Feature flags that control multiple behaviors

## Principle 7: Russian Dolls (Nesting)

**Original:** Place one object inside another.
**Software:** Middleware chains. Decorator pattern. Components within components. Nested containers.

- Middleware stack (auth → logging → rate-limit → handler)
- Docker in Kubernetes in cloud provider
- Component composition (layout → section → card → content)

## Principle 8: Anti-Weight (Counterweight)

**Original:** Compensate for the weight of an object by merging with another that provides lift.
**Software:** Compensating transactions. Circuit breakers. Fallback mechanisms.

- Saga pattern with compensating actions for distributed transactions
- Circuit breaker that degrades gracefully instead of cascading failure
- CDN as counterweight to origin server load

## Principle 9: Preliminary Anti-Action

**Original:** Perform a counteraction in advance.
**Software:** Input validation before processing. Pre-flight checks. Schema validation at the boundary.

- Validate request schema before business logic
- Pre-commit hooks that run linting before code enters the repo
- Feature flag that can instantly disable a new feature

## Principle 10: Preliminary Action

**Original:** Perform a required action in advance.
**Software:** Precomputation. Caching. Eager loading. Pre-warming.

- Precompute search indices
- Pre-warm caches at startup
- Generate static pages at build time (SSG)
- Prefetch data the user is likely to need next

## Principle 11: Beforehand Cushioning

**Original:** Prepare emergency means beforehand.
**Software:** Graceful degradation. Error boundaries. Fallback content. Disaster recovery.

- Error boundaries that catch component failures and show fallback UI
- Read-only mode when database is down
- Backup data source when primary fails
- Blue/green deployments for instant rollback

## Principle 12: Equipotentiality

**Original:** Change conditions so an object need not be raised or lowered.
**Software:** Level the playing field — remove unnecessary differences. Standardize interfaces. Normalize data.

- Standard API contract across all services (OpenAPI)
- Normalized database schema
- Common logging format across all components

## Principle 13: The Other Way Round (Inversion)

**Original:** Invert the action. Make fixed parts movable and movable parts fixed.
**Software:** Inversion of control. Push instead of pull. Event-driven instead of polling. Server-driven instead of client-driven.

- Dependency injection (invert who creates dependencies)
- WebSocket push instead of HTTP polling
- Server-sent events instead of client polling
- Database triggers instead of application-level checks

## Principle 14: Spheroidality (Curvature)

**Original:** Move from flat to curved, from linear to rotational.
**Software:** Move from linear algorithms to logarithmic. From sequential to concurrent. From rigid to flexible.

- Binary search instead of linear scan
- Hash tables instead of array lookups
- Concurrent processing instead of sequential

## Principle 15: Dynamics

**Original:** Make characteristics of an object or environment changeable.
**Software:** Configuration over code. Feature flags. Dynamic scaling. Runtime adaptation.

- Auto-scaling based on load
- Feature flags for runtime behavior changes
- A/B testing with dynamic traffic routing
- Plugin systems that load capabilities at runtime

## Principle 16: Partial or Excessive Action

**Original:** If 100% of an effect is hard to achieve, use slightly more or slightly less.
**Software:** Over-provision then optimize. MVP (less than full). Approximate algorithms.

- Over-provision infrastructure, then scale down based on actual usage
- Ship MVP with 80% of features, measure what's actually needed
- Approximate counting (HyperLogLog) when exact count is too expensive

## Principle 17: Another Dimension

**Original:** Move into an additional dimension.
**Software:** Add a dimension of time (versioning, event sourcing). Add a layer of abstraction. Add caching tier.

- Event sourcing (add time dimension to state)
- API versioning (add version dimension to endpoints)
- CDN layer between client and server
- Abstract syntax tree instead of string parsing

## Principle 18: Mechanical Vibration

**Original:** Use oscillation, resonance.
**Software:** Periodic jobs. Heartbeat checks. Polling with backoff. Retry with jitter.

- Cron jobs for periodic maintenance
- Health check heartbeats
- Exponential backoff with jitter for retries
- Garbage collection cycles

## Principle 19: Periodic Action

**Original:** Replace continuous action with periodic.
**Software:** Batch processing instead of stream. Scheduled sync instead of real-time. Debounce.

- Nightly batch ETL instead of real-time sync
- Debounce user input (wait 300ms after typing stops)
- Periodic cache invalidation instead of per-write invalidation

## Principle 20: Continuity of Useful Action

**Original:** Carry on work without interruption.
**Software:** Streaming instead of request/response. Pipeline processing. Zero-downtime deployments.

- Streaming API instead of paginated requests
- CI/CD pipeline that never stops
- Rolling deployments with zero downtime

## Principle 21: Skipping (Rushing Through)

**Original:** Conduct a process at high speed.
**Software:** Fast path for common cases. Short-circuit evaluation. Fail fast.

- Fast path: if cached, return immediately (skip all processing)
- Short-circuit: if unauthorized, reject before parsing the body
- Fail fast on startup if config is invalid

## Principle 22: Blessing in Disguise

**Original:** Use harmful factors to achieve a positive effect.
**Software:** Use errors as data. Use load spikes for capacity planning. Use technical debt as migration motivation.

- Error tracking as user experience monitoring
- Chaos engineering (inject failures to improve resilience)
- A/B test failures reveal user preferences
- Production incidents → post-mortem → systemic improvement

## Principle 23: Feedback

**Original:** Introduce feedback to improve a process.
**Software:** Monitoring → alerting → auto-scaling. User feedback loops. CALIBRATE agent. A/B testing.

- Application performance monitoring → auto-scale
- Error rate monitoring → circuit breaker → alert
- User analytics → product decisions
- CALIBRATE: prediction vs outcome → correction factor

## Principle 24: Intermediary

**Original:** Use an intermediate carrier or process.
**Software:** Message queues. API gateways. Adapters. Middleware. Proxies.

- Message queue between producer and consumer
- API gateway between client and microservices
- Adapter pattern between old and new interfaces
- Reverse proxy for load balancing and SSL termination

## Principle 25: Self-Service

**Original:** Make an object serve itself.
**Software:** Self-healing systems. Auto-scaling. Self-documenting code. Self-testing systems.

- Kubernetes self-healing (restart crashed pods)
- Auto-scaling based on metrics
- OpenAPI spec generated from code annotations
- Property-based testing (system generates its own test cases)

## Principle 26: Copying

**Original:** Instead of a complex original, use a simple copy.
**Software:** Mocking. Virtualization. Containers. Snapshots. Cloning environments.

- Mock services for testing
- Docker containers (copy of production environment)
- Database snapshots for testing
- Shadow traffic (copy of real traffic to test environment)

## Principle 27: Cheap Short-Lived Objects

**Original:** Replace expensive durable object with cheap disposable ones.
**Software:** Ephemeral infrastructure. Throwaway prototypes. Disposable containers. Spike solutions.

- Spot instances for batch processing
- Throwaway prototype to validate an idea before committing
- Ephemeral test environments (create, test, destroy)
- SCIENTIST's git worktree experiments

## Principle 28: Mechanics Substitution

**Original:** Replace mechanical means with sensory (optical, acoustic, thermal).
**Software:** Replace procedural code with declarative. Replace manual with automated. Replace polling with events.

- SQL (declarative) instead of manual data traversal (procedural)
- Infrastructure as Code instead of manual provisioning
- Event-driven architecture instead of polling
- CSS (declarative styling) instead of imperative DOM manipulation

## Principle 29: Pneumatics and Hydraulics

**Original:** Use gas or liquid parts instead of solid.
**Software:** Use fluid/streaming data structures. Lazy evaluation. Generators. Streams.

- Lazy evaluation (compute only when needed)
- Stream processing (process data as it flows)
- Generators (produce values on demand)
- Reactive streams (backpressure-aware data flow)

## Principle 30: Flexible Shells and Thin Films

**Original:** Use flexible shells and thin films instead of rigid structures.
**Software:** Thin wrapper layers. API facades. Anti-corruption layers. Lightweight adapters.

- Anti-corruption layer between bounded contexts
- Thin API facade over legacy system
- Lightweight adapter instead of full rewrite
- BFF (Backend for Frontend) as thin translation layer

## Principle 31: Porous Materials

**Original:** Make an object porous or add porous elements.
**Software:** Make systems permeable — allow data to flow through. Open APIs. Plugin points. Extension hooks.

- Plugin architecture with defined extension points
- Webhook system (allow external systems to react to events)
- Middleware pipeline (each layer can inspect/modify the flow)
- Open API allowing third-party integrations

## Principle 32: Colour Changes

**Original:** Change the colour of an object or its environment.
**Software:** Change visibility/observability. Add logging. Add tracing. Add metrics. Make the invisible visible.

- Distributed tracing (make request flow visible)
- Feature flags with visual indicators
- Error highlighting in IDE
- Dashboard visualization of system health

## Principle 33: Homogeneity

**Original:** Make objects interact with a given object of the same material.
**Software:** Use the same language/framework throughout. Consistency. Convention over configuration.

- Monorepo (same tooling for all services)
- Consistent API design across all endpoints
- Standard project structure across all teams
- Same testing framework everywhere

## Principle 34: Discarding and Recovering

**Original:** Discard elements that have completed their function. Restore consumable parts.
**Software:** Garbage collection. Cleanup jobs. TTL-based expiry. Auto-rotation of secrets.

- Garbage collection (automatic memory reclaim)
- TTL-based cache expiry
- Log rotation and archival
- Automatic certificate/secret rotation
- Ephemeral container cleanup

## Principle 35: Parameter Changes

**Original:** Change concentration, flexibility, temperature, pressure.
**Software:** Change configuration parameters. Adjust thresholds. Tune performance. Scale resources.

- Adjust cache TTL based on data volatility
- Change rate limits based on load
- Tune database connection pool size
- Adjust retry timeouts based on service health

## Principle 36: Phase Transitions

**Original:** Use phenomena occurring during phase transitions.
**Software:** Use state transitions as triggers. Event sourcing. State machines. Lifecycle hooks.

- State machine for order lifecycle (pending → paid → shipped → delivered)
- Event sourcing (every state change is an event)
- Component lifecycle hooks (mounted, updated, destroyed)
- Database triggers on state changes

## Principle 37: Thermal Expansion

**Original:** Use thermal expansion or contraction.
**Software:** Auto-scaling. Elastic resources. Dynamic allocation.

- Elastic scaling (expand under load, contract when idle)
- Dynamic thread pools
- Auto-provisioning of resources
- Serverless (scale to zero when unused)

## Principle 38: Strong Oxidants (Enriched Atmosphere)

**Original:** Replace common air with enriched air or pure oxygen.
**Software:** Enrich context. Add metadata. Enhance signals. Augment data.

- Request enrichment middleware (add user context, tracing headers)
- Data enrichment pipeline (augment raw data with derived fields)
- Structured logging with rich context
- AI-augmented code review (enrich human review with automated checks)

## Principle 39: Inert Atmosphere

**Original:** Replace normal environment with inert one.
**Software:** Sandboxing. Isolation. Immutability. Read-only filesystems.

- Container sandboxing (isolated execution environment)
- Immutable infrastructure (never modify, always replace)
- Read-only database replicas
- Immutable data structures (prevent mutation bugs)

## Principle 40: Composite Materials

**Original:** Replace homogeneous with composite.
**Software:** Polyglot architecture. Best tool for each job. Hybrid approaches.

- Different databases for different data types (SQL + NoSQL + Graph)
- Different languages for different services (Go for performance, Python for ML)
- Hybrid cloud (on-prem for sensitive data, cloud for elastic compute)
- Composite UI (micro-frontends from different teams/frameworks)
