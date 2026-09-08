# Discord and Slack Alert Channels

Sentinel delivers notifications directly to Discord channels via rich embeds and Slack workspaces using Block Kit formatting.

## Discord Webhook Setup

### 1. Create a Webhook in Discord

1. Open channel settings in your Discord server.
2. Select **Integrations**, then click **Webhooks**.
3. Click **New Webhook**, name it Sentinel, and copy the Webhook URL.

### 2. Configure Sentinel

Add the Discord configuration to `sites.yaml`:

```yaml
discord:
  webhook_url: "env:DISCORD_WEBHOOK_URL"
  username: "Sentinel"
  avatar_url: "https://raw.githubusercontent.com/alexandrmotologa/sentinel/main/docs/avatar.png"
  enabled: true
```

Set the environment variable:

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN"
```

### Discord Outage and Recovery Alerts

Discord alerts use styled embed cards:
- Red embed (`#E74C3C`) for outages, showing endpoint URL, failure reason, HTTP status, and latency.
- Green embed (`#2ECC71`) for recovery, including total downtime duration and current latency.

---

## Slack Incoming Webhook Setup

### 1. Create an Incoming Webhook in Slack

1. Visit the Slack API portal and select or create your application.
2. Enable **Incoming Webhooks**.
3. Click **Add New Webhook to Workspace** and pick the destination channel.
4. Copy the Webhook URL.

### 2. Configure Sentinel

Add the Slack section to `sites.yaml`:

```yaml
slack:
  webhook_url: "env:SLACK_WEBHOOK_URL"
  enabled: true
```

Set the environment variable:

```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T000/B000/XXXX"
```

### Slack Outage and Recovery Alerts

Slack alerts use structured Block Kit layouts:
- Header block with service status indicators.
- Two-column fields displaying URL, error details, consecutive failures, and timestamps.
- Daily summary blocks listing all services with current uptime percentages and average latency.

---

## Testing Notification Channels

Test all configured alerting channels at once with the CLI command:

```bash
sentinel test-alert sites.yaml
```
