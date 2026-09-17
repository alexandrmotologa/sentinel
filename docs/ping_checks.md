# ICMP Network Ping Checks

Sentinel includes cross-platform ICMP Ping probes for bare-metal servers, edge routers, switches, gateways, and network appliances without requiring root privileges or raw sockets.

## Overview

Unlike HTTP and TCP targets that connect to application-layer and transport-layer ports, Ping targets verify IP-level reachability, packet loss, and round-trip transmission latency (RTT) using standard operating system utilities (`ping`).

Common use cases for ICMP Ping checks:
- Edge gateway routers and switches
- VPN tunnels and inter-datacenter links
- DNS anycast infrastructure
- Bare-metal hosts without public HTTP/TCP services

## Configuration

Define ICMP ping targets under `ping_targets` in `sites.yaml`:

```yaml
ping_targets:
  - name: "Edge Gateway Router"
    host: "192.168.1.1"
    count: 3                         # Packets per check (1-10)
    interval: 30s                    # Check interval
    timeout: 2s                      # Timeout per attempt
    expect:
      max_latency_ms: 25             # Fail if avg latency > 25ms
      max_packet_loss_percent: 0     # Fail if packet loss > 0%
    notify: ["telegram", "slack"]    # Alert channels
    severity: "warning"              # Severity level

  - name: "Cloudflare Anycast IP"
    host: "1.1.1.1"
    count: 4
    interval: 60s
    expect:
      max_latency_ms: 100
```

### Parameter Reference

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | Required | Unique identifier for the ping target |
| `host` | string | Required | Target hostname or IPv4/IPv6 address |
| `count` | integer | `1` | Number of ICMP packets transmitted per probe cycle (1–10) |
| `interval` | string / float | `60s` | Time between probe executions |
| `timeout` | string / float | `5s` | Timeout for the ping subprocess execution |
| `expect.max_latency_ms` | float | `None` | Maximum allowed average round-trip latency (ms) |
| `expect.max_packet_loss_percent` | float | `None` | Maximum allowable packet loss percentage (0–100) |
| `notify` | list[string] | `[]` | Channels to alert (`telegram`, `webhook`, `discord`, `slack`). Empty means all. |
| `severity` | string | `critical` | Alert severity badge: `critical`, `warning`, or `info` |

## Cross-Platform Engine

Sentinel executes OS-level subprocess ping calls asynchronously without root privileges:
- **Windows**: `ping -n {count} -w {timeout_ms} {host}`
- **Linux**: `ping -c {count} -W {timeout_s} {host}`
- **macOS (Darwin)**: `ping -c {count} -W {timeout_ms} {host}`

Output parsing extracts packets transmitted, packets received, packet loss percentage, and round-trip minimum/average/maximum latency via regular expressions.

## CLI Probing

Test ping targets immediately from the terminal:

```bash
# Human-readable Rich table
sentinel probe sites.yaml

# JSON output
sentinel probe sites.yaml --json
```
