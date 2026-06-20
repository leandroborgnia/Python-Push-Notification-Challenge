# Feature Specification: System Liveness Walking Skeleton

**Feature Branch**: `001-system-liveness`

**Created**: 2026-06-19

**Status**: Draft

**Input**: User description: "A developer-facing 'system liveness' slice: the thinnest end-to-end vertical that proves every subsystem of the service is wired together and alive, before any real feature exists."

## Clarifications

### Session 2026-06-19

- Q: When the readiness endpoint is called, how is the per-path background round-trip performed? → A: Split the check. The always-on readiness endpoint does **shallow, cheap, bounded per-path connectivity only** — data store `SELECT 1`, message broker reachability, and a worker control/liveness ping per pool — and it MUST NOT block on a job result or couple API readiness to worker job-execution liveness. The **full per-path no-op job round-trip** that proves queue→pool routing end-to-end is a **separate on-demand check**, exercised primarily as a CI/deploy smoke test, not on every readiness call.
- Q: Is wiring/verifying the telemetry stack (structured logging, tracing, error reporting) part of this slice's Definition of Done? → A: Yes — wire **and** verify. Initialize structured logging, distributed tracing, and error reporting at startup, and assert minimal emission in tests: a structured startup log line, a trace span on the readiness request, and error-reporting initialization. Telemetry is not a readiness-checked subsystem; it is verified via the test suite.
- Q: How does the aggregate readiness endpoint relate to the API's Kubernetes probe, and what status does it return when unhealthy? → A: **Two endpoints, status-coded.** A separate, narrow k8s liveness/readiness probe reflects only the API process and the dependencies it needs to serve (e.g., data store), is **never** gated on worker pools, and returns 2xx/503. The rich aggregate readiness endpoint returns **HTTP 200 when healthy and HTTP 503 when not-healthy**, always including the full per-subsystem breakdown in the body. Implementing the probe endpoint is in scope; the k8s manifest wiring is also in scope (see Session 2026-06-20). (Refined in Session 2026-06-20: this narrow probe is split into a process-only **liveness** probe and a process+data-store **readiness** probe — see FR-018/FR-020.)
- Q: How is background-job completion observed — is there a task result store subsystem? → A: **No result backend.** Background tasks run with results disabled (`ignore_result=True`); the "task result store" is removed as a readiness subsystem entirely (with no backend there is nothing to health-check). The on-demand smoke check enqueues a trivial no-op task **defined in our own codebase** — one per worker pool the architecture defines — as a real task on the real broker reaching a real worker (no mock/stub). On execution the task writes a completion record keyed to that specific invocation into an Alembic-managed table using the workers' **synchronous (psycopg)** engine; the check reads that record back through the **async (asyncpg)** data layer with a bounded timeout. Success = the invocation's record appears within the limit. This deep round-trip is the on-demand/CI smoke check only, never part of the always-on readiness endpoint.
- Q: I/O worker pool — threads or gevent (artifacts disagreed)? → A: **Threads** (`--pool=threads`). I/O tasks touch Postgres via the synchronous `psycopg` (v3) engine, which is natively thread-safe, so threads avoid psycogreen monkey-patching and the realistic fan-out does not justify gevent. The constitution was aligned to threads (gevent + psycogreen documented as the higher-concurrency alternative), and the sync driver is pinned to psycopg v3 (psycopg3) across all artifacts. The spec itself stays pool-type-agnostic (it refers only to "background-processing pools").

### Session 2026-06-20

- Q: Should the narrow k8s probe be split into liveness vs readiness? → A: **Yes, split.** A **liveness** probe reflects only the API process (failure → restart) and MUST NOT fail on data-store or worker outages; a **readiness** probe reflects the API process + data-store connectivity (failure → depool from traffic, no restart) and MUST NOT be gated on workers. This prevents a data-store outage from crash-looping the API while still depooling it from traffic. Both remain distinct from the aggregate readiness endpoint (FR-001).
- Q: Is wiring the probes into Kubernetes manifests in scope for this slice (analyze finding I1)? → A: **Yes, in scope.** This slice ships Kubernetes Deployment + Service manifests wiring `/livez`→livenessProbe and `/readyz`→readinessProbe (never gated on workers), plus a CD workflow that deploys them. Supersedes the Session 2026-06-19 note that treated manifest wiring as a deferred planning/ops detail.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Aggregate readiness endpoint (Priority: P1)

As a developer, I can call a single readiness endpoint that reports overall system status and, within
it, shallow connectivity to each subsystem the architecture defines — the data store, the message
broker, and a worker on each background-processing pool.

**Why this priority**: This is the heart of the walking skeleton. A single, trustworthy, cheap
readiness verdict that confirms every subsystem is reachable is what proves the pieces are wired
together. The check is deliberately shallow and bounded: it MUST NOT enqueue or wait on a background
job, and the API's ability to serve MUST NOT be gated on worker job execution (the full end-to-end
routing proof lives in the on-demand smoke check, User Story 4).

**Independent Test**: Stand up the system's dependencies, call the readiness endpoint, and assert it
reports healthy only when every subsystem is reachable; then take one dependency down and assert the
endpoint reports failure, names the failed subsystem, and still returns promptly.

**Acceptance Scenarios**:

1. **Given** the data store, message broker, and a worker on each pool are all reachable, **When** a
   developer calls the readiness endpoint, **Then** it returns an overall "healthy" verdict with a
   per-subsystem breakdown showing each as passing.
2. **Given** the data store is unreachable, **When** the readiness endpoint is called, **Then** it
   returns an overall "not healthy" verdict and identifies the data store as the failing subsystem.
3. **Given** no worker responds on one background-processing pool, **When** the readiness endpoint is
   called, **Then** it returns "not healthy" and identifies that pool as failing while still reporting
   the healthy subsystems as passing — and it returns promptly rather than waiting on any job.
4. **Given** a dependency is failing or slow, **When** the readiness endpoint is called, **Then** it
   returns a verdict within a bounded time rather than hanging, and without blocking on a background
   job result.
5. **Given** any checked subsystem is failing, **When** the aggregate readiness endpoint is called,
   **Then** it responds with HTTP 503 and a body containing the per-subsystem breakdown; when all are
   healthy it responds with HTTP 200 and the same breakdown.
6. **Given** only the worker pools are down (API process and data store healthy), **When** the narrow
   liveness and readiness probes are called, **Then** both return HTTP 2xx (the API is neither restarted
   nor depooled), while the aggregate readiness endpoint returns HTTP 503 reporting the worker pools as
   failing.
7. **Given** the data store is unreachable but the API process is alive, **When** the k8s probes are
   called, **Then** the liveness probe returns HTTP 2xx (no restart) while the readiness probe returns
   HTTP 503 (the pod is depooled from traffic until the data store recovers).

---

### User Story 2 - One-command local bring-up (Priority: P2)

As a developer, I can start the whole system locally with one documented command and have every
service come up healthy.

**Why this priority**: A reproducible, single-command local environment is what lets any developer
trust and extend the skeleton. It is required for hands-on verification but is independently valuable
even before the UI exists.

**Independent Test**: From a clean checkout, run the one documented command and observe every service
reach a healthy state without manual intervention.

**Acceptance Scenarios**:

1. **Given** a clean checkout, **When** a developer runs the single documented bring-up command,
   **Then** every service required for this slice starts and each reports a healthy state.
2. **Given** the system is brought up, **When** the developer inspects service health, **Then** at
   least one schema migration has been applied and the data store is reachable through the
   application's data layer.

---

### User Story 3 - Frontend liveness view (Priority: P3)

As a developer, I can load the frontend and see the system's live status.

**Why this priority**: Surfacing the readiness verdict in the UI proves the frontend is wired to the
backend and gives an at-a-glance health signal, but it depends on the endpoint (US1) already existing.

**Independent Test**: With the readiness endpoint serving a known state, load the frontend and confirm
it displays that state (both a healthy and a non-healthy state).

**Acceptance Scenarios**:

1. **Given** the readiness endpoint reports healthy, **When** a developer loads the frontend, **Then**
   the page renders and displays the overall healthy status and the per-subsystem breakdown.
2. **Given** the readiness endpoint reports a non-healthy state, **When** a developer loads the
   frontend, **Then** the page reflects the non-healthy status rather than always showing healthy.
3. **Given** the readiness endpoint is unreachable, **When** a developer loads the frontend, **Then**
   the page shows an "unavailable / unknown" state rather than a blank page or a false healthy status.

---

### User Story 4 - Automated quality gate & path round-trip smoke check (Priority: P3)

As a developer, the test suite and the lint/type/quality gate both pass on this slice (locally and in
CI), and a separate on-demand smoke check proves each background path routes a job end-to-end.

**Why this priority**: The gate is what makes the skeleton "trustworthy to extend" — it fails fast if
the wiring breaks. The on-demand round-trip smoke check is what proves the full queue→pool routing
(beyond the shallow readiness connectivity), and it runs in CI/deploy rather than on every readiness
call. Both are meaningful only once there is behavior (US1–US3) to test.

**Independent Test**: Run the automated test suite, the quality gate, and the on-demand smoke check
locally and in CI; confirm all are green and that the readiness path, the end-to-end round-trip, and
minimal telemetry emission are all covered against ephemeral dependencies.

**Acceptance Scenarios**:

1. **Given** the slice is complete, **When** the automated test suite runs against ephemeral,
   containerized dependencies, **Then** it exercises the readiness path end-to-end (healthy and
   failure conditions) and passes.
2. **Given** the slice is complete, **When** the lint, formatting, and type-checking gate runs,
   **Then** it passes with no violations.
3. **Given** a change is pushed, **When** CI runs, **Then** the same test suite and quality gate run
   and pass in CI, matching local results.
4. **Given** the system is up, **When** the on-demand round-trip smoke check runs (in CI/deploy or
   manually), **Then** it enqueues a trivial no-op task (from the system's own codebase) on each
   background-processing pool; each task writes a completion record keyed to that invocation via the
   workers' synchronous engine, and the check reads each record back through the asynchronous data layer
   within a bounded time, reporting success only if every pool's record appears. This check is separate
   from the readiness endpoint and is not triggered by a readiness call.
5. **Given** the slice is complete, **When** the test suite runs, **Then** it asserts minimal telemetry
   emission — a structured startup log line, a trace span for a readiness request, and error-reporting
   initialization — and passes.

---

### Edge Cases

- Readiness uses a trivial connectivity probe, so it does not by itself detect a missing or unmigrated
  schema; schema/migration application is verified at bring-up (US2 / FR-008) and exercised by the
  data-layer round-trip in tests — not surfaced as a false readiness pass.
- A background pool has no responding worker → the readiness endpoint reports that pool as failing
  (worker ping fails) and still returns promptly; the on-demand smoke check, if run, fails for that
  pool because the job is not processed within the bounded time.
- Workers are down but the API and data store are up → the aggregate readiness endpoint returns HTTP 503
  and reports the worker pools as failing (promptly), while the narrow liveness and readiness probes stay
  HTTP 2xx so the API process is neither restarted nor depooled (the probes are not gated on worker job
  execution).
- The data store is unreachable but the API process is alive → the liveness probe stays HTTP 2xx (no
  restart loop), the readiness probe returns HTTP 503 (the pod is depooled until the data store
  recovers), and the aggregate readiness endpoint returns HTTP 503.
- One subsystem is healthy and another is not → overall verdict is "not healthy" with an accurate
  per-subsystem breakdown.
- A dependency that was healthy becomes unhealthy on a later call → the subsequent readiness response
  reflects the new state (no stale result masks the failure).
- The readiness endpoint is called before a worker is ready → it reports that pool as not reachable
  within the bounded time rather than hanging.
- The frontend loads while the backend is starting up → it shows an "unknown/unavailable" state and
  recovers to the real status once the backend responds.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST expose an aggregate readiness endpoint that returns an aggregate health verdict
  for the whole service.
- **FR-002**: The readiness verdict MUST be "healthy" only when every checked subsystem is healthy, and
  MUST be "not healthy" if any checked subsystem fails. The aggregate endpoint MUST return HTTP 200 when
  the verdict is healthy and HTTP 503 when not-healthy, and MUST always include the per-subsystem
  breakdown in the response body.
- **FR-003**: The readiness check MUST verify connectivity to the persistent data store through the
  application's own data layer using a trivial connectivity probe (e.g., `SELECT 1`) and include that
  result in the breakdown.
- **FR-004**: The readiness check MUST perform shallow, cheap, bounded per-path connectivity checks
  only — message broker reachability and a control/liveness ping to a worker on EACH
  background-processing pool — and MUST include a per-path result. It MUST NOT enqueue or await a
  background job. There is no result-backend subsystem to check (background tasks run with results
  disabled).
- **FR-005**: The readiness response MUST include a per-subsystem breakdown that identifies which
  subsystem(s) failed (data store, message broker, each background-processing pool) when the overall
  verdict is "not healthy".
- **FR-006**: Each readiness check MUST be time-bounded so the endpoint returns a verdict within a
  defined limit even when a dependency is unreachable or slow (no indefinite hang).
- **FR-007**: System MUST provide a single documented command that brings up every service required for
  this slice in a local environment, with each service reporting a healthy state.
- **FR-008**: At least one schema migration MUST exist and MUST be applied when the system is brought
  up, after which the data store MUST be reachable through the application's data layer.
- **FR-009**: A separate on-demand smoke check MUST enqueue a trivial no-op task — defined in the
  system's own codebase — on EACH background-processing pool, as a real task on the real broker reaching
  a real worker (no mock or stub). On execution the task MUST write a completion record keyed to that
  specific invocation into a migration-managed table using the workers' synchronous data engine. The
  check MUST observe completion by reading that record through the asynchronous data layer within a
  bounded timeout; success means the invocation's record appears within the limit. This proves
  queue→pool routing and the dual-engine (sync-write / async-read) seam end-to-end. It is exercised
  primarily as a CI/deploy smoke test and is runnable on demand.
- **FR-010**: The frontend MUST load and display the system's current health as reported by the
  readiness endpoint, including the per-subsystem breakdown.
- **FR-011**: The frontend MUST reflect a non-healthy verdict when the endpoint reports one, and an
  "unavailable/unknown" state when the endpoint cannot be reached.
- **FR-012**: An automated test MUST exercise the readiness path end-to-end against ephemeral,
  containerized dependencies, covering both the healthy verdict and at least one failure condition.
- **FR-013**: The lint, formatting, and type-checking quality gate MUST pass for this slice, both
  locally and in CI.
- **FR-014**: The aggregate readiness endpoint MUST NOT block on or await a background job result, and
  MUST return promptly even when a worker pool is unreachable. The API's ability to serve requests MUST
  NOT depend on worker job execution, and the narrow Kubernetes liveness and readiness probes (FR-018,
  FR-020) MUST remain healthy when only worker pools are down.
- **FR-015**: The on-demand round-trip smoke check (FR-009) MUST be distinct from the readiness endpoint
  (FR-001) and MUST NOT be invoked on every readiness call.
- **FR-016**: The system MUST initialize structured logging, distributed tracing, and error reporting at
  startup for both the API and the background workers.
- **FR-017**: Automated tests MUST assert minimal telemetry emission — a structured startup log line is
  emitted, a trace span is recorded for a readiness request, and the error-reporting client is
  initialized — verified in-process without depending on external telemetry backends. Telemetry is not a
  readiness-checked subsystem.
- **FR-018**: The system MUST expose a narrow Kubernetes **liveness** probe that reflects only the API
  process (not the data store, not worker pools). Because its failure signals the pod should be
  restarted, it MUST NOT fail due to data-store or worker-pool outages, and MUST return HTTP 2xx
  whenever the API process is alive. It MUST be distinct from the aggregate readiness endpoint (FR-001).
- **FR-019**: Background tasks MUST run with results disabled (no result backend is configured). Task
  completion MUST be observed only via the persisted completion record (FR-009), never via a task result
  backend.
- **FR-020**: The system MUST expose a narrow Kubernetes **readiness** probe that reflects the API
  process plus the data-store connectivity it needs to serve requests. Because its failure signals the
  pod should be removed from traffic (depooled) without a restart, it MUST return HTTP 503 when the data
  store is unreachable and HTTP 2xx otherwise. It MUST NOT be gated on worker-pool reachability and MUST
  be distinct from the aggregate readiness endpoint (FR-001). Implementing both probe endpoints (FR-018,
  FR-020) AND wiring them into the Kubernetes manifests (livenessProbe → `/livez`, readinessProbe →
  `/readyz`) are in scope for this slice.

### Key Entities *(include if feature involves data)*

- **Readiness Report**: the aggregate result returned by the endpoint — an overall verdict, a timestamp,
  and a collection of subsystem check results.
- **Subsystem Check Result**: a single check within the report — the subsystem identifier (data store,
  message broker, or a specific background-processing pool), its pass/fail status, and optional detail
  (e.g., elapsed time or failure reason).
- **Background Liveness Task**: a trivial no-op task defined in the system's own codebase, dispatched by
  the on-demand smoke check (FR-009) — one invocation per background-processing pool — as a real task on
  the real broker. On execution it writes a Completion Record via the workers' synchronous engine. It is
  not used by the readiness endpoint.
- **Completion Record**: a row in a migration-managed table keyed to a specific smoke-check invocation,
  written by the worker (synchronous engine) and read back by the check (asynchronous data layer) to
  confirm end-to-end routing.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a clean checkout, a developer can bring the entire system up with one documented
  command and observe every service healthy within 5 minutes, with no manual steps beyond that command.
- **SC-002**: The readiness verdict is "healthy" only when every shallow subsystem check passes (data
  store, message broker, each pool's worker ping) — across the test suite there are zero false-healthy
  results.
- **SC-003**: When any single subsystem is taken down, the readiness verdict is "not healthy" and
  correctly identifies the failed subsystem in 100% of tested cases.
- **SC-004**: The readiness endpoint returns a verdict within 5 seconds even when a dependency is
  failing, in 100% of tested cases, and never blocks on a background job result.
- **SC-005**: Under normal conditions the readiness endpoint responds in under 1 second, performing only
  shallow connectivity checks.
- **SC-006**: A developer can determine overall system health by loading the frontend alone — without
  any API tooling — within 30 seconds of the page loading.
- **SC-007**: The on-demand round-trip smoke check completes a no-op job on each background-processing
  pool within 10 seconds under normal local conditions.
- **SC-008**: The end-to-end readiness test passes against ephemeral containerized dependencies, and the
  lint/format/type gate passes, both locally and in CI — the slice is 100% green in both environments.
- **SC-009**: Telemetry verification passes in 100% of runs locally and in CI — tests confirm a
  structured startup log line, a trace span on the readiness request, and error-reporting initialization.
- **SC-010**: The aggregate endpoint returns HTTP 503 when unhealthy and HTTP 200 when healthy in 100% of
  tested cases; the narrow liveness probe stays HTTP 2xx whenever the API process is alive (even if the
  data store or all workers are down); and the narrow readiness probe returns HTTP 503 when the data store
  is unreachable and HTTP 2xx otherwise.
- **SC-011**: The Kubernetes Deployment/Service manifests validate cleanly in CI (schema/dry-run check)
  and wire `/livez`→livenessProbe and `/readyz`→readinessProbe, with neither probe gated on workers.

## Assumptions

- "One documented command" is the project's documented orchestration entrypoint for local bring-up; the
  specific command is defined by the operating manual and confirmed during planning.
- The "background-processing paths the architecture defines" are the two paths already fixed by the
  project: a compute-oriented pool and an I/O-oriented pool. "Each path/pool" means both must be proven,
  and each pool exposes a worker reachable via a control/liveness ping.
- The readiness endpoint performs only shallow, bounded connectivity checks and never enqueues or awaits
  a background job; the full end-to-end queue→pool routing proof is the separate on-demand smoke check
  (see Clarifications, Session 2026-06-19).
- Ephemeral, containerized dependencies for the test suite are provisioned per the project's testing
  approach; tests do not depend on the local orchestration stack or any shared/staging environment.
- Authentication and authorization are out of scope for this slice; the readiness endpoint is
  developer-facing and unauthenticated.
- The frontend liveness view is intentionally minimal: legible status display only, with no styling,
  navigation, or UX requirements beyond showing the verdict and breakdown. Display-on-load is required;
  automatic polling/refresh is optional.
- "Healthy" at bring-up means each service passes its own start-up/health signal, not that it has
  processed real traffic.
- The telemetry stack is wired and emitting from day one (constitution Principle I); in tests it is
  verified in-process (captured logs, an in-memory span exporter, an initialized error-reporting client)
  without requiring external telemetry backends.

## Out of Scope

- Any real notification functionality or channels (Email / SMS / Push).
- Authentication and authorization flows.
- The analytics / chart (usage-aggregation) feature.
- Any business logic beyond proving liveness of the wired-together subsystems.
