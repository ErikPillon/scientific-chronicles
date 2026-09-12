#!/bin/bash
# Set up the Instagram pipeline: venv, approval service, scheduled jobs.
# Everything runs on launchd. No openclaw, no agent, no model calls.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HERE/.venv/bin/python"
ENV_FILE="${SCIG_ENV_FILE:-$HOME/.config/sc-instagram/env}"
LOGS="$HOME/.local/state/sc-instagram/logs"
AGENTS="$HOME/Library/LaunchAgents"
PREFIX="com.scientificchronicles"

echo "==> Python environment"
[ -d "$HERE/.venv" ] || python3 -m venv "$HERE/.venv"
"$HERE/.venv/bin/pip" -q install --upgrade pip
"$HERE/.venv/bin/pip" -q install Pillow boto3 requests PyYAML "opencv-python-headless<5"
echo "    ok"

echo "==> Config"
mkdir -p "$(dirname "$ENV_FILE")" "$LOGS" "$AGENTS"
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
  echo "    doctor reported failures; not installing the jobs yet."
  exit 1
fi

# write_agent <suffix> <script+args> <schedule-xml> [keepalive]
write_agent() {
  local suffix="$1" script="$2" schedule="$3" keepalive="${4:-}"
  local label="$PREFIX.$suffix"
  local plist="$AGENTS/$label.plist"
  cat > "$plist" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$HERE/$script</string>
  </array>
  <key>WorkingDirectory</key><string>$HERE</string>
  <key>EnvironmentVariables</key>
  <dict><key>SCIG_ENV_FILE</key><string>$ENV_FILE</string></dict>
$schedule
$keepalive
  <key>StandardOutPath</key><string>$LOGS/$suffix.log</string>
  <key>StandardErrorPath</key><string>$LOGS/$suffix.err</string>
</dict>
</plist>
PLIST_EOF
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
  echo "    + $label"
}

echo "==> launchd jobs"

# Approval bot: long-polls Telegram, restarted if it ever exits.
write_agent ig-approve approve_bot.py \
  "  <key>RunAtLoad</key><true/>" \
  "  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>"

# Daily pick at 09:00. A calendar job missed while asleep fires on wake;
# daily.py is guarded so a catch-up run will not queue a second post.
write_agent ig-daily daily.py \
  "  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>"

# Publisher every 15 minutes — this is what makes scheduling work, since
# Instagram has no native scheduling of its own.
write_agent ig-publish publish_due.py \
  "  <key>StartInterval</key><integer>900</integer>"

# Token refresh on the 1st at 04:00; the token lapses after ~60 days.
write_agent ig-token refresh_token.py \
  "  <key>StartCalendarInterval</key>
  <dict><key>Day</key><integer>1</integer><key>Hour</key><integer>4</integer><key>Minute</key><integer>0</integer></dict>"

echo
echo "Done. Nothing here calls a language model."
echo "  ig-approve   always on   Telegram buttons"
echo "  ig-daily     09:00       pick + preview"
echo "  ig-publish   every 15m   R2 + Instagram"
echo "  ig-token     monthly     token refresh"
echo
echo "  Status:  launchctl list | grep $PREFIX"
echo "  Test:    $PY $HERE/daily.py --dry-run"
echo "  Logs:    $LOGS"
