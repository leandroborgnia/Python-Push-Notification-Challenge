# Contract: Smoke-Check CLI

The on-demand, deep round-trip check (spec FR-009/FR-015). Separate from the readiness endpoint and
never triggered by a readiness call. Primarily a CI/deploy smoke test; runnable on demand.

## Invocation

```bash
# module form (CI/deploy and ad-hoc)
uv run python -m app.cli.smoke

# console-script form (defined in pyproject)
uv run smoke-check
```

Optional flags (defaults from settings):
- `--timeout <seconds>` — overall bound for completion (default `smoke_timeout_s`, spec default 10s).

## Behavior

1. Generate a `correlation_id` (UUID4) for this invocation.
2. Dispatch the `liveness_ping(correlation_id, pool_label)` task once per pool:
   `apply_async(queue="cpu")` and `apply_async(queue="io")` — real tasks on the real broker.
3. Each worker (prefork `cpu`, threads `io`) executes the no-op task and writes a `liveness_completion`
   row `(correlation_id, pool_label, created_at)` via the **synchronous (psycopg v3)** engine.
4. The CLI polls via the **async (asyncpg)** reader (`both_completed(correlation_id)`) using
   `asyncio.wait_for(..., timeout)`.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Both pool completion rows (`cpu` and `io`) appeared within the timeout — queue→pool routing and the dual-engine seam are proven end-to-end. |
| `1` | Timeout or failure — at least one pool's row did not appear in time. stderr names which pool(s) are missing. |

## Output (stdout, structured)

- On success: a structured log line per pool completion + a final `smoke-check: ok` summary with the
  `correlation_id` and elapsed time per pool.
- On failure: a structured error identifying missing pool(s) and the elapsed time; non-zero exit.

## Notes

- No result backend is used (`ignore_result=True`); completion is observed **only** via the persisted
  record. (FR-019)
- In tests this same use case is driven directly against a real RabbitMQ + in-test `cpu`/`io` workers;
  cleanup is by truncation (cross-process writes are not covered by transaction rollback).
