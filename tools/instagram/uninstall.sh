#!/bin/bash
# Remove the scheduled jobs and the approval service. Leaves data and config.
set -uo pipefail
LABEL="com.scientificchronicles.ig-approve"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "stopped $LABEL"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
for job in ig-daily-pick ig-publish-due ig-token-refresh; do
  openclaw cron rm "$job" >/dev/null 2>&1 && echo "removed automation $job"
done
echo "Config at ~/.config/sc-instagram/env and state at ~/.local/state/sc-instagram were kept."
