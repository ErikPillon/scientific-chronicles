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


class Invalid(ValueError):
    """Input is the wrong shape — say what was expected and where to find it."""


def v_chat_id(value: str) -> str:
    if not value.lstrip("-").isdigit():
        raise Invalid("must be numeric — the id, not your @username")
    if len(value.lstrip("-")) < 6:
        raise Invalid(f"{value!r} is too short for a Telegram id (they run ~9-10 digits)")
    return value


def v_account_id(value: str) -> str:
    if value.startswith("http"):
        match = re.search(r"dash\.cloudflare\.com/([0-9a-f]{32})", value)
        if match:
            raise Invalid(f"that is a dashboard URL — the account id inside it "
                          f"is {match.group(1)}")
        raise Invalid("that is a URL, not the account id. R2 sidebar > Account ID, "
                      "32 hex characters")
    if not re.fullmatch(r"[0-9a-f]{32}", value):
        raise Invalid("expected 32 hex characters (R2 sidebar > Account ID)")
    return value


def v_public_base(value: str) -> str:
    if "dash.cloudflare.com" in value:
        raise Invalid("that is the dashboard page, not the public bucket URL. "
                      "Bucket > Settings > Public access, or your custom domain")
    if not value.startswith("https://"):
        raise Invalid("must start with https://")
    return value.rstrip("/")


def v_ig_user_id(value: str) -> str:
    if not value.isdigit():
        raise Invalid(f"{value!r} looks like a handle — this needs the numeric id")
    return value


def ask(key: str, prompt: str, values: dict[str, str], *,
        secret: bool = False, default: str = "", validate=None) -> str:
    current = values.get(key, "") or default
    if current:
        shown = f"{current[:6]}…{current[-4:]}" if secret and len(current) > 14 else current
        suffix = f" [{shown}]"
    else:
        suffix = ""
    while True:
        raw = (getpass.getpass(f"  {prompt}{suffix}: ") if secret
               else input(f"  {prompt}{suffix}: ")).strip()
        candidate = raw or current
        if not candidate:
            print(f"  {RED}required{RESET}")
            continue
        if validate:
            try:
                candidate = validate(candidate)
            except Invalid as exc:
                print(f"  {RED}{exc}{RESET}")
                if not raw:
                    current = ""          # stored value is bad; force a new one
                continue
        values[key] = candidate
        return candidate


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
        apply(values)
        import telegram as tg

        # Offer to read the id straight off a message rather than make them hunt.
        detected = ""
        try:
            for update in tg.call("getUpdates", limit=10):
                chat = (update.get("message") or update.get("callback_query", {})
                        .get("message") or {}).get("chat") or {}
                if chat.get("id"):
                    detected = str(chat["id"])
        except Exception:
            pass
        if detected:
            print(f"  {GREEN}detected chat id {detected}{RESET} from a recent message")
        ask("SCIG_TELEGRAM_CHAT_ID", "your numeric chat id", values,
            default=detected or values.get("SCIG_TELEGRAM_CHAT_ID", ""),
            validate=v_chat_id)
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
        ask("SCIG_R2_ACCOUNT_ID", "account id (32 hex chars)", values,
            validate=v_account_id)
        ask("SCIG_R2_ACCESS_KEY_ID", "access key id", values, secret=True)
        ask("SCIG_R2_SECRET_ACCESS_KEY", "secret access key", values, secret=True)
        ask("SCIG_R2_BUCKET", "bucket name", values,
            default=values.get("SCIG_R2_BUCKET", "scientific-chronicles-ig"))
        ask("SCIG_R2_PUBLIC_BASE", "public base URL (https://…)", values,
            validate=v_public_base)
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
        token = ask("SCIG_IG_ACCESS_TOKEN", "long-lived access token", values, secret=True)

        # Token prefix says which API this is. Sending an Instagram-Login token
        # to graph.facebook.com fails with an unhelpful "cannot parse" error.
        instagram_login = token.startswith("IG")
        values["SCIG_IG_API_BASE"] = (
            "https://graph.instagram.com/v23.0" if instagram_login
            else "https://graph.facebook.com/v23.0")
        print(f"  {GREEN}token is {'Instagram Login' if instagram_login else 'Facebook Login'}"
              f"{RESET} — using {values['SCIG_IG_API_BASE']}")
        apply(values)
        import requests as _rq

        # Ask the API for the numeric id rather than making them find it.
        detected = ""
        try:
            if instagram_login:
                data = _rq.get("https://graph.instagram.com/v23.0/me",
                               params={"fields": "user_id,username",
                                       "access_token": token}, timeout=30).json()
                detected = str(data.get("user_id", "") or "")
                if detected:
                    print(f"  {GREEN}detected @{data.get('username')} "
                          f"({detected}){RESET}")
        except Exception:
            pass
        ask("SCIG_IG_USER_ID", "instagram business user id (numeric)", values,
            default=detected or values.get("SCIG_IG_USER_ID", ""),
            validate=v_ig_user_id)

        if not instagram_login:
            # Only the Facebook flow needs an app id/secret to refresh a token.
            ask("SCIG_META_APP_ID", "meta app id", values)
            ask("SCIG_META_APP_SECRET", "meta app secret", values, secret=True)
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
