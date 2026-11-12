import asyncio
from typing import Callable, Optional, Dict
from telethon import TelegramClient, events
from telethon.tl.types import Message, User, Chat, Channel, MessageService, MessageActionTopicCreate
from config import Config

class TelegramHandler:
    """Telegram API integration class"""

    def __init__(self, config: Config):
        self.config = config
        self.client: Optional[TelegramClient] = None
        self.is_running = False
        self.message_callback: Optional[Callable] = None
        self.code_callback: Optional[Callable] = None
        self.password_callback: Optional[Callable] = None

    async def start(self, message_callback: Callable, code_callback: Optional[Callable] = None,
                    password_callback: Optional[Callable] = None):
        """Start the Telegram client"""
        tg_config = self.config.get_telegram_config()

        if not tg_config.get("api_id") or not tg_config.get("api_hash"):
            raise ValueError("Telegram API credentials are not configured")

        self.message_callback = message_callback
        self.code_callback = code_callback
        self.password_callback = password_callback

        # Create Telethon client
        self.client = TelegramClient(
            'telegram_session',
            int(tg_config["api_id"]),
            tg_config["api_hash"]
        )

        # Set callbacks and start
        await self.client.start(
            phone=tg_config["phone"],
            code_callback=self._request_code if code_callback else None,
            password=self._request_password if password_callback else None
        )
        print(f"Connected to Telegram: {await self.client.get_me()}")

        # Register message handler
        self.client.add_event_handler(
            self._handle_new_message,
            events.NewMessage()
        )

        self.is_running = True

    async def _request_code(self):
        """Prompt for the login code"""
        if self.code_callback:
            return await self.code_callback()
        return input('Enter the login code you received: ')

    async def _request_password(self):
        """Prompt for the two-step verification password"""
        if self.password_callback:
            return await self.password_callback()
        return input('Enter your two-step verification password: ')

    async def _handle_new_message(self, event: events.NewMessage.Event):
        """Handle a new message"""
        message: Message = event.message

        # Get source chat ID
        chat_id = event.chat_id
        print(f"[DEBUG] Message received: chat_id={chat_id}, text={message.text[:50] if message.text else '(no text)'}...")

        # Check whether this is a monitored group
        groups = self.config.get_groups()
        target_group = None
        for group in groups:
            if group.get("enabled") and group.get("telegram_group_id") == chat_id:
                target_group = group
                break

        if not target_group:
            print(f"[DEBUG] Unmonitored group: chat_id={chat_id}")
            return  # Not monitored

        print(f"[DEBUG] Monitored group: {target_group['telegram_group_name']}")

        # Extract message info
        sender = await event.get_sender()
        sender_name = self._get_sender_name(sender)

        # Build message link
        message_link = await self._get_message_link(event.chat, message.id)

        # Download media file
        media_file = None
        if message.media:
            try:
                media_file = await message.download_media(file="downloads/")
            except Exception as e:
                print(f"Failed to download media: {e}")

        # Get topic info (for groups using forum topics)
        topic_id = None
        topic_name = None
        reply_to_text = None
        reply_to_sender = None
        try:
            # Debug: inspect message.reply_to
            has_reply_to = message.reply_to is not None
            has_forum_topic_attr = hasattr(message.reply_to, 'forum_topic') if has_reply_to else False
            forum_topic_value = getattr(message.reply_to, 'forum_topic', None) if has_reply_to else None
            print(f"[DEBUG] Topic detection: has_reply_to={has_reply_to}, has_forum_topic_attr={has_forum_topic_attr}, forum_topic_value={forum_topic_value}")

            if has_reply_to:
                print(f"[DEBUG] reply_to contents: {message.reply_to}")

            if message.reply_to and hasattr(message.reply_to, 'forum_topic') and message.reply_to.forum_topic:
                # reply_to_top_id is the topic ID; reply_to_msg_id is the replied-to message ID
                reply_to_top_id = getattr(message.reply_to, 'reply_to_top_id', None)
                reply_to_msg_id = message.reply_to.reply_to_msg_id

                print(f"[DEBUG] Forum: reply_to_top_id={reply_to_top_id}, reply_to_msg_id={reply_to_msg_id}")

                if reply_to_top_id:
                    # Reply message: reply_to_top_id is the topic ID
                    topic_id = reply_to_top_id
                    print(f"[DEBUG] Reply message: topic_id={topic_id}")
                else:
                    # Direct post: reply_to_msg_id may be the topic ID, but needs verification
                    # Check whether the reply_to_msg_id message is the topic-creation service message
                    try:
                        check_msgs = await self.client.get_messages(event.chat, ids=[reply_to_msg_id])
                        if check_msgs and len(check_msgs) > 0 and check_msgs[0]:
                            check_msg = check_msgs[0]
                            print(f"[DEBUG] reply_to_msg_id={reply_to_msg_id} message: type={type(check_msg).__name__}")
                            if isinstance(check_msg, MessageService):
                                print(f"[DEBUG] Service message action: {type(check_msg.action).__name__}")
                                if isinstance(check_msg.action, MessageActionTopicCreate):
                                    print(f"[DEBUG] Topic creation message: title='{check_msg.action.title}'")
                            if isinstance(check_msg, MessageService) and isinstance(check_msg.action, MessageActionTopicCreate):
                                # This is the topic creation message, so this is the topic ID
                                topic_id = reply_to_msg_id
                                print(f"[DEBUG] Direct post (topic creation verified): topic_id={topic_id}, title='{check_msg.action.title}'")
                            else:
                                # Reply to a regular message - follow the parent to find the topic
                                print(f"[DEBUG] Reply to regular message detected, following parent")
                                if hasattr(check_msg, 'reply_to') and check_msg.reply_to:
                                    parent_top_id = getattr(check_msg.reply_to, 'reply_to_top_id', None)
                                    parent_msg_id = getattr(check_msg.reply_to, 'reply_to_msg_id', None)
                                    topic_id = parent_top_id or parent_msg_id
                                    print(f"[DEBUG] Topic ID from parent: {topic_id}")

                                    # Set as quoted source message
                                    reply_to_text = check_msg.text or "(Media)"
                                    reply_sender = await check_msg.get_sender()
                                    reply_to_sender = self._get_sender_name(reply_sender)
                                else:
                                    topic_id = reply_to_msg_id
                                    print(f"[DEBUG] Fallback: topic_id={topic_id}")
                        else:
                            topic_id = reply_to_msg_id
                            print(f"[DEBUG] Failed to fetch message, falling back: topic_id={topic_id}")
                    except Exception as e:
                        print(f"[DEBUG] Topic ID verification error: {e}")
                        topic_id = reply_to_msg_id

                # If reply_to_top_id exists, fetch the quoted source message
                if reply_to_top_id and reply_to_msg_id and reply_to_msg_id != topic_id:
                    try:
                        reply_msgs = await self.client.get_messages(event.chat, ids=[reply_to_msg_id])
                        if reply_msgs and len(reply_msgs) > 0 and reply_msgs[0]:
                            reply_msg = reply_msgs[0]
                            reply_to_text = reply_msg.text or "(Media)"
                            reply_sender = await reply_msg.get_sender()
                            reply_to_sender = self._get_sender_name(reply_sender)
                    except Exception as e:
                        print(f"Failed to fetch quoted message: {e}")

                topic_name = await self._get_topic_name(event.chat, topic_id)
                print(f"[DEBUG] Retrieved topic name: {topic_name}")
        except Exception as e:
            print(f"Error getting topic info: {e}")

        message_data = {
            "group_id": target_group["id"],
            "telegram_group_id": chat_id,
            "telegram_group_name": target_group["telegram_group_name"],
            "sender_name": sender_name,
            "text": message.text or "",
            "timestamp": message.date,
            "message_id": message.id,
            "has_media": message.media is not None,
            "media_type": self._get_media_type(message),
            "message_link": message_link,
            "media_file": media_file,
            "topic_id": topic_id,
            "topic_name": topic_name,
            "reply_to_text": reply_to_text,
            "reply_to_sender": reply_to_sender
        }

        # Invoke callback
        if self.message_callback:
            await self.message_callback(message_data, target_group)

    async def _get_message_link(self, chat, message_id: int) -> Optional[str]:
        """Build a link to the message"""
        try:
            # Get chat info
            if hasattr(chat, 'username') and chat.username:
                # Public channel/group
                return f"https://t.me/{chat.username}/{message_id}"
            else:
                # Private group
                # Use absolute value of chat_id (negative to positive)
                chat_id = abs(chat.id)
                # Private group link format
                # Normalize by subtracting 1000000000000
                if chat_id > 1000000000000:
                    chat_id = chat_id - 1000000000000
                return f"https://t.me/c/{chat_id}/{message_id}"
        except Exception as e:
            print(f"Failed to build message link: {e}")
            return None

    def _get_sender_name(self, sender) -> str:
        """Get the sender name"""
        if isinstance(sender, User):
            if sender.first_name and sender.last_name:
                return f"{sender.first_name} {sender.last_name}"
            elif sender.first_name:
                return sender.first_name
            elif sender.username:
                return f"@{sender.username}"
            else:
                return "Unknown User"
        else:
            return "Unknown"

    def _get_media_type(self, message: Message) -> Optional[str]:
        """Determine the media type"""
        if not message.media:
            return None

        if message.photo:
            return "photo"
        elif message.video:
            return "video"
        elif message.document:
            return "document"
        elif message.audio:
            return "audio"
        elif message.voice:
            return "voice"
        elif message.sticker:
            return "sticker"
        else:
            return "other"

    async def get_dialogs(self):
        """Get the list of chats/groups the user has joined"""
        if not self.client:
            raise RuntimeError("Client is not started")

        dialogs = []
        seen_ids = set()  # For duplicate ID checks
        print("[DEBUG] Telegram: Fetching dialogs...")
        async for dialog in self.client.iter_dialogs():
            # Groups and channels only
            if dialog.is_group or dialog.is_channel:
                # Skip duplicate IDs
                if dialog.id in seen_ids:
                    continue

                # Avoid duplicate entries for a forum's General topic
                # Skip only if a Channel with the same name was already added
                entity = dialog.entity
                entity_type = type(entity).__name__
                if entity_type == "Chat":
                    # A Channel with the same name already exists, so skip as duplicate
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

        return dialogs

    async def stop(self):
        """Stop the client"""
        self.is_running = False
        if self.client:
            await self.client.disconnect()

    async def run_until_disconnected(self):
        """Run until disconnected"""
        if self.client:
            await self.client.run_until_disconnected()

    async def _get_topic_name(self, chat, topic_id: int) -> Optional[str]:
        """Get the topic name - uses the channels.getForumTopics API"""
        if not topic_id:
            return None

        print(f"[DEBUG] _get_topic_name start: chat_id={chat.id}, topic_id={topic_id}")

        # Fetch topic info directly via the messages.getForumTopicsByID API
        try:
            from telethon.tl.functions.messages import GetForumTopicsByIDRequest

            # Get InputPeer
            input_peer = await self.client.get_input_entity(chat)

            result = await self.client(GetForumTopicsByIDRequest(
                peer=input_peer,
                topics=[topic_id]
            ))

            # Get topic info
            if result.topics and len(result.topics) > 0:
                topic = result.topics[0]
                if hasattr(topic, 'title'):
                    print(f"[DEBUG] GetForumTopicsByID succeeded: id={getattr(topic, 'id', '?')}, title='{topic.title}'")
                    return topic.title

        except Exception as e:
            print(f"[DEBUG] GetForumTopicsByID failed: {e}")

        # Fallback: get from the topic creation message
        from telethon.tl.types import MessageActionTopicEdit
        topic_title = None

        try:
            messages = await self.client.get_messages(chat, ids=[topic_id])
            if messages and len(messages) > 0:
                msg = messages[0]
                if isinstance(msg, MessageService) and isinstance(msg.action, MessageActionTopicCreate):
                    topic_title = msg.action.title
                    print(f"[DEBUG] Fallback - from topic creation message: title='{topic_title}'")
        except Exception as e:
            print(f"[DEBUG] Error fetching topic creation message: {e}")

        # If no edit is found, return the original name
        if topic_title:
            print(f"[DEBUG] No edit, using original name: title='{topic_title}'")
            return topic_title

        # Final fallback: use the topic ID
        print(f"[DEBUG] Final fallback: Topic {topic_id}")
        return f"Topic {topic_id}"
