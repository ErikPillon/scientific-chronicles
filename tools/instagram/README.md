# Instagram auto-posting pipeline

Daily: pick the best item for today's date from the corpus, render a 4:5
image, and send it to Telegram with Approve / Decline / Next buttons. On
approval the image goes to Cloudflare R2 and the post is published to
Instagram at the configured time.

```
daily.py ──► render ──► Telegram preview ──► [you tap Approve]
                                                    │
                                        approve_bot.py marks it approved
                                                    │
                                   publish_due.py ──► R2 ──► Instagram
```

## Parts

| File | Role |
|---|---|
| `daily.py` | Cron entry point: pick today's item, render, send for approval |
| `approve_bot.py` | launchd service; handles the inline-keyboard taps |
| `publish_due.py` | Cron entry point; uploads to R2 and publishes when due |
| `refresh_token.py` | Monthly; keeps the ~60-day Instagram token alive |
| `doctor.py` | Preflight — checks every credential and hop |
| `contact_sheet.py` | Builds an image-provenance review sheet |
| `content.py` | Reads the corpus, ranks candidates, builds captions |
| `render.py` | The three image treatments |
| `store.py` | SQLite queue |

## Setup

```bash
tools/instagram/install.sh
```

First run copies `env.example` to `~/.config/sc-instagram/env` and stops.
Fill that in, re-run, and it will run `doctor.py`, install the launchd
service, and register three openclaw automations.

## Image provenance — read this

`assets/images/` was collected for the website. A large share of it is
screenshots of other people's social posts, watermarked quote graphics, and
third-party diagrams. That is fine on a personal Hugo site and not fine
republished to a public Instagram account.

So `SCIG_IMAGE_POLICY` defaults to `allowlist` with an empty allowlist:
**every post renders as a generated card**, which is always safe. To start
using real photographs:

```bash
.venv/bin/python contact_sheet.py --out image-review.jpg
open image-review.jpg
# put the filenames you own, or that are clearly public domain,
# in ~/.config/sc-instagram/image-allowlist.txt (one per line)
```

Wikimedia Commons is the practical source for the rest — most pre-1930
portraits are public domain. Backfilling it would lift photo coverage from
~2% to most of the corpus; that is a separate job.

## Image treatments

* **photo** — portrait asset (h/w ≥ 1.15, ≥ 700px wide), full bleed under a scrim
* **inset** — square or landscape asset, letterboxed in a rounded panel
* **card** — no permitted asset: typographic card with a ghosted year

## Day-to-day

```bash
.venv/bin/python daily.py --dry-run        # what would post today
.venv/bin/python daily.py                  # send today's preview now
.venv/bin/python publish_due.py --force    # publish approved posts immediately
.venv/bin/python doctor.py                 # re-check credentials
openclaw cron list                         # scheduled jobs
openclaw cron runs ig-daily-pick           # run history
tail -f ~/.local/state/sc-instagram/logs/approve-bot.log
```

State lives in `~/.local/state/sc-instagram/` (`queue.db`, `media/`, `logs/`).
Nothing is written into the repo.

## Notes

* Instagram has no native scheduling. `publish_due.py` runs every 15 minutes
  and does the waiting; containers are created at publish time because they
  expire after 24h.
* Instagram allows 25 posts per rolling 24h. `SCIG_MAX_POSTS_PER_DAY` is 1,
  and the publisher also checks the remote quota before posting.
* The approval bot must use its own token, not openclaw's. Two long-poll
  consumers on one token steal each other's updates; `doctor.py` checks this.
* Only `SCIG_TELEGRAM_CHAT_ID` may approve. Taps from anyone else are refused.
