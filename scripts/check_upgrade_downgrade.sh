#!/bin/bash
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
#
# Play upgrade and downgrade between v2.4.1 and the current image against one
# throwaway config directory (docs/V3_ARCHITECTURE_PLAN.md §5.5, step 11):
#
#   1. v2.4.1 writes a configuration.                      (old install)
#   2. v3 reads it, switches 2FA on, creates a TLS cert.   (upgrade)
#   3. v2.4.1 loads and saves the configuration.           (downgrade)
#   4. v3 still finds 2FA on, with the same secret.        (upgrade again)
#
# The risk this measures: v2.4.1 copies only the config keys it knows, so a
# 2FA secret kept inside the configuration would be dropped by the first save
# after a downgrade, and 2FA would be silently off after the next upgrade.
# v3 keeps it in config/two_factor.json and config/tls/ instead.
#
#   bash scripts/check_upgrade_downgrade.sh [old-image] [new-image]
#
# Runs on the Docker host, one limited throwaway container at a time, never
# against the live config. Exit code 0 only if every step held.
# DDC_CHECK_SIMULATE_LOSS=1 deletes two_factor.json in step 3 - the counter-check
# that this script can fail.

set -u
OLD="${1:-dockerdiscordcontrol:v2.4.1-backup}"
NEW="${2:-dockerdiscordcontrol:latest}"
WORK=$(mktemp -d /tmp/ddc-updown-XXXX)
chown 1000:1000 "$WORK"
trap 'rm -rf "$WORK"' EXIT
fail=0

run() {  # image, python code
    docker run --rm --memory=256m --pids-limit=64 -u ddc \
        -v "$WORK":/app/config -e DDC_ENABLE_BACKGROUND_REFRESH=false \
        --entrypoint python3 "$1" -c "$2"
}

step() {
    if run "$2" "$3"; then echo "ok    $1"; else echo "FAIL  $1"; fail=1; fi
}

step "1 v2.4.1 writes a configuration" "$OLD" "
from services.config.config_service import load_config, save_config
from werkzeug.security import generate_password_hash
c = load_config(); c['web_ui_password_hash'] = generate_password_hash('pw'); c['language'] = 'de'
raise SystemExit(0 if save_config(c) else 1)"

step "2 v3 reads it, 2FA on, TLS cert" "$NEW" "
import time, hashlib, json
from services.config.config_service import load_config
from services.web.two_factor_service import TwoFactorStore, totp, secret_bytes
from app.web.tls import ensure_self_signed_certificate
c = load_config()
if not c.get('web_ui_password_hash') or c.get('language') != 'de': raise SystemExit('upgrade lost the configuration')
s = TwoFactorStore(); s.begin_setup(); now = time.time()
if not s.confirm_setup(totp(secret_bytes(s.pending_or_active_secret()), now), now=now): raise SystemExit('2FA not on')
ensure_self_signed_certificate('/app/config/tls')
open('/app/config/.expected', 'w').write(json.dumps({p: hashlib.sha256(open('/app/config/' + p, 'rb').read()).hexdigest() for p in ('two_factor.json', 'tls/ddc.crt', 'tls/ddc.key')}))"

step "3 v2.4.1 loads and saves (downgrade)" "$OLD" "
import os
from services.config.config_service import load_config, save_config
c = load_config(); c['language'] = 'en'
ok = save_config(c)
if '${DDC_CHECK_SIMULATE_LOSS:-0}' == '1':
    os.remove('/app/config/two_factor.json')
raise SystemExit(0 if ok else 1)"

step "4 v3 finds 2FA still on, files unchanged" "$NEW" "
import json, hashlib
from services.config.config_service import load_config
from services.web.two_factor_service import TwoFactorStore
expected = json.load(open('/app/config/.expected'))
now = {p: hashlib.sha256(open('/app/config/' + p, 'rb').read()).hexdigest() for p in expected}
if now != expected: raise SystemExit('downgrade changed: ' + str([p for p in expected if now[p] != expected[p]]))
if not TwoFactorStore().enabled: raise SystemExit('2FA silently off after the round trip')
if load_config().get('language') != 'en': raise SystemExit('the downgrade save did not land')"

if [ "$fail" = "0" ]; then
    echo "Upgrade and downgrade hold."
else
    echo "UPGRADE/DOWNGRADE BROKEN - see FAIL lines above."
fi
exit "$fail"
