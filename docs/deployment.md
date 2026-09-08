# Deployment guide

Sentinel runs on virtual private servers, local systems, or container clusters. Its low resource footprint allows it to operate alongside other lightweight workloads.

## Docker Compose

The standard deployment uses Docker Compose:

1. Copy the example configuration:

```bash
cp sites.example.yaml sites.yaml
```

2. Create a `.env` file for credentials:

```bash
TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
TELEGRAM_CHAT_ID="-1001234567890"
API_SECRET="your-production-secret"
```

3. Launch the container:

```bash
docker compose up -d
```

4. View logs:

```bash
docker compose logs -f
```

The container runs as an unprivileged user (UID 10001) and includes a health check probe that verifies the daemon's heartbeat file every 30 seconds.

## Docker manual execution

To run a standalone container without Compose:

```bash
docker build -t sentinel .
docker run -d \
  --name sentinel \
  --restart unless-stopped \
  -v $(pwd)/sites.yaml:/etc/sentinel/sites.yaml:ro \
  -e TELEGRAM_BOT_TOKEN="your_token" \
  -e TELEGRAM_CHAT_ID="your_chat_id" \
  sentinel
```

## Systemd service on Linux

To run Sentinel as a background system service on Debian, Ubuntu, or CentOS:

1. Install Python 3.12 and create a dedicated virtual environment:

```bash
sudo useradd -r -s /bin/false sentinel
sudo mkdir -p /opt/sentinel /etc/sentinel
cd /opt/sentinel
sudo python3.12 -m venv .venv
sudo .venv/bin/pip install --upgrade pip
sudo .venv/bin/pip install sentinel
```

2. Copy your configuration file:

```bash
sudo cp /path/to/sites.yaml /etc/sentinel/sites.yaml
sudo chown -R sentinel:sentinel /opt/sentinel /etc/sentinel
```

3. Create the systemd service file at `/etc/systemd/system/sentinel.service`:

```ini
[Unit]
Description=Sentinel Async Health Watcher
After=network.target

[Service]
Type=simple
User=sentinel
Group=sentinel
WorkingDirectory=/opt/sentinel
ExecStart=/opt/sentinel/.venv/bin/sentinel run /etc/sentinel/sites.yaml
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

4. Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable sentinel
sudo systemctl start sentinel
sudo systemctl status sentinel
```

5. Monitor service logs:

```bash
sudo journalctl -u sentinel -f
```
