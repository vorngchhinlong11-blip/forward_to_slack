import flet as ft
import asyncio
import os
from config import Config
from git_backup import GitBackup
from notifier import Notifier, find_chat_id
import sys
import time

RECONNECT_DELAY = 30  # seconds between reconnect attempts after a lost connection

# Exit codes understood by run_windows.bat
EXIT_UNEXPECTED = 3        # closed without the user closing the window -> restart
EXIT_ALREADY_RUNNING = 10  # another copy is running -> don't restart
APP_STATE = {"user_closed": False}
from message_forwarder import MessageForwarder

class TelegramToSlackGUI:
    """Flet GUI application"""

    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "Telegram to Slack Forwarder"
        self.page.window.width = 900
        self.page.window.height = 700
        self.page.theme_mode = ft.ThemeMode.SYSTEM
        self.page.scroll = ft.ScrollMode.AUTO

        self.config = Config()
        self.notifier = Notifier(self.config.get_notify_config)
        self._stop_requested = False

        # Back up groups.json to GitHub automatically whenever groups change
        self.git_backup = GitBackup(
            repo_dir=os.path.dirname(os.path.abspath(__file__)),
            on_status=self._show_backup_status,
        )
        if self.config.config_data.get("git_backup", True):
            self.config.on_groups_changed = self.git_backup.schedule
        # Intercept closing so a pending backup can finish first
        self.page.window.prevent_close = True
        self.page.window.on_event = self._on_window_event
        self.forwarder = MessageForwarder(self.config)
        self.is_forwarding = False

        # UI components
        self.status_text = ft.Text("Stopped", size=16, weight=ft.FontWeight.BOLD)
        self.group_list = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
        self.group_search_field = ft.TextField(
            hint_text="Search groups / channels",
            prefix_icon=ft.Icons.SEARCH,
            width=300,
            height=40,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=0),
            border_radius=20,
            on_change=lambda e: self._refresh_group_list(),
            suffix=ft.IconButton(
                icon=ft.Icons.CLOSE,
                icon_size=16,
                tooltip="Clear",
                on_click=self._clear_group_search,
            ),
        )

        self._build_ui()
        self._maybe_resume_forwarding()

    def _build_ui(self):
        """Build the UI"""
        # Header
        header = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.TELEGRAM, size=40, color=ft.Colors.BLUE),
                ft.Text("→", size=30),
                ft.Icon(ft.Icons.TAG, size=40, color=ft.Colors.PURPLE),
                ft.Text("Telegram to Slack", size=24, weight=ft.FontWeight.BOLD),
            ], alignment=ft.MainAxisAlignment.CENTER),
            padding=20,
        )

        # Status bar
        self.start_stop_btn = ft.ElevatedButton(
            "Start Forwarding",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._toggle_forwarding,
            bgcolor=ft.Colors.GREEN,
            color=ft.Colors.WHITE
        )

        status_bar = ft.Container(
            content=ft.Row([
                ft.Text("Status:", size=16),
                self.status_text,
                ft.Container(width=20),
                self.start_stop_btn,
            ], alignment=ft.MainAxisAlignment.START),
            padding=15,
        )

        # Toolbar
        toolbar = ft.Row([
            ft.ElevatedButton(
                "Add Group",
                icon=ft.Icons.ADD,
                on_click=self._show_add_group_dialog
            ),
            ft.ElevatedButton(
                "Telegram Settings",
                icon=ft.Icons.SETTINGS,
                on_click=self._show_telegram_settings
            ),
            ft.ElevatedButton(
                "Slack Settings",
                icon=ft.Icons.SETTINGS,
                on_click=self._show_slack_settings
            ),
            ft.ElevatedButton(
                "Alerts",
                icon=ft.Icons.NOTIFICATIONS,
                on_click=self._show_alert_settings
            ),
        ], spacing=10, wrap=True)

        # Group list
        group_section = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("Registered Groups", size=18, weight=ft.FontWeight.BOLD),
                    self.group_search_field,
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(),
                ft.Container(
                    content=self.group_list,
                    expand=True,
                )
            ]),
            padding=15,
            expand=True,
        )

        # Main layout
        self.page.add(
            header,
            status_bar,
            ft.Container(
                content=toolbar,
                padding=15,
            ),
            group_section,
        )

        self._refresh_group_list()

    def _refresh_group_list(self):
        """Refresh the group list"""
        self.group_list.controls.clear()

        groups = self.config.get_groups()
        query = (self.group_search_field.value or "").strip().lower()

        if not groups:
            self.group_list.controls.append(
                ft.Text("No groups registered", italic=True, color=ft.Colors.GREY)
            )
        else:
            if query:
                groups = [
                    g for g in groups
                    if query in g.get("telegram_group_name", "").lower()
                    or query in g.get("slack_channel_name", "").lower()
                    or query in (g.get("telegram_topic_name") or "").lower()
                ]
            if not groups:
                self.group_list.controls.append(
                    ft.Text("No matching groups", italic=True, color=ft.Colors.GREY)
                )
            for group in groups:
                self.group_list.controls.append(self._create_group_card(group))

        self.page.update()

    def _clear_group_search(self, e):
        """Clear the group search"""
        self.group_search_field.value = ""
        self._refresh_group_list()

    def _create_group_card(self, group: dict):
        """Create a group card"""
        enabled_icon = ft.Icon(
            ft.Icons.CHECK_CIRCLE if group["enabled"] else ft.Icons.CANCEL,
            color=ft.Colors.GREEN if group["enabled"] else ft.Colors.RED
        )

        thread_mode_text = {
            "daily": "Daily",
            "weekly": "Weekly",
            "single_message": "None"
        }.get(group.get("thread_mode", "daily"), "Daily")

        return ft.Card(
            content=ft.Container(
                content=ft.Column([
                    ft.Row([
                        enabled_icon,
                        ft.Column([
                            ft.Text(group["telegram_group_name"], size=16, weight=ft.FontWeight.BOLD),
                            *([ft.Row([
                                ft.Icon(ft.Icons.TAG, size=14, color=ft.Colors.BLUE),
                                ft.Text(f"Topic: {group.get('telegram_topic_name') or group['telegram_topic_id']}",
                                        size=12, color=ft.Colors.BLUE),
                            ], spacing=4)] if group.get("telegram_topic_id") is not None else []),
                            ft.Text(f"→ {group['slack_channel_name']}", size=12, color=ft.Colors.GREY),
                            ft.Text(f"Thread: {thread_mode_text}", size=11, italic=True),
                        ], expand=True),
                        ft.IconButton(
                            icon=ft.Icons.EDIT,
                            on_click=lambda e, g=group: self._show_edit_group_dialog(g)
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE,
                            on_click=lambda e, g=group: self._delete_group(g)
                        ),
                    ]),
                ]),
                padding=15,
            )
        )

    def _show_add_group_dialog(self, e):
        """Show the add group dialog"""
        # Check Telegram/Slack settings
        if not self.config.is_telegram_configured():
            self._show_error("Please complete the Telegram settings first")
            return
        if not self.config.is_slack_configured():
            self._show_error("Please complete the Slack settings first")
            return

        self._show_group_dialog(None)

    def _show_edit_group_dialog(self, group: dict):
        """Show the edit group dialog"""
        self._show_group_dialog(group)

    def _show_group_dialog(self, group: dict = None):
        """Add/edit group dialog"""
        is_edit = group is not None

        # Loading indicator
        loading_text = ft.Text("Loading...", italic=True, color=ft.Colors.GREY)

        # Lists holding the options
        all_tg_options = []
        all_slack_options = []

        # Fields
        tg_group_dropdown = ft.Dropdown(
            label="Telegram Group",
            width=400,
            hint_text="Loading...",
            disabled=True
        )

        slack_channel_dropdown = ft.Dropdown(
            label="Slack Channel",
            width=400,
            hint_text="Loading...",
            disabled=True
        )

        # Topic picker - only shown for Telegram groups that use topics
        ALL_TOPICS = "all"
        forum_ids = set()  # chat IDs of groups with topics
        topic_dropdown = ft.Dropdown(
            label="Telegram Topic",
            width=400,
            visible=False,
            value=ALL_TOPICS,
            options=[ft.dropdown.Option(ALL_TOPICS, "All topics")],
        )
        topic_status = ft.Text("", size=11, color=ft.Colors.GREY, visible=False)

        async def load_topics(chat_id: int, selected_topic=None):
            topic_dropdown.visible = topic_status.visible = True
            topic_dropdown.disabled = True
            topic_dropdown.options = [ft.dropdown.Option(ALL_TOPICS, "All topics")]
            topic_dropdown.value = ALL_TOPICS
            topic_status.value = "Loading topics..."
            self.page.update()
            try:
                topics = await self.forwarder.get_forum_topics(
                    chat_id,
                    code_callback=self._request_telegram_code,
                    password_callback=self._request_telegram_password
                )
                topic_dropdown.options += [
                    ft.dropdown.Option(str(t["id"]), t["title"]) for t in topics
                ]
                if selected_topic is not None:
                    key = str(selected_topic)
                    if not any(o.key == key for o in topic_dropdown.options):
                        # Topic was deleted/renamed in Telegram - keep the saved one visible
                        topic_dropdown.options.append(ft.dropdown.Option(key, group.get("telegram_topic_name") or key))
                    topic_dropdown.value = key
                topic_status.value = "All topics = the whole group. Pick one topic to forward only that topic."
            except Exception as ex:
                topic_status.value = f"Failed to load topics: {ex}"
            topic_dropdown.disabled = False
            self.page.update()

        def on_tg_group_change(e):
            value = tg_group_dropdown.value
            if value and int(value) in forum_ids:
                self.page.run_task(load_topics, int(value))
            else:
                topic_dropdown.visible = topic_status.visible = False
                topic_dropdown.value = ALL_TOPICS
                self.page.update()

        tg_group_dropdown.on_change = on_tg_group_change

        # Search fields
        def filter_tg_options(e):
            search_text = e.control.value.lower()
            if search_text:
                tg_group_dropdown.options = [
                    opt for opt in all_tg_options
                    if search_text in opt.text.lower()
                ]
            else:
                tg_group_dropdown.options = all_tg_options.copy()
            self.page.update()

        def filter_slack_options(e):
            search_text = e.control.value.lower()
            if search_text:
                slack_channel_dropdown.options = [
                    opt for opt in all_slack_options
                    if search_text in opt.text.lower()
                ]
            else:
                slack_channel_dropdown.options = all_slack_options.copy()
            self.page.update()

        tg_search_field = ft.TextField(
            label="Search Telegram",
            width=400,
            prefix_icon=ft.Icons.SEARCH,
            on_change=filter_tg_options,
            hint_text="Search by group name..."
        )

        slack_search_field = ft.TextField(
            label="Search Slack",
            width=400,
            prefix_icon=ft.Icons.SEARCH,
            on_change=filter_slack_options,
            hint_text="Search by channel name..."
        )

        thread_mode_dropdown = ft.Dropdown(
            label="Thread Mode",
            width=400,
            value=group.get("thread_mode", "daily") if is_edit else "daily",
            options=[
                ft.dropdown.Option("daily", "Daily"),
                ft.dropdown.Option("weekly", "Weekly"),
                ft.dropdown.Option("single_message", "No Thread"),
            ]
        )

        enabled_switch = ft.Switch(
            label="Enabled",
            value=group.get("enabled", True) if is_edit else True
        )

        async def load_options():
            nonlocal all_tg_options, all_slack_options
            error_messages = []

            # Fetch Telegram groups
            try:
                tg_groups = await self.forwarder.get_telegram_groups(
                    code_callback=self._request_telegram_code,
                    password_callback=self._request_telegram_password
                )
                if tg_groups:
                    forum_ids.update(g["id"] for g in tg_groups if g.get("forum"))
                    all_tg_options = [
                        ft.dropdown.Option(str(g["id"]), g["name"] + ("  (topics)" if g.get("forum") else ""))
                        for g in tg_groups
                    ]
                    tg_group_dropdown.options = all_tg_options.copy()
                    tg_group_dropdown.hint_text = "Select a group"
                    tg_group_dropdown.disabled = False
                    if is_edit:
                        tg_group_dropdown.value = str(group["telegram_group_id"])
                        if group["telegram_group_id"] in forum_ids:
                            self.page.run_task(load_topics, group["telegram_group_id"],
                                               group.get("telegram_topic_id"))
                else:
                    error_messages.append("No Telegram groups found")
                    tg_group_dropdown.hint_text = "No groups found"
            except Exception as ex:
                error_msg = f"Failed to fetch Telegram groups: {str(ex)}"
                print(error_msg)
                error_messages.append(error_msg)
                tg_group_dropdown.hint_text = "Failed to load"

            # Fetch Slack channels
            try:
                slack_channels = self.forwarder.get_slack_channels()
                if slack_channels:
                    all_slack_options = [
                        ft.dropdown.Option(c["id"], c["name"]) for c in slack_channels
                    ]
                    slack_channel_dropdown.options = all_slack_options.copy()
                    slack_channel_dropdown.hint_text = "Select a channel"
                    slack_channel_dropdown.disabled = False
                    if is_edit:
                        slack_channel_dropdown.value = group["slack_channel_id"]
                else:
                    error_messages.append("No Slack channels found")
                    slack_channel_dropdown.hint_text = "No channels found"
            except Exception as ex:
                error_msg = f"Failed to fetch Slack channels: {str(ex)}"
                print(error_msg)
                error_messages.append(error_msg)
                slack_channel_dropdown.hint_text = "Failed to load"

            loading_text.value = "Loaded" if not error_messages else "An error occurred"
            loading_text.color = ft.Colors.GREEN if not error_messages else ft.Colors.RED

            if error_messages:
                loading_text.value = "\n".join(error_messages)

            self.page.update()

        def save_group(e):
            if not tg_group_dropdown.value or not slack_channel_dropdown.value:
                self._show_error("Please fill in all fields")
                return

            # Get the selected names
            tg_name = next(
                (opt.text for opt in all_tg_options if opt.key == tg_group_dropdown.value),
                ""
            ).removesuffix("  (topics)")
            if is_edit and not tg_name:
                tg_name = group["telegram_group_name"]

            # Topic (None = all topics)
            topic_id = topic_name = None
            if topic_dropdown.visible and topic_dropdown.value not in (None, ALL_TOPICS):
                topic_id = int(topic_dropdown.value)
                topic_name = next(
                    (opt.text for opt in topic_dropdown.options if opt.key == topic_dropdown.value), ""
                )
            slack_name = next(
                (opt.text for opt in slack_channel_dropdown.options if opt.key == slack_channel_dropdown.value),
                ""
            )

            if is_edit:
                # Update
                self.config.update_group(
                    group["id"],
                    telegram_group_id=int(tg_group_dropdown.value),
                    telegram_group_name=tg_name,
                    slack_channel_id=slack_channel_dropdown.value,
                    slack_channel_name=slack_name,
                    thread_mode=thread_mode_dropdown.value,
                    enabled=enabled_switch.value,
                    telegram_topic_id=topic_id,
                    telegram_topic_name=topic_name
                )
            else:
                # Add new
                self.config.add_group(
                    telegram_group_id=int(tg_group_dropdown.value),
                    telegram_group_name=tg_name,
                    slack_channel_id=slack_channel_dropdown.value,
                    slack_channel_name=slack_name,
                    thread_mode=thread_mode_dropdown.value,
                    telegram_topic_id=topic_id,
                    telegram_topic_name=topic_name
                )

            dialog.open = False
            self.page.update()
            self._refresh_group_list()

        dialog = ft.AlertDialog(
            title=ft.Text("Edit Group" if is_edit else "Add Group"),
            content=ft.Column([
                loading_text,
                tg_search_field,
                tg_group_dropdown,
                topic_dropdown,
                topic_status,
                slack_search_field,
                slack_channel_dropdown,
                thread_mode_dropdown,
                enabled_switch if is_edit else ft.Container(),
            ], tight=True, height=450, scroll=ft.ScrollMode.AUTO),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: setattr(dialog, 'open', False) or self.page.update()),
                ft.TextButton("Save", on_click=save_group),
            ],
        )

        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

        # Load options asynchronously
        self.page.run_task(load_options)

    def _delete_group(self, group: dict):
        """Delete a group"""
        def confirm_delete(e):
            self.config.delete_group(group["id"])
            dialog.open = False
            self.page.update()
            self._refresh_group_list()

        dialog = ft.AlertDialog(
            title=ft.Text("Confirm"),
            content=ft.Text(f"Delete {group['telegram_group_name']}?"),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: setattr(dialog, 'open', False) or self.page.update()),
                ft.TextButton("Delete", on_click=confirm_delete),
            ],
        )

        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _show_telegram_settings(self, e):
        """Telegram settings dialog"""
        tg_config = self.config.get_telegram_config()

        api_id_field = ft.TextField(
            label="API ID",
            value=tg_config.get("api_id", ""),
            width=400
        )
        api_hash_field = ft.TextField(
            label="API Hash",
            value=tg_config.get("api_hash", ""),
            width=400
        )
        phone_field = ft.TextField(
            label="Phone number (e.g. +81XXXXXXXXXX)",
            value=tg_config.get("phone", ""),
            width=400
        )

        def save_settings(e):
            if not api_id_field.value or not api_hash_field.value or not phone_field.value:
                self._show_error("Please fill in all fields")
                return

            self.config.set_telegram_config(
                api_id=api_id_field.value,
                api_hash=api_hash_field.value,
                phone=phone_field.value
            )

            dialog.open = False
            self.page.update()

            # Verify connection after saving settings
            self.page.run_task(self._verify_telegram_connection)

        dialog = ft.AlertDialog(
            title=ft.Text("Telegram Settings"),
            content=ft.Column([
                ft.Text("Get your API keys at https://my.telegram.org", size=12),
                api_id_field,
                api_hash_field,
                phone_field,
            ], tight=True, height=250),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: setattr(dialog, 'open', False) or self.page.update()),
                ft.TextButton("Save", on_click=save_settings),
            ],
        )

        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _show_slack_settings(self, e):
        """Slack settings dialog"""
        slack_config = self.config.get_slack_config()

        bot_token_field = ft.TextField(
            label="Bot Token (xoxb-...)",
            value=slack_config.get("bot_token", ""),
            width=400,
            password=True
        )

        def save_settings(e):
            if not bot_token_field.value:
                self._show_error("Please enter the Bot Token")
                return

            self.config.set_slack_config(bot_token=bot_token_field.value)

            dialog.open = False
            self.page.update()

        dialog = ft.AlertDialog(
            title=ft.Text("Slack Settings"),
            content=ft.Column([
                ft.Text("Enter your Slack App's Bot Token", size=12),
                bot_token_field,
            ], tight=True, height=150),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: setattr(dialog, 'open', False) or self.page.update()),
                ft.TextButton("Save", on_click=save_settings),
            ],
        )

        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _show_alert_settings(self, e):
        """Alert settings: your own Telegram bot + optional heartbeat URL"""
        notify = self.config.get_notify_config()

        token_field = ft.TextField(label="Bot Token (from @BotFather)", value=notify.get("bot_token", ""),
                                   width=420, password=True, can_reveal_password=True)
        chat_field = ft.TextField(label="Chat ID", value=notify.get("chat_id", ""), width=280)
        heartbeat_field = ft.TextField(
            label="Heartbeat URL (optional, e.g. https://hc-ping.com/...)",
            value=notify.get("heartbeat_url", ""), width=420)
        status = ft.Text("", size=12)

        def set_status(text, ok=True):
            status.value = text
            status.color = ft.Colors.GREEN if ok else ft.Colors.RED
            self.page.update()

        def detect_chat(e):
            if not token_field.value.strip():
                set_status("Enter the bot token first", ok=False)
                return
            set_status("Looking for your chat...")
            try:
                chat_id, name = find_chat_id(token_field.value)
                chat_field.value = chat_id
                set_status(f"Found chat: {name or chat_id}")
            except Exception as ex:
                set_status(str(ex), ok=False)

        def send_test(e):
            if not token_field.value.strip() or not chat_field.value.strip():
                set_status("Enter the bot token and chat ID first", ok=False)
                return
            set_status("Sending test message...")
            try:
                self.notifier.send_test(token_field.value, chat_field.value)
                set_status("Test message sent - check Telegram")
            except Exception as ex:
                set_status(f"Failed: {ex}", ok=False)

        def save_settings(e):
            self.config.set_notify_config(token_field.value, chat_field.value, heartbeat_field.value)
            dialog.open = False
            self.page.update()
            if self.is_forwarding:
                self.notifier.start_heartbeat(self._telegram_connected)  # apply a new heartbeat URL right away

        dialog = ft.AlertDialog(
            title=ft.Text("Alerts"),
            content=ft.Column([
                ft.Text("Get a Telegram message when forwarding starts, stops or fails.", size=12),
                ft.Text("1. In Telegram, open @BotFather, send /newbot and copy the token.\n"
                        "2. Open your new bot and press Start.\n"
                        "3. Paste the token, click Find, then Send test.", size=12, color=ft.Colors.GREY),
                token_field,
                ft.Row([chat_field, ft.TextButton("Find", icon=ft.Icons.SEARCH, on_click=detect_chat)]),
                ft.Divider(),
                ft.Text("If the laptop shuts down or loses power, the app can't send anything. "
                        "For that, create a free check at healthchecks.io (Period 5 min, Grace 10 min), "
                        "connect it to Telegram there, and paste its ping URL:", size=12, color=ft.Colors.GREY),
                heartbeat_field,
                status,
            ], tight=True, width=440, scroll=ft.ScrollMode.AUTO),
            actions=[
                ft.TextButton("Send test", on_click=send_test),
                ft.TextButton("Cancel", on_click=lambda e: setattr(dialog, 'open', False) or self.page.update()),
                ft.TextButton("Save", on_click=save_settings),
            ],
        )

        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _telegram_connected(self) -> bool:
        """Whether the forwarding Telegram client is currently connected"""
        client = self.forwarder.telegram_handler.client
        return bool(client and client.is_connected())

    def _toggle_forwarding(self, e):
        """Start/stop forwarding"""
        # Disable the button to prevent double clicks
        self.start_stop_btn.disabled = True
        self.page.update()

        if not self.is_forwarding:
            # Start
            if not self.config.get_groups():
                self._show_error("No groups registered")
                self.start_stop_btn.disabled = False
                self.page.update()
                return

            self.page.run_task(self._start_forwarding)
        else:
            # Stop (requested by the user, so it isn't reported as a failure)
            self._stop_requested = True
            self.page.run_task(self._stop_forwarding)

    def _set_status(self, text: str, color):
        self.status_text.value = text
        self.status_text.color = color
        self.page.update()

    async def _wait_unless_stopped(self, seconds: float) -> bool:
        """Sleep, but wake early if the user clicks Stop. Returns True if stopped."""
        end = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < end:
            if self._stop_requested:
                return True
            await asyncio.sleep(0.5)
        return self._stop_requested

    def _set_forwarding_active(self, active: bool):
        """Remember whether forwarding should run, so it resumes after a restart"""
        if self.config.config_data.get("forwarding_active") != active:
            self.config.config_data["forwarding_active"] = active
            self.config.save_config()

    def _maybe_resume_forwarding(self):
        """Start forwarding automatically when the app opens.

        Skipped only if the user clicked Stop Forwarding last time, or if
        Telegram/Slack aren't set up yet.
        """
        active = self.config.config_data.get("forwarding_active")
        if active is None:  # never started or stopped yet: start if everything is set up
            active = self.config.is_telegram_configured() and self.config.is_slack_configured()
        if not active or not self.config.get_groups():
            return
        self.start_stop_btn.disabled = True
        self._set_status("Resuming...", ft.Colors.ORANGE)
        reason = ("after the app closed unexpectedly" if "--restarted" in sys.argv
                  else "when the app opened")
        self.page.run_task(self._start_forwarding, reason)

    async def _start_forwarding(self, resume_reason: str = None):
        """Start forwarding, and keep reconnecting if the connection is lost

        resume_reason is set when resuming automatically; then a failed start
        keeps retrying (e.g. the internet isn't ready yet right after boot).
        """
        self._stop_requested = False
        lost_at = None      # when the connection was lost (None = connected)
        attempts = 0
        keep_trying = resume_reason is not None
        if keep_trying:
            # Let Stop work while still trying to resume
            self.is_forwarding = True
            self.start_stop_btn.text = "Stop Forwarding"
            self.start_stop_btn.icon = ft.Icons.STOP
            self.start_stop_btn.bgcolor = ft.Colors.RED
            self.start_stop_btn.disabled = False
            self.page.update()

        while not self._stop_requested:
            # --- connect ------------------------------------------------------
            try:
                await self.forwarder.start(
                    code_callback=self._request_telegram_code,
                    password_callback=self._request_telegram_password
                )
            except Exception as ex:
                if self._stop_requested:
                    return  # errors while the user is stopping aren't failures
                if lost_at is None and not keep_trying:
                    # First manual start failed (bad settings, no internet...): give up
                    self.notifier.send(f"❌ Forwarding failed to start:\n{ex}")
                    self._show_error(f"Failed to start forwarding: {ex}")
                    await self._stop_forwarding()
                    return
                # Reconnecting after a lost connection: keep trying
                attempts += 1
                print(f"Reconnect attempt {attempts} failed: {ex}")
                self._set_status(f"Reconnecting... (attempt {attempts})", ft.Colors.ORANGE)
                if await self._wait_unless_stopped(RECONNECT_DELAY):
                    return
                continue

            # --- connected ----------------------------------------------------
            enabled = sum(1 for g in self.config.get_groups() if g.get("enabled"))
            if keep_trying:
                keep_trying = False  # resumed; from now on behave like a normal run
                self.notifier.send(f"🔄 Forwarding resumed automatically {resume_reason} ({enabled} groups)")
            elif not self.is_forwarding:
                self.is_forwarding = True
                self.start_stop_btn.text = "Stop Forwarding"
                self.start_stop_btn.icon = ft.Icons.STOP
                self.start_stop_btn.bgcolor = ft.Colors.RED
                self.start_stop_btn.disabled = False
                self.notifier.send(f"✅ Forwarding started ({enabled} groups)")
            elif lost_at is not None:
                minutes = max(1, int((time.time() - lost_at) // 60))
                self.notifier.send(f"✅ Reconnected to Telegram after about {minutes} min - "
                                   f"forwarding resumed.\nCheck Telegram for messages from that time.")
            lost_at, attempts = None, 0
            self._set_forwarding_active(True)
            self._set_status("Forwarding", ft.Colors.GREEN)
            self.notifier.start_heartbeat(self._telegram_connected)

            # Runs until the connection ends (Stop button, or connection lost)
            try:
                await self.forwarder.telegram_handler.run_until_disconnected()
            except Exception as ex:
                print(f"Connection error: {ex}")
            if self._stop_requested:
                return

            # --- connection lost: reconnect automatically ----------------------
            lost_at = time.time()
            self.notifier.stop_heartbeat()  # heartbeat stops so healthchecks.io notices too
            self.notifier.send("⚠️ Lost the connection to Telegram (internet down or the computer "
                               "was asleep). Forwarding is paused - reconnecting automatically "
                               f"every {RECONNECT_DELAY} s.")
            self._set_status("Reconnecting...", ft.Colors.ORANGE)
            try:
                await self.forwarder.stop()
            except Exception:
                pass
            if await self._wait_unless_stopped(5):
                return

    async def _stop_forwarding(self):
        """Stop forwarding"""
        was_forwarding = self.is_forwarding
        self.notifier.stop_heartbeat()
        if self._stop_requested:
            self._set_forwarding_active(False)  # don't resume on the next start
            if was_forwarding:
                self.notifier.send("⏹ Forwarding stopped (Stop Forwarding button).")
        try:
            await self.forwarder.stop()
        except Exception as ex:
            print(f"Error while stopping: {ex}")
        self.is_forwarding = False
        self.status_text.value = "Stopped"
        self.status_text.color = ft.Colors.GREY
        self.start_stop_btn.text = "Start Forwarding"
        self.start_stop_btn.icon = ft.Icons.PLAY_ARROW
        self.start_stop_btn.bgcolor = ft.Colors.GREEN
        self.start_stop_btn.disabled = False
        self.page.update()

    async def _verify_telegram_connection(self):
        """Verify the Telegram connection"""
        try:
            # Show progress dialog
            progress_dialog = ft.AlertDialog(
                title=ft.Text("Connecting"),
                content=ft.Column([
                    ft.ProgressRing(),
                    ft.Text("Connecting to Telegram..."),
                ], tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            )
            self.page.overlay.append(progress_dialog)
            progress_dialog.open = True
            self.page.update()

            # Fetch Telegram groups (connection check)
            groups = await self.forwarder.get_telegram_groups(
                code_callback=self._request_telegram_code,
                password_callback=self._request_telegram_password
            )

            # Success dialog
            progress_dialog.open = False
            self.page.update()

            success_dialog = ft.AlertDialog(
                title=ft.Text("Connected"),
                content=ft.Text(f"Connected to Telegram.\nFound {len(groups)} groups/channels."),
                actions=[
                    ft.TextButton("OK", on_click=lambda e: setattr(success_dialog, 'open', False) or self.page.update())
                ],
            )
            self.page.overlay.append(success_dialog)
            success_dialog.open = True
            self.page.update()

        except Exception as ex:
            # Error dialog
            if 'progress_dialog' in locals():
                progress_dialog.open = False
                self.page.update()

            self._show_error(f"Telegram connection error: {str(ex)}")

    async def _request_telegram_code(self):
        """Enter the Telegram verification code"""
        code_result = None
        code_event = asyncio.Event()

        code_field = ft.TextField(
            label="Verification Code",
            hint_text="Enter the 5-digit code sent by Telegram",
            width=300,
            autofocus=True
        )

        def submit_code(e):
            nonlocal code_result
            if code_field.value:
                code_result = code_field.value
                dialog.open = False
                self.page.update()
                code_event.set()

        dialog = ft.AlertDialog(
            title=ft.Text("Telegram Verification"),
            content=ft.Column([
                ft.Text("Telegram has sent you a verification code."),
                ft.Text("Enter the code you received in the app or via SMS."),
                code_field,
            ], tight=True, height=150),
            actions=[
                ft.TextButton("Submit", on_click=submit_code),
            ],
        )

        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

        await code_event.wait()
        return code_result

    async def _request_telegram_password(self):
        """Enter the Telegram two-step verification password"""
        password_result = None
        password_event = asyncio.Event()

        password_field = ft.TextField(
            label="Two-Step Verification Password",
            hint_text="Enter your Telegram two-step verification password",
            password=True,
            width=300,
            autofocus=True
        )

        def submit_password(e):
            nonlocal password_result
            if password_field.value:
                password_result = password_field.value
                dialog.open = False
                self.page.update()
                password_event.set()

        dialog = ft.AlertDialog(
            title=ft.Text("Two-Step Verification"),
            content=ft.Column([
                ft.Text("Two-step verification is enabled."),
                ft.Text("Please enter your password."),
                password_field,
            ], tight=True, height=150),
            actions=[
                ft.TextButton("Submit", on_click=submit_password),
            ],
        )

        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

        await password_event.wait()
        return password_result

    def _show_error(self, message: str):
        """Show an error dialog"""
        dialog = ft.AlertDialog(
            title=ft.Text("Error"),
            content=ft.Text(message),
            actions=[
                ft.TextButton("OK", on_click=lambda e: setattr(dialog, 'open', False) or self.page.update())
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()


    def _show_backup_status(self, ok: bool, message: str):
        """Show the result of a GitHub backup (called from a background thread)"""
        try:
            self.page.open(ft.SnackBar(
                ft.Text(("✓ " if ok else "⚠ ") + message),
                bgcolor=None if ok else ft.Colors.ORANGE_800,
                duration=3000 if ok else 8000,
            ))
        except Exception:
            pass  # window may be closing

    def _on_window_event(self, e):
        """Finish any pending GitHub backup before the window closes"""
        if e.data == "close":
            try:
                if self.is_forwarding:
                    self.notifier.stop_heartbeat()
                    self.notifier.send("⏹ Forwarding stopped: the app was closed.", wait=True)
                self.git_backup.flush()
            finally:
                APP_STATE["user_closed"] = True
                self.page.window.destroy()


def _ensure_single_instance():
    """Exit if another copy is already running (two copies would forward everything twice)."""
    if sys.platform != "win32":
        return None
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, "Local\\TelegramToSlackForwarder")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(
            None, "Telegram to Slack Forwarder is already running.\n\n"
                  "Look for its window or its icon in the taskbar.",
            "Telegram to Slack Forwarder", 0x40)
        sys.exit(EXIT_ALREADY_RUNNING)
    return handle  # keep the mutex for the app's lifetime


def main(page: ft.Page):
    TelegramToSlackGUI(page)


if __name__ == "__main__":
    _instance_lock = _ensure_single_instance()
    ft.app(target=main)
    # run_windows.bat restarts the app unless the user closed the window
    sys.exit(0 if APP_STATE["user_closed"] else EXIT_UNEXPECTED)
