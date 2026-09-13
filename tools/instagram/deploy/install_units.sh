#!/bin/bash
# Runs ON the server. Installs systemd user units for the pipeline.
set -euo pipefail

REPO="${REMOTE_REPO:-$HOME/scientific-chronicles}"
REPO="${REPO/#\~/$HOME}"
DIR="$REPO/tools/instagram"
PY="$DIR/.venv/bin/python"
UNITS="$HOME/.config/systemd/user"
mkdir -p "$UNITS"

# Without lingering, user services stop the moment you log out — the whole
# point of moving off the laptop.
if ! loginctl show-user "$USER" -p Linger --value 2>/dev/null | grep -q yes; then
  loginctl enable-linger "$USER" 2>/dev/null \
    && echo "  lingering enabled" \
    || echo "  WARNING: could not enable lingering; run: sudo loginctl enable-linger $USER"
fi

cat > "$UNITS/scig-approve.service" <<EOF
[Unit]
Description=Scientific Chronicles — Telegram approval bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=$DIR
ExecStart=$PY $DIR/approve_bot.py
Restart=always
RestartSec=15

[Install]
WantedBy=default.target
EOF

# oneshot + timer for the periodic jobs
make_timer() {
  local name="$1" script="$2" calendar="$3" desc="$4"
  cat > "$UNITS/scig-$name.service" <<EOF
[Unit]
Description=Scientific Chronicles — $desc
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=$DIR
ExecStart=$PY $DIR/$script
EOF
  cat > "$UNITS/scig-$name.timer" <<EOF
[Unit]
Description=Scientific Chronicles — $desc

[Timer]
OnCalendar=$calendar
Persistent=true
AccuracySec=1min

[Install]
WantedBy=timers.target
EOF
}

# Persistent=true reruns a timer missed while the machine was down — the
# behaviour launchd only approximates.
make_timer daily   daily.py         "*-*-* 09:00:00 Europe/Rome" "offer tomorrow's candidates"
make_timer publish publish_due.py   "*:0/5"                      "publish approved posts that are due"
make_timer token   refresh_token.py "*-*-01 04:00:00 Europe/Rome" "refresh the Instagram token"

systemctl --user daemon-reload
systemctl --user enable --now scig-approve.service >/dev/null
for t in daily publish token; do
  systemctl --user enable --now "scig-$t.timer" >/dev/null
done

echo "  installed:"
systemctl --user --no-pager --plain list-timers 'scig-*' 2>/dev/null | sed -n '1,6p' | sed 's/^/    /'
echo "    scig-approve: $(systemctl --user is-active scig-approve.service)"
