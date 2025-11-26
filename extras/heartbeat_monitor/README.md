# DDC Heartbeat Monitor

This folder previously contained standalone heartbeat monitoring scripts.

**The monitor scripts are now generated dynamically through the Web UI.**

## How to use

1. Go to DDC Web UI → Configuration → Heartbeat Monitoring section
2. Configure your heartbeat channel and timeout settings
3. Click "Download Monitor Script" to get a pre-configured script
4. Run the script on a **separate server/machine** (not on the same host as DDC)

## Script Types

- **Python**: Continuous monitoring with recovery detection (recommended)
- **Bash**: One-shot check, ideal for cron jobs
- **Windows Batch**: One-shot check for Task Scheduler

## Why separate machine?

The monitor should run on a different machine than DDC to detect if the DDC host goes down entirely.
