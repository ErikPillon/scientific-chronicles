# Running on a server

The laptop is the wrong host for this: launchd user agents only run while
you are logged in, so a closed lid means a post published late or not at all.
A machine that is always up removes that failure mode.

```bash
tools/instagram/deploy/deploy_server.sh epillon@100.93.81.36
```

Run it from the Mac. It refuses to proceed while the laptop jobs are still
installed — two approval bots polling one Telegram token steal each other's
updates, and two publishers would post the same queue twice — and offers to
remove them first.

What it moves:

| | |
|---|---|
| code | `git clone`/`reset --hard` to `origin/main` |
| venv | rebuilt on the server (`opencv-python-headless`, no X11 needed) |
| `~/.config/sc-instagram/env` | copied, `chmod 600`, `SCIG_REPO` repointed |
| `queue.db` | copied, so post history and repost cooldowns carry over |
| portrait cache | rsynced, so the backfill is not repeated |

It runs `doctor.py` on the server and installs nothing if that fails.

## Units

systemd **user** units with lingering enabled, so they run with nobody
logged in:

```
scig-approve.service   always on, Restart=always
scig-daily.timer       09:00 Europe/Rome
scig-publish.timer     every 5 minutes
scig-token.timer       1st of the month, 04:00
```

Every timer sets `Persistent=true`, so a run missed while the machine was
down fires on the next boot rather than being skipped.

Publishing times come from `SCIG_TIMEZONE` in the env file, not the server
clock, so a server running UTC still posts at 08:00 Rome.

```bash
systemctl --user list-timers 'scig-*'
journalctl --user -u scig-approve -f
systemctl --user restart scig-approve      # after a code change
```

## Updating

Re-run `deploy_server.sh`. It fast-forwards the checkout, reinstalls
dependencies, and reloads the units.

Note it does `git reset --hard origin/main`, so anything the pipeline wrote
into the server's checkout is discarded. That matters if you set
`SCIG_ASSET_COMMIT=1`: commit and push those from the server before
redeploying, or keep asset persistence on the Mac.
