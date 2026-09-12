#!/usr/bin/env python
"""Interactive credential setup.

Walks through every secret the pipeline needs, explains where to find it,
verifies it on the spot, and writes it to ~/.config/sc-instagram/env with
0600 permissions. Secrets are read with getpass so they never echo to the
terminal or land in your shell history.

Safe to re-run: existing values are offered as defaults and kept on Enter.
"""
from __future__ import annotations

import getpass
import os
import re
import subprocess
import sys
from pathlib import Path

ENV_FILE = Path(os.environ.get("SCIG_ENV_FILE", "~/.config/sc-instagram/env")).expanduser()
HERE = Path(__file__).resolve().parent

BOLD, DIM, GREEN, RED, YELLOW, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[0m"
)


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip("'\"")
    return values


def write_env(values: dict[str, str]) -> None:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    template = (HERE / "env.example").read_text(encoding="utf-8")
    out, seen = [], set()
    for line in template.splitlines():
        match = re.match(r"^([A-Z0-9_]+)=", line)
        if match and match.group(1) in values:
            key = match.group(1)
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)
    extra = [f"{k}={v}" for k, v in values.items() if k not in seen]
    if extra:
        out += ["", "# Added by setup_credentials.py", *extra]
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    ENV_FILE.chmod(0o600)


def banner(title: str, *lines: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")
    for line in lines:
        print(f"  {DIM}{line}{RESET}")


def ask(key: str, prompt: str, values: dict[str, str], *,
        secret: bool = False, default: str = "") -> str:
    current = values.get(key, "") or default
    if current:
        shown = f"{current[:6]}…{current[-4:]}" if secret and len(current) > 14 else current
        suffix = f" [{shown}]"
    else:
        suffix = ""
    while True:
        raw = (getpass.getpass(f"  {prompt}{suffix}: ") if secret
               else input(f"  {prompt}{suffix}: ")).strip()
        if raw:
            values[key] = raw
            return raw
        if current:
            values[key] = current
            return current
        print(f"  {RED}required{RESET}")


def verify(label: str, fn) -> bool:
    print(f"  {DIM}checking {label}…{RESET}", end=" ", flush=True)
    try:
        detail = fn()
        print(f"{GREEN}ok{RESET}" + (f" — {detail}" if detail else ""))
        return True
    except Exception as exc:
        print(f"{RED}failed{RESET}\n    {exc}")
        return False


def retry_or_skip() -> str:
    while True:
        choice = input(f"  {YELLOW}[r]etry, [s]kip for now, [q]uit: {RESET}").strip().lower()
        if choice in ("r", "s", "q", ""):
            return choice or "r"


def section(name: str, collect, values: dict[str, str]) -> None:
    """Run one section until it verifies, is skipped, or the user quits."""
    while True:
        if collect(values):
            write_env(values)          # save progress after each good section
            return
        choice = retry_or_skip()
        if choice == "s":
            print(f"  {YELLOW}skipped — doctor.py will flag it later{RESET}")
            write_env(values)
            return
        if choice == "q":
            write_env(values)
            print(f"\nSaved what you entered to {ENV_FILE}. Re-run any time.")
            sys.exit(0)


def main() -> int:
    print(f"{BOLD}Scientific Chronicles — Instagram pipeline credentials{RESET}")
    print(f"{DIM}Writing to {ENV_FILE} (chmod 600). Secrets are not echoed.{RESET}")
    print(f"{DIM}Press Enter to keep an existing value. Ctrl-C to stop.{RESET}")

    values = read_env()
    sys.path.insert(0, str(HERE))

    def apply(values: dict[str, str]) -> None:
        """Make the just-entered values visible to the client modules."""
        os.environ.update(values)
        for module in ("config", "telegram", "r2", "instagram", "content", "wikimedia"):
            sys.modules.pop(module, None)

    # ---- Telegram ----------------------------------------------------------
    def telegram_section(values):
        banner("1/3  Telegram approval bot",
               "Open @BotFather in Telegram and send /newbot.",
               "It must be a NEW bot — if you also run openclaw, sharing its",
               "token makes the two steal each other's updates.")
        ask("SCIG_TELEGRAM_BOT_TOKEN", "bot token", values, secret=True)
        print(f"  {DIM}Now send any message to your new bot so it can see your chat.{RESET}")
        ask("SCIG_TELEGRAM_CHAT_ID", "your numeric chat id", values,
            default=values.get("SCIG_TELEGRAM_CHAT_ID", ""))
        apply(values)

        import telegram as tg
        ok = verify("bot token", lambda: "@" + tg.call("getMe")["username"])
        if not ok:
            return False
        if not verify("owner chat", lambda: str(tg.call("getChat", chat_id=tg.chat_id())["id"])):
            print(f"    {DIM}If this failed, message the bot once, then retry.{RESET}")
            return False
        return verify("test message", lambda: (
            tg.call("sendMessage", chat_id=tg.chat_id(),
                    text="✅ Scientific Chronicles pipeline connected."),
            "sent — check Telegram")[1])

    # ---- Cloudflare R2 -----------------------------------------------------
    def r2_section(values):
        banner("2/3  Cloudflare R2",
               "Cloudflare dashboard > R2. Account ID is in the sidebar.",
               "Manage API tokens > Create token, Object Read & Write on one bucket.",
               "The public URL must be reachable — Instagram fetches the image itself.",
               "Prefer a custom domain; r2.dev is rate-limited by Cloudflare.")
        ask("SCIG_R2_ACCOUNT_ID", "account id", values)
        ask("SCIG_R2_ACCESS_KEY_ID", "access key id", values, secret=True)
        ask("SCIG_R2_SECRET_ACCESS_KEY", "secret access key", values, secret=True)
        ask("SCIG_R2_BUCKET", "bucket name", values,
            default=values.get("SCIG_R2_BUCKET", "scientific-chronicles-ig"))
        ask("SCIG_R2_PUBLIC_BASE", "public base URL (https://…)", values)
        apply(values)

        import r2, requests, config as cfg

        def probe():
            cfg.ensure_dirs()
            tmp = cfg.MEDIA_DIR / "_setup_probe.txt"
            tmp.write_text("scientific-chronicles setup probe")
            key = "instagram/_setup/probe.txt"
            url = r2.upload(tmp, key)
            tmp.unlink(missing_ok=True)
            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                raise RuntimeError(
                    f"{url} returned HTTP {response.status_code}. Instagram must be "
                    f"able to fetch it — enable public access on the bucket.")
            r2.delete(key)
            return "upload + public read"
        return verify("bucket read/write and public URL", probe)

    # ---- Instagram ---------------------------------------------------------
    def instagram_section(values):
        banner("3/3  Instagram",
               "developers.facebook.com > your app > Graph API Explorer.",
               "Permissions: instagram_basic, pages_show_list,",
               "             instagram_business_content_publish",
               "Call /me/accounts, then /{page-id}?fields=instagram_business_account",
               "to get the Instagram user id. Exchange for a long-lived token.",
               "App id and secret (Settings > Basic) let it auto-refresh.")
        ask("SCIG_IG_USER_ID", "instagram business user id", values)
        ask("SCIG_IG_ACCESS_TOKEN", "long-lived access token", values, secret=True)
        ask("SCIG_META_APP_ID", "meta app id", values)
        ask("SCIG_META_APP_SECRET", "meta app secret", values, secret=True)
        values.setdefault("SCIG_IG_API_BASE", "https://graph.facebook.com/v23.0")
        apply(values)

        import instagram as ig

        def account():
            data = ig._request("GET", ig._user_id(),
                               fields="username,account_type,media_count")
            kind = data.get("account_type", "?")
            if kind not in ("BUSINESS", "MEDIA_CREATOR", "CREATOR"):
                raise RuntimeError(f"account_type is {kind}; publishing needs Business or Creator")
            return f"@{data.get('username')} ({kind})"
        if not verify("account and token", account):
            return False
        return verify("publishing quota",
                      lambda: f"{ig.quota_used()}/25 used in the last 24h")

    try:
        section("telegram", telegram_section, values)
        section("r2", r2_section, values)
        section("instagram", instagram_section, values)
    except KeyboardInterrupt:
        write_env(values)
        print(f"\n\nStopped. Saved what you entered to {ENV_FILE}.")
        return 1

    write_env(values)
    print(f"\n{GREEN}{BOLD}Saved to {ENV_FILE}{RESET} (chmod 600)")
    print(f"\nNext:\n  {BOLD}{HERE}/install.sh{RESET}      install the launchd jobs")
    print(f"  {BOLD}.venv/bin/python backfill.py{RESET}   warm the portrait cache")

    if input("\nRun doctor.py now? [Y/n]: ").strip().lower() not in ("n", "no"):
        subprocess.run([str(HERE / ".venv/bin/python"), str(HERE / "doctor.py")],
                       env={**os.environ, "SCIG_ENV_FILE": str(ENV_FILE)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
