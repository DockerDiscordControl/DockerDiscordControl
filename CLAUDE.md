# Claude Development Notes

## Environment Setup
- **Development Environment**: Unraid system accessed via network share mounted at `/Volumes/appdata/dockerdiscordcontrol/`
- **Testing**: Always test changes directly on the Unraid system, not locally
- **Web UI Port**: Use `DDC_WEB_PORT=5001` when running web server
- **Docker Context**: Code runs inside Docker container on Unraid

## Key Commands
- Start Web UI: `DDC_WEB_PORT=5001 python3 -m app.web_ui`
- Run tests: `python -m pytest -xvs tests/ --tb=short`
- Check mech status: `DDC_WEB_PORT=5001 python3 -c "from services.mech_service import get_mech_service; print(get_mech_service().get_state())"`

## Architecture Notes
- Discord bot uses asyncio event loop
- Web UI uses Gevent for threading compatibility
- Mech service handles power decay and level calculations
- Animation system uses PIL/Pillow for WebP generation

## Power System v3.0 - Ultra Optimized
- **Client-side Power Calculation**: `seconds / 86400` (1 power per day) 
- **Smart Update Logic**: Check every 10s, update only on 0.01 decimal change
- **Actual Updates**: Only 100 DOM updates per day (every 14.4 minutes average)
- **Server Sync**: Every 60s only for new donations (>$0.50 difference)
- **Performance**: 99.9% reduction - from 1200 to 60 API calls/hour
- **Animation**: Only regenerates on integer power changes ($1 increments)