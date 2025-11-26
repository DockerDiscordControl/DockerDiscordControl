# Status Watchdog

The **Status Watchdog** is DDC's monitoring feature that alerts you when the bot goes offline. It implements a "Dead Man's Switch" pattern - if DDC stops running, an external monitoring service detects the missing heartbeat and sends you an alert.

## How It Works

```
┌─────────────┐     HTTPS Ping      ┌──────────────────┐
│    DDC      │ ──────────────────► │ Monitoring       │
│   (Bot)     │   every X minutes   │ Service          │
└─────────────┘                     │ (Healthchecks.io)│
                                    └────────┬─────────┘
                                             │
                                    If ping stops...
                                             │
                                             ▼
                                    ┌──────────────────┐
                                    │  Alert sent via  │
                                    │  Email / Discord │
                                    │  / SMS / etc.    │
                                    └──────────────────┘
```

1. DDC periodically sends an HTTPS ping to a monitoring URL
2. The monitoring service expects pings at regular intervals
3. If no ping arrives within the timeout period, the service sends an alert
4. When DDC comes back online, pings resume automatically

## Why This Approach?

### Security Benefits

| Traditional Approach | Status Watchdog |
|---------------------|-----------------|
| External script needs bot token | No tokens shared |
| Script polls Discord API | DDC pings external URL |
| Token exposed on monitoring server | Only outbound HTTPS requests |
| Rate limit concerns | No Discord API usage |

The Status Watchdog is **more secure** because:
- **Outbound only**: DDC makes outgoing requests, nothing listens for incoming connections
- **No data exposure**: Only a simple HTTP GET, no tokens or sensitive information sent
- **User-controlled**: You choose the monitoring service and configure alerts there

## Compatible Services

### Healthchecks.io (Recommended)
- **Free tier**: 20 checks
- **URL**: https://healthchecks.io
- **Setup**: Create account → New Check → Copy ping URL
- Supports: Email, Slack, Discord Webhook, PagerDuty, SMS

### Uptime Kuma (Self-hosted)
- **Free**: Open source, self-hosted
- **URL**: https://github.com/louislam/uptime-kuma
- **Setup**: Install → Add Monitor (Push type) → Copy push URL
- Supports: 90+ notification types

### Other Services
- **Cronitor**: https://cronitor.io
- **Dead Man's Snitch**: https://deadmanssnitch.com
- **Pingdom**: https://pingdom.com

## Configuration

### Web UI Setup

1. Navigate to **Configuration** in the Web UI
2. Scroll to **Status Watchdog** section
3. Enable the toggle
4. Enter your monitoring URL (must be `https://`)
5. Set the ping interval (default: 5 minutes)
6. Save configuration

### Settings

| Setting | Description | Default |
|---------|-------------|---------|
| **Monitoring URL** | The HTTPS URL to ping (from your monitoring service) | - |
| **Ping Interval** | How often DDC sends a ping (minutes) | 5 |

### Recommended Timeout Settings

Set your monitoring service timeout to **2-3x the ping interval**:

| Ping Interval | Recommended Timeout |
|---------------|---------------------|
| 1 minute | 3-5 minutes |
| 5 minutes | 15 minutes |
| 10 minutes | 30 minutes |

This allows for occasional network delays without false alerts.

## Example: Healthchecks.io Setup

### Step 1: Create a Check

1. Sign up at [healthchecks.io](https://healthchecks.io)
2. Click **+ Add Check**
3. Name it "DDC Bot" or similar
4. Set **Period** to match your ping interval (e.g., 5 minutes)
5. Set **Grace** to 2x the period (e.g., 10 minutes)
6. Copy the ping URL: `https://hc-ping.com/your-uuid-here`

### Step 2: Configure DDC

1. Paste the URL into DDC's **Monitoring URL** field
2. Set interval to match (e.g., 5 minutes)
3. Save and restart DDC

### Step 3: Configure Alerts

In Healthchecks.io:
1. Go to **Integrations**
2. Add your preferred notification method:
   - **Discord Webhook**: Paste your Discord webhook URL
   - **Email**: Already configured by default
   - **Slack/Telegram/etc.**: Follow integration guides

## Example: Uptime Kuma Setup

### Step 1: Add Push Monitor

1. In Uptime Kuma, click **Add New Monitor**
2. Select **Push** as monitor type
3. Set **Heartbeat Interval** (e.g., 300 seconds = 5 minutes)
4. Copy the push URL

### Step 2: Configure DDC

1. Paste the push URL into DDC's **Monitoring URL** field
2. Set matching interval
3. Save and restart DDC

### Step 3: Configure Notifications

1. Go to **Settings** → **Notifications**
2. Add Discord, Email, or other notification services
3. Assign notifications to your DDC monitor

## Troubleshooting

### Ping Not Working

1. **Check URL format**: Must start with `https://`
2. **Check network**: DDC needs outbound HTTPS access
3. **Check logs**: Look for `[Watchdog]` entries in DDC logs
4. **Test manually**: Try the URL in a browser (should return 200 OK)

### False Alerts

1. **Increase timeout**: Set monitoring service timeout to 3x ping interval
2. **Check interval mismatch**: Ensure DDC interval matches service expectation
3. **Network issues**: Check for intermittent connectivity problems

### Log Messages

```
[Watchdog] Ping successful              # Normal operation
[Watchdog] Ping returned status 404     # URL incorrect
[Watchdog] Ping failed: <error>         # Network/connection issue
[Watchdog] Monitoring URL must use HTTPS # Security check failed
```

## Best Practices

1. **Run monitoring service externally**: Use a cloud service or host Uptime Kuma on a different server than DDC. If the DDC host goes down, you want to know!

2. **Use Discord webhooks for alerts**: Most monitoring services support Discord webhooks - get alerts directly in Discord.

3. **Set reasonable intervals**: 5 minutes is a good balance between quick detection and minimal overhead.

4. **Test your alerts**: Temporarily stop DDC to verify alerts are working.

5. **Monitor the monitor**: If using self-hosted Uptime Kuma, consider also using a cloud service as backup.

---
*Last updated: November 2025*
