#!/bin/bash
# Patch the running container with fixed code (no rebuild needed!)

echo "🔧 Patching Container Code (No Rebuild Required)"
echo "================================================"
echo ""

# 1. Patch save_config to not create legacy files
echo "📝 Patching config_service.py..."
docker exec dockerdiscordcontrol bash -c 'cat > /tmp/patch_save_config.py << "EOPATCH"
import re

# Read the file
with open("/app/services/config/config_service.py", "r") as f:
    content = f.read()

# Find and replace the save_config method
pattern = r"def save_config\(self, config: Dict\[str, Any\]\) -> ConfigServiceResult:.*?except Exception as e:.*?return ConfigServiceResult\(\s*success=False,\s*error=str\(e\)\s*\)"

replacement = """def save_config(self, config: Dict[str, Any]) -> ConfigServiceResult:
        \"\"\"Save configuration - MODULAR ONLY (no legacy files).\"\"\"
        with self._save_lock:
            try:
                # DO NOT save legacy files anymore!
                # Container configs are saved by save_container_configs_from_web()
                logger.info("save_config called - modular structure only")
                self._invalidate_cache()
                return ConfigServiceResult(success=True, message="Config saved (modular)")
            except Exception as e:
                logger.error(f"Error saving configuration: {e}")
                return ConfigServiceResult(success=False, error=str(e))"""

# Replace using regex
content_new = re.sub(pattern, replacement, content, flags=re.DOTALL)

# Write back
with open("/app/services/config/config_service.py", "w") as f:
    f.write(content_new)

print("✅ Patched config_service.py")
EOPATCH

python3 /tmp/patch_save_config.py'

if [ $? -eq 0 ]; then
    echo "✅ Code patched successfully!"
else
    echo "❌ Patch failed!"
    exit 1
fi

# 2. Restart the web UI and bot processes (without full container restart)
echo ""
echo "🔄 Restarting services inside container..."
docker exec dockerdiscordcontrol supervisorctl restart all

echo ""
echo "✅ Patch complete! Services restarted."
echo ""
echo "Now test in Web UI:"
echo "1. Change a container permission (e.g., remove 'restart' from Icarus)"
echo "2. Click Save"
echo "3. Check: cat config/containers/Icarus.json"
echo ""
echo "The change should be saved immediately!"
