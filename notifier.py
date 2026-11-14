"""Status alerts through your own Telegram bot, plus an optional heartbeat.

- Telegram bot: messages you when forwarding starts, stops, fails, loses its
  Telegram connection, when the computer goes to sleep / wakes up, and when
  the connection comes back. Alerts that can't be sent (e.g. no internet) are
  kept and retried until they get through, marked as delayed.
- Heartbeat (optional): while forwarding, pings a monitoring URL (e.g.
  https://healthchecks.io) every few minutes. If the computer is off, asleep
  or offline, the pings stop and the monitoring service alerts you - the one
  case this app can't report in real time itself.

Settings live in data/config.json under "notify" (never committed):
    {"bot_token": "...", "chat_id": "...", "heartbeat_url": "..."}
All network calls run in background threads and never raise.
"""
import collections
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Callable, Optional, Tuple

WATCH_INTERVAL = 20         # seconds between sleep/connection checks
SLEEP_GAP = 90              # a clock jump longer than this means the computer was asleep
DISCONNECT_ALERT_AFTER = 60  # seconds offline before alerting
HEARTBEAT_INTERVAL = 300    # seconds between heartbeat pings
RETRY_INTERVAL = 30         # seconds between retries of unsent alerts
MAX_ALERT_AGE = 24 * 3600   # drop unsent alerts older than this
HTTP_TIMEOUT = 15
SUSPEND_SEND_TIMEOUT = 4    # Windows only waits briefly before sleeping


def _api(token: str, method: str, params: Optional[dict] = None, timeout: float = HTTP_TIMEOUT) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode() if params else None
    try:
        with urllib.request.urlopen(url, data=data, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        if e.code in (401, 404):
            raise RuntimeError("Invalid bot token - copy it again from @BotFather")
        if e.code == 400 and "chat not found" in str(body.get("description", "")).lower():
            raise RuntimeError("Chat not found - open your bot in Telegram and press Start")
        raise RuntimeError(body.get("description") or f"HTTP {e.code}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Can't reach Telegram (no internet?): {e.reason}")


def find_chat_id(bot_token: str) -> Tuple[str, str]:
    """Return (chat_id, name) of the latest chat that messaged the bot.

    The user must first open their bot in Telegram and press Start / send any message.
    """
    result = _api(bot_token.strip(), "getUpdates").get("result", [])
    for update in reversed(result):
        msg = update.get("message") or update.get("my_chat_member") or {}
        chat = msg.get("chat")
        if chat:
            name = chat.get("title") or " ".join(
                filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username", "")
            return str(chat["id"]), name
    raise RuntimeError("No messages found. Open your bot in Telegram, press Start "
                       "(or send it any message), then try again.")


def _hm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "less than a minute"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


class Notifier:
    def __init__(self, get_settings: Callable[[], dict]):
        # get_settings is called each time so changes apply without restarting
        self._get_settings = get_settings
        self.host = socket.gethostname()
        self._outbox = collections.deque()      # (created_ts, text) waiting to be sent
        self._outbox_lock = threading.Lock()
        self._outbox_wake = threading.Event()
        self._sender: Optional[threading.Thread] = None
        self._watch_stop: Optional[threading.Event] = None
        self._monitoring = False
        self._power_hook = None
        self._register_power_events()

    # ---- Telegram bot -----------------------------------------------------
    @property
    def enabled(self) -> bool:
        s = self._get_settings()
        return bool(s.get("bot_token") and s.get("chat_id"))

    def send(self, text: str, wait: bool = False, timeout: float = HTTP_TIMEOUT) -> None:
        """Send an alert. If it can't be sent now, it is retried until it gets through.

        wait=True tries once immediately (e.g. while the app is closing or the
        computer is about to sleep) before falling back to the retry queue.
        """
        if not self.enabled:
            return
        created = time.time()
        if wait and self._try_send(created, text, timeout):
            return
        with self._outbox_lock:
            self._outbox.append((created, text))
        self._ensure_sender()
        self._outbox_wake.set()

    def send_test(self, bot_token: str, chat_id: str) -> None:
        """Send a test message; raises with a readable error on failure."""
        _api(bot_token.strip(), "sendMessage", {
            "chat_id": chat_id.strip(),
            "text": f"✅ Test from Telegram to Slack Forwarder on {self.host}. Alerts will arrive here.",
        })

    def _format(self, created: float, text: str) -> str:
        footer = f"🖥 {self.host} · {datetime.fromtimestamp(created).strftime('%Y-%m-%d %H:%M')}"
        if time.time() - created > 120:
            footer += f"\n⏱ Delayed alert (no internet until {_hm(time.time())})"
        return f"{text}\n\n{footer}"

    def _try_send(self, created: float, text: str, timeout: float = HTTP_TIMEOUT) -> bool:
        s = self._get_settings()
        if not (s.get("bot_token") and s.get("chat_id")):
            return True  # alerts were turned off - nothing to deliver
        try:
            _api(s["bot_token"].strip(), "sendMessage", {
                "chat_id": str(s["chat_id"]).strip(),
                "text": self._format(created, text),
            }, timeout=timeout)
            return True
        except Exception as e:
            print(f"[notify] Telegram alert not sent yet, will retry: {e}", flush=True)
            return False

    def _ensure_sender(self) -> None:
        if self._sender and self._sender.is_alive():
            return
        self._sender = threading.Thread(target=self._sender_loop, daemon=True)
        self._sender.start()

    def _sender_loop(self) -> None:
        while True:
            with self._outbox_lock:
                item = self._outbox[0] if self._outbox else None
            if item is None:
                self._outbox_wake.wait()
                self._outbox_wake.clear()
                continue
            created, text = item
            if time.time() - created > MAX_ALERT_AGE or self._try_send(created, text):
                with self._outbox_lock:
                    if self._outbox and self._outbox[0] is item:
                        self._outbox.popleft()
            else:
                # Offline: wait, then retry in order (oldest first)
                self._outbox_wake.wait(RETRY_INTERVAL)
                self._outbox_wake.clear()

    # ---- Watching: sleep, connection, heartbeat ----------------------------
    def start_heartbeat(self, is_connected: Optional[Callable[[], bool]] = None) -> None:
        """Start watching while forwarding.

        - Detects the computer sleeping (clock jumps) and reports it on wake-up
        - Reports Telegram connection drops longer than a minute, and recovery
        - Pings the heartbeat URL, if one is set
        """
        self.stop_heartbeat()
        stop = threading.Event()
        self._watch_stop = stop
        self._monitoring = True
        threading.Thread(target=self._watch_loop, args=(stop, is_connected), daemon=True).start()

    def stop_heartbeat(self) -> None:
        self._monitoring = False
        if self._watch_stop:
            self._watch_stop.set()
            self._watch_stop = None

    def _watch_loop(self, stop: threading.Event, is_connected: Optional[Callable[[], bool]]) -> None:
        last = time.time()   # wall clock: keeps counting while the computer sleeps
        last_ping = 0.0
        down_since: Optional[float] = None
        down_alerted = False
        grace_until = 0.0    # ignore connection drops right after waking up

        while True:
            now = time.time()
            gap = now - last
            last = now

            if gap > SLEEP_GAP:
                asleep_from = now - gap
                self.send(f"😴 The computer was asleep or frozen for {_duration(gap)} "
                          f"({_hm(asleep_from)}–{_hm(now)}). Forwarding was paused.\n"
                          f"☀️ It's awake again and forwarding resumes automatically. "
                          f"Check Telegram for messages from that time.")
                down_since, down_alerted = None, False
                grace_until = now + 2 * DISCONNECT_ALERT_AFTER  # reconnecting takes a moment

            if is_connected is not None:
                try:
                    connected = bool(is_connected())
                except Exception:
                    connected = False
                if not connected and now >= grace_until:
                    if down_since is None:
                        down_since = now
                    elif not down_alerted and now - down_since >= DISCONNECT_ALERT_AFTER:
                        self.send(f"⚠️ Lost the connection to Telegram at {_hm(down_since)} "
                                  f"(no internet?). Forwarding is paused and reconnecting…")
                        down_alerted = True
                elif connected and down_since is not None:
                    if down_alerted:
                        self.send(f"✅ Connection to Telegram is back after {_duration(now - down_since)} "
                                  f"({_hm(down_since)}–{_hm(now)}). Forwarding resumed.\n"
                                  f"Check Telegram for messages from that time.")
                    down_since, down_alerted = None, False

            if now - last_ping >= HEARTBEAT_INTERVAL:
                last_ping = now
                self._ping()

            if stop.wait(WATCH_INTERVAL):
                return

    def _ping(self) -> None:
        url = (self._get_settings().get("heartbeat_url") or "").strip()
        if not url:
            return
        try:
            urllib.request.urlopen(url, timeout=HTTP_TIMEOUT).close()
        except Exception as e:
            print(f"[notify] Heartbeat ping failed: {e}", flush=True)

    # ---- Windows: message right before the computer goes to sleep ----------
    def _on_suspend(self) -> None:
        if self._monitoring:
            self.send("😴 The computer is going to sleep - forwarding is paused until it wakes up.",
                      wait=True, timeout=SUSPEND_SEND_TIMEOUT)

    def _register_power_events(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            PBT_APMSUSPEND = 0x4
            DEVICE_NOTIFY_CALLBACK = 2
            CALLBACK = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p)

            class SUBSCRIBE_PARAMS(ctypes.Structure):
                _fields_ = [("Callback", CALLBACK), ("Context", ctypes.c_void_p)]

            def callback(context, event_type, setting):
                try:
                    if event_type == PBT_APMSUSPEND:
                        self._on_suspend()
                except Exception:
                    pass
                return 0

            cb = CALLBACK(callback)
            params = SUBSCRIBE_PARAMS(cb, None)
            handle = ctypes.c_void_p()
            result = ctypes.windll.powrprof.PowerRegisterSuspendResumeNotification(
                DEVICE_NOTIFY_CALLBACK, ctypes.byref(params), ctypes.byref(handle))
            if result == 0:
                self._power_hook = (cb, params, handle)  # keep alive for the app's lifetime
            else:
                print(f"[notify] Sleep notifications unavailable (code {result})", flush=True)
        except Exception as e:
            print(f"[notify] Sleep notifications unavailable: {e}", flush=True)
