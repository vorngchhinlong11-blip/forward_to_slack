import json
import os
from typing import Dict, List, Optional
from pathlib import Path

class Config:
    """Configuration manager"""

    def __init__(self, config_path: str = "data/config.json"):
        self.config_path = config_path
        self.config_data = self._load_config()

    def _load_config(self) -> Dict:
        """Load the config file"""
        default_config = {
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

        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # Fill in missing keys with default values
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                return config
        else:
            return default_config

    def save_config(self):
        """Save to the config file"""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config_data, f, indent=2, ensure_ascii=False)

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

    # Group management
    def get_groups(self) -> List[Dict]:
        """Get all group settings"""
        return self.config_data.get("groups", [])

    def add_group(self, telegram_group_id: int, telegram_group_name: str,
                  slack_channel_id: str, slack_channel_name: str,
                  thread_mode: str = "daily") -> str:
        """Add a new group"""
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

        self.config_data["groups"].append(new_group)
        self.save_config()
        return group_id

    def update_group(self, group_id: str, **kwargs):
        """Update group settings"""
        for group in self.config_data["groups"]:
            if group["id"] == group_id:
                group.update(kwargs)
                self.save_config()
                return True
        return False

    def delete_group(self, group_id: str) -> bool:
        """Delete a group"""
        original_length = len(self.config_data["groups"])
        self.config_data["groups"] = [
            g for g in self.config_data["groups"] if g["id"] != group_id
        ]
        if len(self.config_data["groups"]) < original_length:
            self.save_config()
            return True
        return False

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
