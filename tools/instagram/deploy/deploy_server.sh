#!/bin/bash
# Move the pipeline onto a Linux server, run from your Mac.
#
#   tools/instagram/deploy/deploy_server.sh [user@host]
#
# Transfers code, credentials, queue and portrait cache, then installs
# systemd *user* units with lingering enabled so they run with nobody
# logged in. Idempotent: safe to re-run after a code change.
set -euo pipefail

REMOTE="${1:-epillon@100.93.81.36}"
REPO_URL="${SCIG_REPO_URL:-https://github.com/ErikPillon/scientific-chronicles.git}"
REMOTE_REPO="${SCIG_REMOTE_REPO:-~/scientific-chronicles}"
ENV_FILE="$HOME/.config/sc-instagram/env"
STATE="$HOME/.local/state/sc-instagram"
SSH_OPTS="-o ConnectTimeout=10"

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

say "Checking $REMOTE"
ssh $SSH_OPTS "$REMOTE" 'echo "  connected: $(uname -srm)"; . /etc/os-release 2>/dev/null && echo "  $PRETTY_NAME"'

say "Refusing to run two copies at once"
if launchctl list 2>/dev/null | grep -q com.scientificchronicles; then
  echo "  The laptop jobs are still installed."
  echo "  Two approval bots on one Telegram token steal each other's updates,"
  echo "  and both publishers would post the same queue twice."
  read -rp "  Stop the laptop jobs now? [Y/n] " reply
  if [[ ! "$reply" =~ ^[Nn] ]]; then
    "$(dirname "${BASH_SOURCE[0]}")/../uninstall.sh"
  else
    echo "  Aborting: refusing to deploy alongside a running local copy." >&2
    exit 1
  fi
fi

say "Code"
ssh $SSH_OPTS "$REMOTE" "
  set -e
  if [ -d $REMOTE_REPO/.git ]; then
    git -C $REMOTE_REPO fetch --quiet origin && git -C $REMOTE_REPO reset --hard --quiet origin/main
    echo '  updated to' \$(git -C $REMOTE_REPO rev-parse --short HEAD)
  else
    git clone --quiet $REPO_URL $REMOTE_REPO
    echo '  cloned'
  fi"

say "Python environment"
ssh $SSH_OPTS "$REMOTE" "
  set -e
  cd $REMOTE_REPO/tools/instagram
  command -v python3 >/dev/null || { echo '  python3 missing — apt install python3 python3-venv' >&2; exit 1; }
  [ -d .venv ] || python3 -m venv .venv
  ./.venv/bin/pip -q install --upgrade pip
  ./.venv/bin/pip -q install Pillow boto3 requests PyYAML 'opencv-python-headless<5'
  echo '  ok:' \$(./.venv/bin/python -V)"

say "Credentials"
[ -f "$ENV_FILE" ] || { echo "  $ENV_FILE not found" >&2; exit 1; }
ssh $SSH_OPTS "$REMOTE" 'mkdir -p ~/.config/sc-instagram && chmod 700 ~/.config/sc-instagram'
scp $SSH_OPTS -q "$ENV_FILE" "$REMOTE:.config/sc-instagram/env"
# SCIG_REPO must point at the server's checkout, not the Mac's path.
ssh $SSH_OPTS "$REMOTE" "
  chmod 600 ~/.config/sc-instagram/env
  sed -i 's|^SCIG_REPO=.*|SCIG_REPO=$REMOTE_REPO|' ~/.config/sc-instagram/env
  echo '  copied, SCIG_REPO repointed at' $REMOTE_REPO"

say "Queue and portrait cache"
ssh $SSH_OPTS "$REMOTE" 'mkdir -p ~/.local/state/sc-instagram/{media,logs}'
if [ -f "$STATE/queue.db" ]; then
  scp $SSH_OPTS -q "$STATE/queue.db" "$REMOTE:.local/state/sc-instagram/queue.db"
  echo "  queue.db copied (keeps post history and repost cooldowns)"
fi
if [ -d "$STATE/wikimedia" ]; then
  echo "  syncing portrait cache ($(du -sh "$STATE/wikimedia" | cut -f1)) — this is the slow part"
  # macOS ships openrsync, which lacks --info=progress2; keep to portable flags.
  rsync -az "$STATE/wikimedia/" "$REMOTE:.local/state/sc-instagram/wikimedia/"
fi

say "Preflight on the server"
ssh $SSH_OPTS "$REMOTE" "cd $REMOTE_REPO/tools/instagram && ./.venv/bin/python doctor.py" || {
  echo "  doctor failed on the server — not installing the timers." >&2; exit 1; }

say "systemd user units"
ssh $SSH_OPTS "$REMOTE" "REMOTE_REPO=$REMOTE_REPO bash -s" < "$(dirname "${BASH_SOURCE[0]}")/install_units.sh"

say "Done"
echo "  The server now owns the pipeline. On the server:"
echo "    systemctl --user list-timers 'scig-*'"
echo "    journalctl --user -u scig-approve -f"
