# DDC Heartbeat Monitor (Extras)

This directory contains the standalone heartbeat monitoring tool. It is not part of the container runtime and can be used on a separate host to monitor the DDC bot.

Moved from `heartbeat_monitor/` to `extras/heartbeat_monitor/` for clearer separation.

Quick start:
1. `pip install discord.py`
2. Copy `config.json.example` to `config.json` and edit values
3. `python ddc_heartbeat_monitor.py`


