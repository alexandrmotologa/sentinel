# Telegram alerting

Sentinel formats notifications using Telegram's HTML parse mode. All dynamic values such as URLs, target names, and error reasons are escaped to prevent formatting errors.

## Message formats

### Outage alert

Sentinel dispatches an outage alert when a target's consecutive failure count reaches `consecutive_failures_to_alert`:

```html
🚨 <b>SERVICE DOWN: Production API Health</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>URL:</b> <code>https://api.example.com/health</code>
<b>Reason:</b> ❌ Expected JSON {"database": "connected"}, got {"database": "timeout"}
<b>HTTP Status:</b> 503 Service Unavailable
<b>Response Latency:</b> 2,410 ms
<b>Consecutive Failures:</b> 2 / 2
<b>Timestamp:</b> 2026-09-09 00:35:12 UTC
```

### Recovery alert

When a service recovers after an outage alert, Sentinel calculates the total downtime and dispatches a recovery notification:

```html
✅ <b>SERVICE RECOVERED: Production API Health</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>URL:</b> <code>https://api.example.com/health</code>
<b>Downtime Duration:</b> 4 minutes, 15 seconds
<b>Current Status:</b> 200 OK
<b>Current Latency:</b> 185 ms
<b>Timestamp:</b> 2026-09-09 00:39:27 UTC
```

If `send_silently` is set to true in configuration, recovery messages arrive without sound notifications.

### Test alert

Run `sentinel test-alert` to verify Telegram bot tokens and chat IDs:

```html
🔍 <b>SENTINEL TEST ALERT</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>Status:</b> ✅ Monitoring daemon alert delivery verified
<b>Timestamp:</b> 2026-09-09 00:30:00 UTC
```

### Daily summary

When `daily_summary_time` is configured under `global`, Sentinel sends a status breakdown at that UTC time each day:

```html
📊 <b>SENTINEL DAILY SUMMARY</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>Monitored Services:</b> 3
<b>Healthy Services:</b> 3
<b>Average Uptime:</b> 99.85%
<b>Timestamp:</b> 2026-09-09 09:00:00 UTC

🟢 <b>Production API</b>: 99.9% uptime (142 ms)
🟢 <b>Landing Page</b>: 100.0% uptime (85 ms)
🟢 <b>Stripe Webhook</b>: 99.7% uptime (210 ms)
```

## Reliability and retries

Network failures or Telegram rate limits (HTTP 429) do not stop the monitoring loop. Sentinel uses exponential backoff up to three attempts per message before logging a warning and continuing checks.
