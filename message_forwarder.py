import asyncio
from typing import Dict
from config import Config
from telegram_handler import TelegramHandler
from slack_handler import SlackHandler

class MessageForwarder:
    """Manages forwarding messages from Telegram to Slack"""

    def __init__(self, config: Config):
        self.config = config
        self.telegram_handler = TelegramHandler(config)
        self.slack_handler = SlackHandler(config)
        self.is_running = False

    async def start(self, code_callback=None, password_callback=None):
        """Start the forwarding service"""
        # Connect to Slack
        if not self.slack_handler.connect():
            raise RuntimeError("Failed to connect to Slack")

        # Start Telegram (register the message callback)
        await self.telegram_handler.start(
            self._on_telegram_message,
            code_callback=code_callback,
            password_callback=password_callback
        )

        self.is_running = True
        print("Message forwarding service started")

    async def _on_telegram_message(self, message_data: Dict, group_config: Dict):
        """Callback invoked when a Telegram message is received"""
        try:
            # Post to the Slack channel
            channel_id = group_config["slack_channel_id"]
            timestamp = message_data["timestamp"]
            topic_id = message_data.get("topic_id")
            topic_name = message_data.get("topic_name")

            # Get/create the thread (separate thread per topic, if any)
            thread_ts = self.slack_handler.get_or_create_thread(
                group_config, timestamp, topic_id=topic_id, topic_name=topic_name
            )

            # Format the message
            formatted_message = self.slack_handler.format_message(message_data)

            # Upload the file, if any
            if message_data.get("media_file"):
                media_file = message_data["media_file"]

                # Check the file size
                import os
                file_size = os.path.getsize(media_file) if os.path.exists(media_file) else 0
                file_size_mb = file_size / (1024 * 1024)
                file_size_gb = file_size / (1024 * 1024 * 1024)

                # Slack's limit is 1GB
                if file_size > 1024 * 1024 * 1024:  # 1GB
                    # File too large: post the message only
                    warning_message = formatted_message + f"\n⚠️ File too large ({file_size_gb:.2f}GB > 1GB limit)\nCould not upload to Slack."

                    self.slack_handler.post_message(
                        channel_id=channel_id,
                        text=warning_message,
                        thread_ts=thread_ts
                    )

                    # Delete the temporary file
                    try:
                        if os.path.exists(media_file):
                            os.remove(media_file)
                            print(f"Deleted large file: {media_file} ({file_size_gb:.2f}GB)")
                    except Exception as e:
                        print(f"Failed to delete temporary file: {e}")

                    print(f"File too large ({file_size_gb:.2f}GB) - skipped upload from {message_data['telegram_group_name']}")
                else:
                    # File size is OK: upload it
                    success = self.slack_handler.upload_file(
                        channel_id=channel_id,
                        file_path=media_file,
                        initial_comment=formatted_message,
                        thread_ts=thread_ts
                    )

                    # Delete the temporary file after upload
                    try:
                        if os.path.exists(media_file):
                            os.remove(media_file)
                            print(f"Deleted temporary file: {media_file}")
                    except Exception as e:
                        print(f"Failed to delete temporary file: {e}")

                    if success:
                        print(f"Uploaded file ({file_size_mb:.2f}MB): {message_data['telegram_group_name']} → Slack")
                    else:
                        print(f"Failed to upload file: {message_data['telegram_group_name']}")

                        # On failure, also post an error message to Slack
                        error_message = formatted_message + f"\n⚠️ File upload failed ({file_size_mb:.2f}MB)\nPossibly due to insufficient storage or a network error."
                        self.slack_handler.post_message(
                            channel_id=channel_id,
                            text=error_message,
                            thread_ts=thread_ts
                        )
            else:
                # Text only: post a normal message
                self.slack_handler.post_message(
                    channel_id=channel_id,
                    text=formatted_message,
                    thread_ts=thread_ts
                )

                print(f"Forwarded message: {message_data['telegram_group_name']} → Slack")

        except Exception as e:
            print(f"Message forwarding error: {e}")

    async def stop(self):
        """Stop the forwarding service"""
        self.is_running = False
        await self.telegram_handler.stop()
        print("Message forwarding service stopped")

    async def run(self):
        """Run the forwarding service"""
        await self.start()
        await self.telegram_handler.run_until_disconnected()

    async def get_telegram_groups(self, code_callback=None, password_callback=None):
        """Get the list of Telegram groups"""
        # If a client exists and is connected
        if self.telegram_handler.client and self.telegram_handler.client.is_connected():
            return await self.telegram_handler.get_dialogs()

        # If there is no client or it is disconnected, connect temporarily
        tg_config = self.config.get_telegram_config()
        if not tg_config.get("api_id") or not tg_config.get("api_hash"):
            raise ValueError("Telegram is not configured")

        from telethon import TelegramClient
        client = TelegramClient(
            'telegram_session',
            int(tg_config["api_id"]),
            tg_config["api_hash"]
        )

        # Define callback functions
        async def request_code():
            if code_callback:
                return await code_callback()
            return input('Enter the verification code you received: ')

        async def request_password():
            if password_callback:
                return await password_callback()
            return input('Enter your two-step verification password: ')

        await client.start(
            phone=tg_config["phone"],
            code_callback=request_code if code_callback else None,
            password=request_password if password_callback else None
        )

        dialogs = []
        seen_ids = set()  # For duplicate ID checks
        print("[DEBUG] Telegram: Fetching dialogs...")
        async for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                # Remove duplicate IDs
                if dialog.id in seen_ids:
                    continue

                # Workaround for forum "General" topics showing up as duplicates:
                # skip only if a Channel with the same name was already added
                entity = dialog.entity
                entity_type = type(entity).__name__
                if entity_type == "Chat":
                    # A Channel with the same name already exists, so this is a duplicate; skip
                    if dialog.name in [d["name"] for d in dialogs]:
                        print(f"[DEBUG] Telegram: Skipped (duplicate Chat): id={dialog.id}, name={dialog.name}")
                        continue

                seen_ids.add(dialog.id)
                print(f"[DEBUG] Telegram: Added: id={dialog.id}, name={dialog.name}, type={entity_type}")

                dialogs.append({
                    "id": dialog.id,
                    "name": dialog.name,
                    "type": "group" if dialog.is_group else "channel"
                })

        print(f"[DEBUG] Telegram: Total {len(dialogs)} groups/channels found")
        await client.disconnect()
        return dialogs

    def get_slack_channels(self):
        """Get the list of Slack channels"""
        if not self.slack_handler.client:
            self.slack_handler.connect()

        return self.slack_handler.get_channels()
