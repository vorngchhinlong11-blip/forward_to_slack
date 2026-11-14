import json
import os
from typing import Dict, List, Optional
from pathlib import Path


def _write_json(path: str, data) -> None:
    """Write JSON atomically so a crash can't leave a half-written file"""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, path)

class Config:
    """Configuration manager

    Settings are split across two files:
    - groups.json        : registered groups (no secrets; kept in Git as a backup)
    - data/config.json   : Telegram/Slack credentials (secret; never in Git)
    """

    def __init__(self, config_path: str = "data/config.json", groups_path: str = "groups.json"):
        self.config_path = config_path
        self.groups_path = groups_path
        # Optional callback(description) run after groups are added/edited/deleted
        self.on_groups_changed = None
        self.config_data = self._load_config()

    def _load_config(self) -> Dict:
        """Load credentials and groups"""
        config = {
            "groups": [],
            "telegram": {
                "api_id": "",
                "api_hash": "",
                "phone": ""
            },
            "slack": {
                "bot_token": "",
                "app_token": ""
            }
        }

        legacy_groups = None
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                stored = json.load(f)
            # Older versions kept the groups inside data/config.json
            legacy_groups = stored.pop("groups", None)
            config.update(stored)

        if legacy_groups is not None:
            # Groups found in data/config.json are always the newest copy
            # (current code never writes them there), so migrate them.
            config["groups"] = legacy_groups
            self.config_data = config
            self.save_config()
        elif os.path.exists(self.groups_path):
            with open(self.groups_path, 'r', encoding='utf-8') as f:
                config["groups"] = json.load(f)

        return config

    def save_config(self):
        """Save groups to groups.json and credentials to data/config.json"""
        _write_json(self.groups_path, self.config_data.get("groups", []))
        secrets = {k: v for k, v in self.config_data.items() if k != "groups"}
        _write_json(self.config_path, secrets)

    # Telegram settings
    def get_telegram_config(self) -> Dict:
        """Get Telegram API settings"""
        return self.config_data.get("telegram", {})

    def set_telegram_config(self, api_id: str, api_hash: str, phone: str):
        """Save Telegram API settings"""
        self.config_data["telegram"] = {
            "api_id": api_id,
            "api_hash": api_hash,
            "phone": phone
        }
        self.save_config()

    # Slack settings
    def get_slack_config(self) -> Dict:
        """Get Slack API settings"""
        return self.config_data.get("slack", {})

    def set_slack_config(self, bot_token: str, app_token: str = ""):
        """Save Slack API settings"""
        self.config_data["slack"] = {
            "bot_token": bot_token,
            "app_token": app_token
        }
        self.save_config()

    # Status alerts (Telegram bot + heartbeat) - stored in data/config.json
    def get_notify_config(self) -> Dict:
        """Get alert settings"""
        return self.config_data.get("notify", {})

    def set_notify_config(self, bot_token: str, chat_id: str, heartbeat_url: str = ""):
        """Save alert settings"""
        self.config_data["notify"] = {
            "bot_token": bot_token.strip(),
            "chat_id": chat_id.strip(),
            "heartbeat_url": heartbeat_url.strip(),
        }
        self.save_config()

    # Group management
    def get_groups(self) -> List[Dict]:
        """Get all group settings"""
        return self.config_data.get("groups", [])

    def add_group(self, telegram_group_id: int, telegram_group_name: str,
                  slack_channel_id: str, slack_channel_name: str,
                  thread_mode: str = "daily",
                  telegram_topic_id: Optional[int] = None,
                  telegram_topic_name: Optional[str] = None) -> str:
        """Add a new group (optionally limited to one forum topic)"""
        import uuid
        group_id = str(uuid.uuid4())

        new_group = {
            "id": group_id,
            "telegram_group_id": telegram_group_id,
            "telegram_group_name": telegram_group_name,
            "slack_channel_id": slack_channel_id,
            "slack_channel_name": slack_channel_name,
            "thread_mode": thread_mode,
            "enabled": True
        }
        if telegram_topic_id is not None:
            new_group["telegram_topic_id"] = telegram_topic_id
            new_group["telegram_topic_name"] = telegram_topic_name

        self.config_data["groups"].append(new_group)
        self.save_config()
        source = telegram_group_name + (f" / {telegram_topic_name}" if telegram_topic_id is not None else "")
        self._notify_groups_changed(f"added {source} -> {slack_channel_name}")
        return group_id

    def update_group(self, group_id: str, **kwargs):
        """Update group settings"""
        for group in self.config_data["groups"]:
            if group["id"] == group_id:
                group.update(kwargs)
                # "All topics": drop the topic keys instead of storing nulls
                if "telegram_topic_id" in kwargs and kwargs["telegram_topic_id"] is None:
                    group.pop("telegram_topic_id", None)
                    group.pop("telegram_topic_name", None)
                self.save_config()
                self._notify_groups_changed(f"edited {group.get('telegram_group_name', group_id)}")
                return True
        return False

    def delete_group(self, group_id: str) -> bool:
        """Delete a group"""
        removed = [g for g in self.config_data["groups"] if g["id"] == group_id]
        self.config_data["groups"] = [
            g for g in self.config_data["groups"] if g["id"] != group_id
        ]
        if removed:
            self.save_config()
            self._notify_groups_changed(f"deleted {removed[0].get('telegram_group_name', group_id)}")
            return True
        return False

    def _notify_groups_changed(self, description: str) -> None:
        """Tell the listener (e.g. the GitHub backup) that groups.json changed"""
        if self.on_groups_changed:
            self.on_groups_changed(description)

    def get_group(self, group_id: str) -> Optional[Dict]:
        """Get a specific group"""
        for group in self.config_data["groups"]:
            if group["id"] == group_id:
                return group
        return None

    def is_telegram_configured(self) -> bool:
        """Check whether Telegram is fully configured"""
        tg_config = self.get_telegram_config()
        return bool(tg_config.get("api_id") and tg_config.get("api_hash") and tg_config.get("phone"))

    def is_slack_configured(self) -> bool:
        """Check whether Slack is fully configured"""
        slack_config = self.get_slack_config()
        return bool(slack_config.get("bot_token"))
