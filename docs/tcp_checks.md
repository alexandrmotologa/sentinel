# Direct TCP Socket Checks

Sentinel supports low-level TCP socket health checks for databases, cache clusters, message brokers, and internal microservices.

## Overview

Unlike HTTP targets that evaluate request headers, response bodies, and TLS certificates, TCP targets verify network-level socket handshake availability and measure socket connection latency.

Common services suited for TCP checks include:
- PostgreSQL (port 5432)
- MySQL / MariaDB (port 3306)
- Redis / KeyDB (port 6379)
- RabbitMQ (port 5672)
- Elasticsearch / OpenSearch (port 9200)

## Configuration

Define TCP targets under `tcp_targets` in `sites.yaml`:

```yaml
tcp_targets:
  - name: "Production PostgreSQL"
    host: "db-primary.internal"
    port: 5432
    interval: 15s
    timeout: 3s

  - name: "Redis In-Memory Cache"
    host: "10.0.1.20"
    port: 6379
    interval: 10s
    timeout: 2s
```

### Parameter Reference

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | Required | Unique identifier for the service |
| `host` | string | Required | Hostname or IP address to connect to |
| `port` | integer | Required | Destination TCP port number |
| `interval` | string / float | 60s | Time between consecutive connection attempts |
| `timeout` | string / float | 5s | Socket connection timeout before failing |

## CLI Probing

You can test TCP targets manually without starting the continuous background daemon:

```bash
# Formatted terminal table output
sentinel probe sites.yaml

# Machine-readable JSON output for automated pipelines
sentinel probe sites.yaml --json
```

## Failure Detection and Alerting

When a TCP handshake fails (connection refused, network route unreachable, or handshake timeout), Sentinel records the failure and increments the failure counter. Once failures reach the configured debounce threshold, an outage notification is dispatched across all active notification channels.
