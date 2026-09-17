# Maintenance Windows & Dynamic Alert Mutes

Sentinel provides scheduled and dynamic alert suppression mechanisms to prevent alert fatigue during planned server maintenance, database vacuuming, cluster reboots, and rolling software deployments.

## Scheduled Maintenance Windows

Scheduled maintenance windows are defined directly in your YAML configuration file under `maintenance`:

```yaml
maintenance:
  # Daily recurring window (UTC)
  - name: "database-backup"
    targets: ["Primary PostgreSQL", "Redis Cache"]
    schedule: "daily 02:00-04:00 UTC"
    reason: "Nightly automated snapshot and vacuum"

  # Weekly recurring window on specific day
  - name: "weekend-cluster-reboot"
    targets: ["*"]                   # Wildcard matches all targets
    schedule: "weekly sun 01:00-03:00 UTC"
    reason: "Kernel patching and node recycling"

  # One-off scheduled maintenance range
  - name: "datacenter-migration"
    targets: ["api-gateway"]
    schedule: "2026-10-01T12:00:00Z/2026-10-01T16:00:00Z"
    reason: "Datacenter migration to Frankfurt"
```

### Supported Schedule Expressions

- `daily HH:MM-HH:MM [UTC]` (e.g. `daily 02:00-03:30`)
- `weekly [day] HH:MM-HH:MM [UTC]` (e.g. `weekly sun 01:00-03:00`, `saturdays 23:00-01:00`)
- `YYYY-MM-DDTHH:MM:SSZ/YYYY-MM-DDTHH:MM:SSZ` (ISO 8601 interval)
- `YYYY-MM-DD HH:MM to YYYY-MM-DD HH:MM`

When a target is under maintenance, health probes continue executing normally (logging status and collecting metrics), but **all outage and recovery notifications are suppressed**. On the Web Status Page, an amber `MAINTENANCE` badge and banner are shown.

---

## Dynamic CLI Muting

For ad-hoc deployments and incident triaging, you can mute targets on the fly without editing configuration files or restarting the daemon.

### Mute a Target

Temporarily silence alerts for a target by specifying the duration in minutes:

```bash
# Mute a specific target for 45 minutes
sentinel mute "Primary PostgreSQL" --duration 45 --reason "Emergency schema migration"

# Short form flags (-d for duration, -r for reason)
sentinel mute "Production API" -d 60 -r "Deploying v2.4.0 release"
```

### List Active Mutes

Inspect all currently active maintenance mutes, expiration timestamps, and reasons:

```bash
sentinel mutes
```

Output:
```text
               Active Maintenance Mutes
┌──────────────────┬─────────────────────────┬────────────────────────────┐
│ Target Name      │ Expires At              │ Reason                     │
├──────────────────┼─────────────────────────┼────────────────────────────┤
│ Production API   │ 2026-09-17 19:30:00 UTC │ Deploying v2.4.0 release   │
└──────────────────┴─────────────────────────┴────────────────────────────┘
```

### Unmute a Target

Restore alert notifications immediately once work is complete:

```bash
sentinel unmute "Production API"
```

Dynamic mutes are persisted in `sentinel_mutes.json` (or `~/.sentinel/mutes.json`) so they survive daemon reloads and restarts, and are automatically pruned upon expiration.
