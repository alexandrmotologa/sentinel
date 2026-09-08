# Sentinel

[![CI](https://github.com/alexandrmotologa/sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/alexandrmotologa/sentinel/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Sentinel is an asynchronous uptime and API health monitoring daemon written in Python 3.12. It monitors multiple endpoints concurrently, validates status codes, latency thresholds, text presence, JSON payload assertions, and SSL certificate expiration, and sends Telegram and generic webhook alerts with flap protection.

## Features

- Non-blocking asynchronous checks powered by `httpx` and `asyncio`
- Flap protection with configurable failure debounce thresholds
- Downtime tracking and recovery notifications with elapsed outage duration
- Health assertion rules: HTTP status code ranges, max latency, regex, text, and nested JSON keys
- SSL certificate expiration warning
- Multi-channel alerting: Formatted Telegram alerts and generic HTTP webhooks (Slack, Discord, PagerDuty)
- One-off target probing with `sentinel probe` and optional JSON output
- Docker and docker-compose deployment with non-root user and container healthchecks

## Quick Start

### Installation

```bash
pip install sentinel
```

Or install from source:

```bash
git clone https://github.com/alexandrmotologa/sentinel.git
cd sentinel
pip install -e .
```

### Running Sentinel

1. Copy the example configuration:

```bash
cp sites.example.yaml sites.yaml
```

2. Validate your configuration:

```bash
sentinel check-config sites.yaml
```

3. Run an immediate one-off health probe across all targets:

```bash
sentinel probe sites.yaml
```

Or export results as JSON:

```bash
sentinel probe sites.yaml --json
```

4. Send a test alert to verify notification channels:

```bash
sentinel test-alert --config sites.yaml
```

5. Start the 24/7 monitoring daemon:

```bash
sentinel run sites.yaml
```

## Documentation

- [Architecture Guide](docs/architecture.md): Concurrency model, state transitions, and debounce logic.
- [Configuration Reference](docs/configuration.md): Full syntax and options for `sites.yaml`.
- [Alerting Guide](docs/alerting.md): Telegram templates, sound rules, and notification triggers.
- [Deployment Guide](docs/deployment.md): Running under Docker, systemd, or background processes.

## License

MIT License. See LICENSE for details.
