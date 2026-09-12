#!/bin/bash
# Remove the launchd jobs. Leaves config, state and cached portraits.
set -uo pipefail
PREFIX="com.scientificchronicles"
for suffix in ig-approve ig-daily ig-publish ig-token; do
  label="$PREFIX.$suffix"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null && echo "stopped $label"
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
done
echo "Config (~/.config/sc-instagram/env) and state (~/.local/state/sc-instagram) kept."
