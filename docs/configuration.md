# Configuration reference

Sentinel reads target definitions, checking schedules, and alert credentials from a single YAML file (`sites.yaml` by default).

## Top-level structure

```yaml
global:
  default_interval: 60s
  default_timeout: 10s
  consecutive_failures_to_alert: 2
  daily_summary_time: "09:00"

telegram:
  bot_token: "123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
  chat_id: "-1001234567890"
  send_silently: false
  enabled: true

targets:
  - name: "API Service"
    url: "https://api.example.com/health"
    interval: 30s
    timeout: 5s
    method: "GET"
    headers:
      Authorization: "Bearer env:API_SECRET"
    expect:
      status_code: 200
      max_latency_ms: 1000
      json:
        status: "ok"
```

## Duration syntax

Time values accept numeric seconds or human-readable duration strings:

| Unit | Example | Value in seconds |
|---|---|---|
| Milliseconds | `500ms` | 0.5s |
| Seconds | `30s` or `30` | 30.0s |
| Minutes | `2m` | 120.0s |
| Hours | `1h` | 3600.0s |
| Days | `1d` | 86400.0s |

## Environment variable resolution

Configuration values can reference environment variables using two formats:

1. `env:VARIABLE_NAME`: Look up `VARIABLE_NAME` in the system environment.
2. `${VARIABLE_NAME:-default_value}`: Standard shell placeholder syntax with optional fallback values.

Example:

```yaml
telegram:
  bot_token: "env:TELEGRAM_BOT_TOKEN"
  chat_id: "${TELEGRAM_CHAT_ID:-123456789}"
```

## Global settings

The `global` section defines defaults applied across all targets:

- `default_interval`: Interval between checks for targets that do not define their own. Default is `60s`.
- `default_timeout`: Network request timeout for targets that do not specify one. Default is `10s`.
- `consecutive_failures_to_alert`: Number of sequential failed checks required before triggering an outage alert. Default is `2`.
- `daily_summary_time`: Optional time in 24-hour UTC format (`HH:MM`) to send a daily report.

## Telegram settings

The `telegram` section controls alert delivery:

- `bot_token`: Telegram Bot API token obtained from @BotFather.
- `chat_id`: Numeric identifier for the target user, group, or channel.
- `send_silently`: When set to true, disables sound notifications for recovery messages.
- `enabled`: Enables or disables Telegram notifications globally.

## Target definitions

Each entry in `targets` configures an endpoint check:

- `name`: Human-readable label displayed in alerts and logs.
- `url`: Full target URL including scheme and path.
- `interval`: Check interval for this target. Overrides `default_interval`.
- `timeout`: Request timeout in seconds. Overrides `default_timeout`.
- `method`: HTTP method. Defaults to `GET`. Supports `POST`, `PUT`, `PATCH`, `DELETE`, and `HEAD`.
- `headers`: Map of custom HTTP headers sent with the request.
- `body`: Raw string payload for requests with bodies.
- `follow_redirects`: Boolean indicating whether to follow 3xx redirects. Defaults to `true`.
- `expect`: Assertion rules required for the check to pass.

## Health expectations

The `expect` block defines the criteria evaluated on each check:

### Status code rules

Matches exact codes, lists, or ranges:

```yaml
expect:
  status_code: 200              # Exact match
```

```yaml
expect:
  status_code: [200, 201, 204]  # List match
```

```yaml
expect:
  status_code: "200-299"        # Numeric range
```

### Latency limits

Flags slow responses that exceed latency thresholds:

```yaml
expect:
  max_latency_ms: 1500          # Fails if latency exceeds 1500 ms
```

### Text and regex matching

Searches the response body:

```yaml
expect:
  contains_text: "System Operational"
  regex: "Version: [0-9]+\\.[0-9]+"
```

### JSON path assertions

Validates fields within JSON response payloads:

```yaml
expect:
  json:
    status: "ok"
    services.database: "connected"
```

### SSL certificate expiration

Warns when HTTPS certificates approach expiration:

```yaml
expect:
  ssl_check: true
  ssl_warn_days: 14             # Warns if expiration is within 14 days
```
