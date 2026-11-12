import json
import os
import ssl
import time
import socket
from http.client import IncompleteRead
import certifi
from datetime import datetime, timezone
from typing import Dict, Optional
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from config import Config

class SlackHandler:
    """Slack API integration"""

    def __init__(self, config: Config):
        self.config = config
        self.client: Optional[WebClient] = None
        self.thread_cache_file = "data/thread_cache.json"
        self.thread_cache = self._load_thread_cache()

    def _load_thread_cache(self) -> Dict:
        """Load the thread cache"""
        if os.path.exists(self.thread_cache_file):
            with open(self.thread_cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _save_thread_cache(self):
        """Save the thread cache"""
        os.makedirs(os.path.dirname(self.thread_cache_file), exist_ok=True)
        with open(self.thread_cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.thread_cache, f, indent=2)

    def connect(self):
        """Connect to Slack"""
        slack_config = self.config.get_slack_config()
        if not slack_config.get("bot_token"):
            raise ValueError("Slack bot token is not set")

        # SSL certificate setup
        ssl_context = ssl.create_default_context(cafile=certifi.where())

        self.client = WebClient(
            token=slack_config["bot_token"],
            ssl=ssl_context,
            timeout=60  # 60s timeout (the 30s default is not enough)
        )

        # Connection test
        try:
            response = self.client.auth_test()
            print(f"Connected to Slack: {response['user']}")
            return True
        except SlackApiError as e:
            print(f"Failed to connect to Slack: {e.response['error']}")
            return False

    def post_message(self, channel_id: str, text: str,
                     thread_ts: Optional[str] = None) -> Optional[str]:
        """Post a message"""
        if not self.client:
            raise RuntimeError("Slack client is not connected")

        try:
            response = self.client.chat_postMessage(
                channel=channel_id,
                text=text,
                thread_ts=thread_ts
            )
            return response['ts']
        except SlackApiError as e:
            print(f"Failed to post message: {e.response['error']}")
            return None

    def update_message(self, channel_id: str, ts: str, text: str) -> bool:
        """Edit a message (used to update thread titles)"""
        if not self.client:
            raise RuntimeError("Slack client is not connected")

        try:
            self.client.chat_update(
                channel=channel_id,
                ts=ts,
                text=text
            )
            print(f"[DEBUG] Updated Slack message: ts={ts}")
            return True
        except SlackApiError as e:
            print(f"Failed to update message: {e.response['error']}")
            return False

    def upload_file(self, channel_id: str, file_path: str,
                   initial_comment: str = "", thread_ts: Optional[str] = None) -> bool:
        """Upload a file"""
        if not self.client:
            raise RuntimeError("Slack client is not connected")

        try:
            response = self.client.files_upload_v2(
                channel=channel_id,
                file=file_path,
                initial_comment=initial_comment,
                thread_ts=thread_ts
            )
            return response['ok']
        except SlackApiError as e:
            print(f"Failed to upload file: {e.response['error']}")
            return False

    def get_or_create_thread(self, group_config: Dict, timestamp: datetime,
                             topic_id: Optional[int] = None, topic_name: Optional[str] = None) -> Optional[str]:
        """Get or create a thread (updates the title when the topic name changes)"""
        thread_mode = group_config.get("thread_mode", "daily")
        group_id = group_config["id"]
        channel_id = group_config["slack_channel_id"]

        if thread_mode == "single_message":
            # No threads
            return None

        # Convert from UTC to the local time zone
        import datetime as dt
        if timestamp.tzinfo is None:
            # Treat as UTC if there is no time zone info
            timestamp = timestamp.replace(tzinfo=dt.timezone.utc)

        # Convert to the local time zone
        local_timestamp = timestamp.astimezone()

        # Build the cache key (includes channel ID and topic ID)
        topic_suffix = f"_topic{topic_id}" if topic_id else ""
        if thread_mode == "daily":
            # Per day
            cache_key = f"{group_id}_{channel_id}_{local_timestamp.strftime('%Y-%m-%d')}{topic_suffix}"
        elif thread_mode == "weekly":
            # Per week (week number)
            cache_key = f"{group_id}_{channel_id}_{local_timestamp.strftime('%Y-W%W')}{topic_suffix}"
        else:
            return None

        # If cached, check whether the topic name changed
        if cache_key in self.thread_cache:
            cached_data = self.thread_cache[cache_key]

            # Handle legacy format (thread_ts only) vs new format (dict)
            if isinstance(cached_data, str):
                # Legacy format: only thread_ts is stored
                thread_ts = cached_data
                cached_topic_name = None
            else:
                # New format: {"thread_ts": "...", "topic_name": "..."}
                thread_ts = cached_data.get("thread_ts")
                cached_topic_name = cached_data.get("topic_name")

            # If the topic name changed, update the Slack thread title
            if topic_name and cached_topic_name != topic_name:
                new_title = self._get_thread_title(group_config, local_timestamp, thread_mode, topic_name)
                if self.update_message(channel_id, thread_ts, new_title):
                    print(f"[INFO] Topic name changed: {cached_topic_name} → {topic_name}")
                    # Update the cache
                    self.thread_cache[cache_key] = {
                        "thread_ts": thread_ts,
                        "topic_name": topic_name
                    }
                    self._save_thread_cache()

            return thread_ts

        # Create a new thread
        thread_title = self._get_thread_title(group_config, local_timestamp, thread_mode, topic_name)
        thread_ts = self.post_message(channel_id, thread_title)

        if thread_ts:
            # Save to the cache in the new format
            self.thread_cache[cache_key] = {
                "thread_ts": thread_ts,
                "topic_name": topic_name
            }
            self._save_thread_cache()

        return thread_ts

    def _get_thread_title(self, group_config: Dict, timestamp: datetime, thread_mode: str,
                          topic_name: Optional[str] = None) -> str:
        """Build the thread title"""
        telegram_name = group_config.get("telegram_group_name", "Telegram")

        # Append the topic name, if any
        if topic_name:
            source_name = f"{telegram_name} / {topic_name}"
        else:
            source_name = telegram_name

        if thread_mode == "daily":
            date_str = timestamp.strftime('%Y-%m-%d')
            return f":telegram: {source_name} - {date_str}"
        elif thread_mode == "weekly":
            week_start = timestamp.strftime('%Y-%m-%d')
            return f":telegram: {source_name} - Week of {week_start}"
        else:
            return f":telegram: {source_name}"

    def get_channels(self):
        """Get the channel list (paginated, with retries)"""
        if not self.client:
            raise RuntimeError("Slack client is not connected")

        channels = []
        cursor = None
        max_retries = 3
        print("[DEBUG] Slack: Fetching channels...")

        while True:
            retry_count = 0
            response = None

            while retry_count < max_retries:
                try:
                    # Fetch public and private channels
                    response = self.client.conversations_list(
                        types="public_channel,private_channel",
                        exclude_archived=True,
                        limit=500,  # 500 to keep the response size down
                        cursor=cursor
                    )
                    break  # Exit the loop on success

                except (IncompleteRead, socket.timeout, TimeoutError) as e:
                    retry_count += 1
                    if retry_count < max_retries:
                        wait_time = retry_count * 2  # Backoff: 2s, 4s, 6s
                        print(f"[DEBUG] Slack: Network error ({type(e).__name__}), retrying in {wait_time}s... ({retry_count}/{max_retries})")
                        time.sleep(wait_time)
                    else:
                        print(f"[ERROR] Slack: Failed after {max_retries} retries: {type(e).__name__}: {e}")
                        raise

                except SlackApiError as e:
                    print(f"[DEBUG] Slack: API error: {e.response['error']}")
                    return channels  # Return immediately on API errors

            if response is None:
                break

            for channel in response['channels']:
                is_private = channel.get('is_private', False)
                print(f"[DEBUG] Slack: Added: id={channel['id']}, name=#{channel['name']}, private={is_private}")
                channels.append({
                    "id": channel['id'],
                    "name": f"#{channel['name']}",
                    "is_private": is_private
                })

            # Check for a next page
            cursor = response.get('response_metadata', {}).get('next_cursor')
            if not cursor:
                break  # All pages fetched

            print(f"[DEBUG] Slack: Fetching next page...")

        print(f"[DEBUG] Slack: Total {len(channels)} channels found")
        return channels

    def format_message(self, message_data: Dict) -> str:
        """Format a Telegram message for Slack"""
        sender = message_data.get("sender_name", "Unknown")
        text = message_data.get("text", "")
        reply_to_text = message_data.get("reply_to_text")
        reply_to_sender = message_data.get("reply_to_sender")

        # If there is a quoted reply
        quote_block = ""
        if reply_to_text and reply_to_sender:
            # Slack quote format (uses >)
            quote_lines = reply_to_text.split('\n')
            quoted = '\n'.join(f">{line}" for line in quote_lines)
            quote_block = f"_{reply_to_sender}:_\n{quoted}\n\n"

        # Message body
        if text:
            formatted = f"{quote_block}*{sender}*: {text}"
        else:
            # No text (file only)
            formatted = f"{quote_block}*{sender}*"

        return formatted
