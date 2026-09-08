# Architecture

Sentinel monitors multiple HTTP endpoints concurrently using Python's standard `asyncio` loop and `httpx.AsyncClient`. It is designed as a standalone daemon that runs continuously on minimal system resources.

## Concurrency model

When the engine starts, it spawns an independent task for each target defined in `sites.yaml`. Each task runs in an isolated loop:

1. Evaluates target health against configured expectations.
2. Updates in-memory state and calculates debouncing rules.
3. Dispatches notifications when an outage or recovery condition triggers.
4. Updates a local heartbeat file.
5. Sleeps for the target interval before repeating.

Because each target runs in its own task, a slow or unresponsive endpoint does not delay checks for other services. Request connections reuse connection pools through `httpx.AsyncClient` with HTTP/2 support.

## State transitions and flap protection

Transient network blips often trigger false alarms in naive monitoring tools. Sentinel prevents alert storms through configurable failure debouncing.

Each target maintains an in-memory `TargetState` object tracking:

- Operational status (`UP`, `DOWN`, or `UNKNOWN`).
- Current consecutive failure count.
- Downtime start timestamp (`down_since`).
- Outage alert dispatch status (`alert_sent`).
- Total check count and success count for uptime percentages.

### Outage alert trigger

An outage notification is sent only when `consecutive_failures` reaches `consecutive_failures_to_alert`. Subsequent consecutive failures keep the status as `DOWN` without re-sending notifications. This suppresses alert spam during extended downtime.

### Recovery alert trigger

When a failing target passes a health check:

1. Sentinel checks if an outage alert was sent (`alert_sent == True`).
2. If an outage alert was sent, Sentinel computes the total outage duration (`now - down_since`), formats it into plain text, and dispatches a recovery message.
3. If the failure count was below the debounce threshold, no outage alert had been sent, so no recovery notification is dispatched.
4. The failure counter resets to zero, and the status returns to `UP`.

## Health evaluation pipeline

The evaluator runs each check in a single pass:

1. Measures round-trip latency with `time.perf_counter()`.
2. Validates the HTTP status code against exact codes, code lists, or numeric ranges.
3. Checks whether response latency falls within `max_latency_ms`.
4. Searches the response body for required text or regex matches.
5. Parses JSON responses and verifies exact values across nested keys or dot-notation paths.
6. Probes TLS certificate validity for HTTPS endpoints when `ssl_check` is enabled.

A target passes only when every configured rule succeeds. If any rule fails, the evaluator returns a structured `CheckResult` with the failure reason.
