# Sentinel

Sentinel is an asynchronous uptime and API health monitoring daemon written in Python 3.12. It monitors multiple endpoints concurrently, validates status codes, latency thresholds, text presence, JSON payload assertions, and SSL certificate expiration, and sends Telegram alerts with flap protection.

## Features

- Non-blocking asynchronous checks powered by `httpx` and `asyncio`
- Flap protection with configurable failure debounce thresholds
- Downtime tracking and recovery notifications with elapsed outage duration
- Health assertion rules: HTTP status code ranges, max latency, regex, text, and nested JSON keys
- SSL certificate expiration warning
- Formatted Telegram alerts with HTML styling and retry handling
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

3. Send a test Telegram alert:

```bash
sentinel test-alert --config sites.yaml
```

4. Start the monitoring daemon:

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
