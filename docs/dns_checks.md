# DNS Resolution and Propagation Probes

Sentinel provides built-in, native DNS resolution and propagation probes to monitor the health, latency, and correctness of domain records.

## Overview

Unlike HTTP probes that evaluate web server responses or TCP probes that test port handshakes, DNS probes query domain names directly using native Python non-blocking resolution routines (`asyncio.get_running_loop().getaddrinfo()`).

Common use cases include:
- Verifying domain resolution availability (`A` / `AAAA` records)
- Detecting DNS hijacking, cache poisoning, or unexpected IP changes
- Validating CDN canonical aliases (`CNAME` records)
- Monitoring primary and backup mail exchange routing (`MX` records)
- Tracking SPF, DKIM, or domain verification records (`TXT` records)
- Alerting on slow DNS response times or lookup latency spikes

## Configuration

Define DNS targets under `dns_targets` (or `dns`) in `sites.yaml`:

```yaml
dns_targets:
  - name: "Production API DNS (A)"
    host: "api.example.com"
    record_type: "A"
    interval: 30s
    timeout: 3s
    expect:
      expected_ips:
        - "93.184.216.34"
      max_latency_ms: 200

  - name: "CDN Canonical Alias"
    host: "assets.example.com"
    record_type: "CNAME"
    interval: 60s
    expect:
      expected_cname: "cdn.provider.net"

  - name: "Mail Server MX Routing"
    host: "example.com"
    record_type: "MX"
    interval: 120s
```

### Parameter Reference

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | Required | Unique identifier for the DNS target |
| `host` | string | Required | Domain name or hostname to query |
| `record_type` | string | `"A"` | Record type: `A`, `AAAA`, `CNAME`, `MX`, or `TXT` |
| `interval` | string / float | 60s | Time between consecutive resolution checks |
| `timeout` | string / float | 5s | Maximum lookup duration before timing out (min 0.5s) |
| `expect` | object | Optional | Assertion criteria for resolution results |

### Expectation Assertions (`expect`)

| Field | Type | Description |
|---|---|---|
| `expected_ips` | list of strings | List of IP addresses that must be present in the resolution result (for `A` or `AAAA`) |
| `expected_cname` | string | Target canonical domain that the CNAME alias must point to |
| `max_latency_ms` | float | Maximum acceptable round-trip query time in milliseconds |

## CLI Probing

You can run immediate DNS checks from your terminal without launching the background daemon:

```bash
# Formatted terminal table output
sentinel probe sites.yaml

# Machine-readable JSON output
sentinel probe sites.yaml --json
```

## Failure Detection and Alerting

When a DNS query fails (NXDOMAIN / `gaierror`, resolution timeout, missing expected IP address, or latency exceeding `max_latency_ms`), Sentinel increments the target's failure counter. Once the debounce threshold (`consecutive_failures_to_alert`) is reached, an alert is dispatched across all enabled notification channels.
