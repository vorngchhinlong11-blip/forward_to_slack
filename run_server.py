"""Headless runner for servers (no GUI).

Usage (run from the project folder):
    python run_server.py           # forward messages until stopped
    python run_server.py --check   # verify Slack + Telegram login, then exit
    python run_server.py --login   # log in to Telegram interactively (over SSH)

Groups, keys and thread cache are read from data/config.json and
data/thread_cache.json; the Telegram login from telegram_session.session.
"""
import argparse
import asyncio
import os
import sys

from telethon import TelegramClient

from config import Config
from message_forwarder import MessageForwarder
from notifier import Notifier
from slack_handler import SlackHandler

# Exit code used when Telegram is not logged in. The systemd service is told
# not to restart on this code, so it won't keep asking Telegram for codes.
EXIT_NOT_LOGGED_IN = 3

SESSION_NAME = "telegram_session"


def _telegram_client(config: Config) -> TelegramClient:
    tg = config.get_telegram_config()
    if not tg.get("api_id") or not tg.get("api_hash"):
        print("ERROR: Telegram API ID / API Hash missing in data/config.json", flush=True)
        sys.exit(2)
    return TelegramClient(SESSION_NAME, int(tg["api_id"]), tg["api_hash"])


async def _is_logged_in(config: Config) -> bool:
    client = _telegram_client(config)
    await client.connect()
    try:
        return await client.is_user_authorized()
    finally:
        await client.disconnect()


async def login(config: Config) -> None:
    """Interactive login: prompts for the code (and 2FA password) in the terminal."""
    client = _telegram_client(config)
    await client.start(phone=config.get_telegram_config().get("phone"))
    me = await client.get_me()
    print(f"Logged in to Telegram as {me.first_name} (@{me.username})", flush=True)
    await client.disconnect()


async def check(config: Config) -> int:
    ok = True
    if SlackHandler(config).connect():
        print("Slack: OK", flush=True)
    else:
        print("Slack: FAILED (check the bot token)", flush=True)
        ok = False

    if await _is_logged_in(config):
        print("Telegram: OK (logged in)", flush=True)
    else:
        print("Telegram: NOT LOGGED IN - run: python run_server.py --login", flush=True)
        ok = False

    enabled = [g for g in config.get_groups() if g.get("enabled")]
    print(f"Groups: {len(enabled)} enabled / {len(config.get_groups())} total", flush=True)
    return 0 if ok else 1


async def serve(config: Config) -> int:
    if not await _is_logged_in(config):
        print("ERROR: Telegram is not logged in. Stop the service and run:\n"
              "  python run_server.py --login", flush=True)
        return EXIT_NOT_LOGGED_IN

    enabled = [g for g in config.get_groups() if g.get("enabled")]
    print(f"Starting forwarder for {len(enabled)} enabled group(s)", flush=True)

    notifier = Notifier(config.get_notify_config)
    forwarder = MessageForwarder(config)
    try:
        await forwarder.start()
        notifier.send(f"✅ Forwarding started on the server ({len(enabled)} groups)")
        notifier.start_heartbeat(lambda: forwarder.telegram_handler.client.is_connected())
        await forwarder.telegram_handler.run_until_disconnected()
    except Exception as e:
        notifier.send(f"❌ Server forwarding stopped because of an error:\n{e}\n"
                      "The service will restart automatically.", wait=True)
        raise
    finally:
        notifier.stop_heartbeat()
        if forwarder.is_running:
            await forwarder.stop()

    # run_until_disconnected() returned: connection lost. Exit non-zero so
    # systemd restarts the service with a fresh connection.
    print("Disconnected from Telegram - exiting so the service restarts", flush=True)
    notifier.send("⚠️ Server lost the connection to Telegram - restarting automatically.", wait=True)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram to Slack forwarder (headless)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify setup and exit")
    mode.add_argument("--login", action="store_true", help="log in to Telegram interactively")
    args = parser.parse_args()

    # Always work from the project folder so data/ and the session file are found
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    config = Config()

    if args.login:
        asyncio.run(login(config))
    elif args.check:
        sys.exit(asyncio.run(check(config)))
    else:
        try:
            sys.exit(asyncio.run(serve(config)))
        except KeyboardInterrupt:
            print("Stopped", flush=True)


if __name__ == "__main__":
    main()
