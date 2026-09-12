# Instagram auto-posting pipeline

Daily: pick the best item for today's date, find a portrait, render it in the
house style, and send it to Telegram with Approve / Decline / Next buttons.
On approval the image goes to Cloudflare R2 and publishes to Instagram at the
configured time.

```
daily.py ──► image ──► render ──► Telegram preview ──► [you tap Approve]
             │                                              │
    corpus asset → Wikimedia → card          approve_bot.py marks it approved
                                                            │
                                        publish_due.py ──► R2 ──► Instagram
```

**No language model is involved anywhere in this pipeline.** Everything is
plain Python: Pillow for rendering, the Telegram Bot API for approval, boto3
for R2, the Graph API for publishing. Scheduling is launchd. Token cost is
zero.

## Parts

| File | Role |
|---|---|
| `setup_credentials.py` | Interactive, verified credential entry |
| `daily.py` | Pick today's item, render, send for approval |
| `approve_bot.py` | Long-running service; handles the inline-keyboard taps |
| `publish_due.py` | Uploads to R2 and publishes when due |
| `refresh_token.py` | Monthly; keeps the ~60-day Instagram token alive |
| `doctor.py` | Preflight — checks every credential and hop |
| `backfill.py` | Pre-fetch Wikimedia portraits for the whole corpus |
| `contact_sheet.py` | Review sheet of the corpus image pool |
| `wikimedia.py` | Portrait lookup, identity check, licence filter, cache |
| `content.py` | Reads the corpus, ranks candidates, builds captions |
| `render.py` | The three image treatments |
| `store.py` | SQLite queue |

## Setup

```bash
tools/instagram/.venv/bin/python tools/instagram/setup_credentials.py
tools/instagram/install.sh
```

`setup_credentials.py` walks through each secret, says where to find it,
verifies it on the spot, and writes `~/.config/sc-instagram/env` at 0600.
Secrets are read with `getpass`, so they never echo or reach your shell
history. It saves after each section and is safe to re-run — Enter keeps an
existing value.

`install.sh` then runs `doctor.py` and installs four launchd jobs.

```
ig-approve   always on   Telegram buttons
ig-daily     09:00       pick + preview
ig-publish   every 15m   R2 + Instagram
ig-token     monthly     token refresh
```

Then warm the portrait cache — one pass over ~2000 people, a few minutes:

```bash
.venv/bin/python backfill.py            # everything
.venv/bin/python backfill.py --month 9  # one month first, to see the hit rate
```

Ranking uses the cache, so backfilling also makes the picker prefer people who
actually have a portrait.

## Images

Three treatments, in order of preference:

1. **photo** — full bleed under a scrim, type over the bottom. Anything with
   h/w ≥ 0.95 and ≥ 700px wide. This is the default look.
2. **inset** — too wide to crop without wrecking it, so it is letterboxed in a
   rounded panel on the ink background.
3. **card** — no usable image: typographic card with a ghosted year.

Sources are tried in order: corpus asset in `assets/images/`, then a Wikimedia
portrait, then the card.

### Wikimedia rules

* **Identity.** A page is only accepted when the surname matches the resolved
  title *and* a known birth or death year appears in the article intro. A
  photo of the wrong person is worse than a card, so misses fall back rather
  than guess. Only people are looked up — an event title does not map to a
  correct image reliably enough.
* **Licence.** The render overlays type, which makes a derivative work.
  Share-alike would propagate that obligation to the post, so `cc-by-sa` is
  excluded by default; `pd`, `cc0` and `cc-by` are kept. Change with
  `SCIG_WIKIMEDIA_LICENSES`.
* **Credit** is appended to the caption automatically for anything that is
  not public domain, and for PD too when an author is known.
* Results are cached on disk, negatives included, so repeat runs cost nothing
  and Wikimedia is not re-queried daily.

Corpus assets come from an earlier project; a few carry third-party
watermarks. `contact_sheet.py` renders the pool for review, and
`SCIG_IMAGE_POLICY=blocklist` plus a blocklist file makes the marked ones fall
through to Wikimedia instead.

## Day-to-day

```bash
.venv/bin/python daily.py --dry-run        # what would post today
.venv/bin/python daily.py                  # send today's preview now
.venv/bin/python publish_due.py --force    # publish approved posts immediately
.venv/bin/python doctor.py                 # re-check credentials
launchctl list | grep scientificchronicles # job status
tail -f ~/.local/state/sc-instagram/logs/ig-approve.log
```

State lives in `~/.local/state/sc-instagram/` — `queue.db`, `media/`,
`wikimedia/`, `logs/`. Nothing is written into the repo.

## Notes

* Instagram has no native scheduling. `publish_due.py` runs every 15 minutes
  and does the waiting; containers are created at publish time because they
  expire after 24h.
* Instagram allows 25 posts per rolling 24h. `SCIG_MAX_POSTS_PER_DAY` is 1 and
  the publisher also checks the remote quota before posting.
* A calendar job missed while the Mac sleeps fires on wake. `daily.py` will
  not queue a second post for a day that already has one; use `--again` to
  override.
* The approval bot needs its own Telegram token. If you also run openclaw,
  two long-poll consumers on one token steal each other's updates —
  `doctor.py` checks for exactly this.
* Only `SCIG_TELEGRAM_CHAT_ID` may approve; taps from anyone else are refused.
