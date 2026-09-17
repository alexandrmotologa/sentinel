# Metrics and Health Endpoints

Sentinel includes an embedded asynchronous HTTP server that exposes Prometheus metrics, JSON health checks, and a zero-dependency web status page without external web framework dependencies.

## Configuration

Enable the metrics server in `sites.yaml`:

```yaml
metrics:
  enabled: true
  host: "0.0.0.0"
  port: 9090
```

When enabled, Sentinel starts listening as soon as the daemon starts.

## Web Status Page (`/` and `/status`)

The embedded metrics server serves a self-contained, responsive dark-mode HTML dashboard at both `/` and `/status`.

### Features
- **Zero external dependencies**: Built purely with vanilla HTML5, modern CSS, and JavaScript. No npm packages or CDNs required.
- **Real-time target status pills**: Color-coded indicators (`UP` in green, `DOWN` in red, `UNKNOWN` in muted gray).
- **24-hour uptime ratio bars**: Visual representation of target availability and SLA ratios.
- **Latency badges**: Sub-100ms displayed in emerald, sub-300ms in yellow/amber, and slow queries in red.
- **Live client polling**: Asynchronously polls `/healthz` every 5 seconds to update target statuses, latencies, and uptime ratios in real-time without reloading the page.
- **Network status & error tracking**: Displays last error messages and outage details when a service fails.

Access it directly in your browser or test it via cURL:

```bash
curl -i http://localhost:9090/status
```

## Prometheus Metrics (`/metrics`)

The `/metrics` endpoint exports standard Prometheus text exposition format (version 0.0.4).

### Available Metrics

| Metric Name | Type | Description |
|---|---|---|
| `sentinel_target_up` | Gauge | Operational status per target (1 = UP, 0 = DOWN) |
| `sentinel_target_latency_seconds` | Gauge | Most recent round-trip latency in seconds |
| `sentinel_target_consecutive_failures` | Gauge | Current count of consecutive failed checks |
| `sentinel_target_uptime_ratio` | Gauge | Overall uptime ratio between 0.0 and 1.0 |
| `sentinel_checks_total` | Counter | Cumulative check iterations performed |

### Prometheus Scrape Configuration

Add Sentinel to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "sentinel"
    scrape_interval: 15s
    static_configs:
      - targets: ["localhost:9090"]
```

### Sample Output

```text
# HELP sentinel_target_up Target operational status (1 = UP, 0 = DOWN)
# TYPE sentinel_target_up gauge
sentinel_target_up{target="Production API Health"} 1
sentinel_target_up{target="Primary PostgreSQL"} 1

# HELP sentinel_target_latency_seconds Round-trip latency in seconds
# TYPE sentinel_target_latency_seconds gauge
sentinel_target_latency_seconds{target="Production API Health"} 0.042180
sentinel_target_latency_seconds{target="Primary PostgreSQL"} 0.003120

# HELP sentinel_target_consecutive_failures Number of consecutive failures
# TYPE sentinel_target_consecutive_failures gauge
sentinel_target_consecutive_failures{target="Production API Health"} 0

# HELP sentinel_target_uptime_ratio Target uptime ratio between 0.0 and 1.0
# TYPE sentinel_target_uptime_ratio gauge
sentinel_target_uptime_ratio{target="Production API Health"} 0.9995

# HELP sentinel_checks_total Total checks performed on target
# TYPE sentinel_checks_total counter
sentinel_checks_total{target="Production API Health"} 1420
```

## Healthz Endpoint (`/healthz`)

The `/healthz` endpoint returns a machine-readable JSON status report.

- Returns HTTP 200 when all monitored targets are operational.
- Returns HTTP 503 when one or more targets are in degraded or down state.

### Sample Response

```json
{
  "status": "healthy",
  "timestamp": "2026-09-09T01:00:00Z",
  "total_targets": 2,
  "healthy_targets": 2,
  "targets": {
    "Production API Health": {
      "url": "https://api.example.com/health",
      "status": "UP",
      "latency_ms": 42.18,
      "uptime_percentage": 99.95,
      "consecutive_failures": 0,
      "last_error": null
    },
    "Primary PostgreSQL": {
      "url": "tcp://db.internal.example.com:5432",
      "status": "UP",
      "latency_ms": 3.12,
      "uptime_percentage": 100.0,
      "consecutive_failures": 0,
      "last_error": null
    }
  }
}
```
