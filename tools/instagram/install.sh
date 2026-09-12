#!/bin/bash
# Set up the Instagram pipeline: venv, approval service, scheduled jobs.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HERE/.venv/bin/python"
LABEL="com.scientificchronicles.ig-approve"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
ENV_FILE="${SCIG_ENV_FILE:-$HOME/.config/sc-instagram/env}"
LOGS="$HOME/.local/state/sc-instagram/logs"

echo "==> Python environment"
[ -d "$HERE/.venv" ] || python3 -m venv "$HERE/.venv"
"$HERE/.venv/bin/pip" -q install --upgrade pip
"$HERE/.venv/bin/pip" -q install Pillow boto3 requests PyYAML
echo "    ok"

echo "==> Config"
mkdir -p "$(dirname "$ENV_FILE")" "$LOGS"
if [ ! -f "$ENV_FILE" ]; then
  cp "$HERE/env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "    created $ENV_FILE — fill it in, then re-run this script."
  exit 0
fi
chmod 600 "$ENV_FILE"
echo "    using $ENV_FILE"

echo "==> Preflight"
if ! "$PY" "$HERE/doctor.py"; then
  echo "    doctor reported failures; not installing the scheduled jobs yet."
  exit 1
fi

echo "==> Approval service (launchd)"
mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$HERE/approve_bot.py</string>
  </array>
  <key>WorkingDirectory</key><string>$HERE</string>
  <key>EnvironmentVariables</key>
  <dict><key>SCIG_ENV_FILE</key><string>$ENV_FILE</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$LOGS/approve-bot.log</string>
  <key>StandardErrorPath</key><string>$LOGS/approve-bot.err</string>
</dict>
</plist>
PLIST_EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "    loaded $LABEL"

echo "==> Scheduled jobs (openclaw)"
add_job() {
  local name="$1" cron="$2" script="$3" desc="$4"
  openclaw cron rm "$name" >/dev/null 2>&1 || true
  openclaw cron add "$name" \
    --cron "$cron" \
    --command "$PY $HERE/$script" \
    --command-cwd "$HERE" \
    --command-env "SCIG_ENV_FILE=$ENV_FILE" \
    --description "$desc" \
    --best-effort-deliver
  echo "    + $name  ($cron)"
}

add_job ig-daily-pick     "0 9 * * *"    daily.py         "Pick the day's item and send it for approval"
add_job ig-publish-due    "*/15 * * * *" publish_due.py   "Publish approved posts whose time has come"
add_job ig-token-refresh  "0 4 1 * *"    refresh_token.py "Refresh the long-lived Instagram token"

echo
echo "Done."
echo "  Daily pick   09:00  -> Telegram approval"
echo "  Publisher    every 15m"
echo "  Token refresh 1st of each month"
echo
echo "  Test now:  $PY $HERE/daily.py"
echo "  Logs:      $LOGS"
