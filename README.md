# Telegram to Slack Forwarder

A tool that automatically forwards messages from Telegram groups to Slack channels.

## Features

- Monitors Telegram groups in real time and forwards messages to Slack
- Add and manage groups easily through the GUI
- **Enter your Telegram verification code directly in the GUI**
- **Search Telegram groups and Slack channels when adding a group**
- **Search the registered groups list by group or channel name**
- Thread management (daily, weekly, or no threads)
- **Automatically uploads media files (photos, videos, etc.) to Slack**
- Detects your PC's time zone automatically to sort messages into threads
- Works with Telegram groups that include external users
- Monitors multiple groups at the same time
- Supports Windows, macOS and Linux

## Requirements

- Python 3.9 or later
- A Telegram account
- A Slack workspace (admin rights, or permission to create a bot)

## Setup

### 1. Get Telegram API keys

1. Go to https://my.telegram.org
2. Log in and select "API development tools"
3. Fill in the application details to get your API ID and API Hash

### 2. Create a Slack app and get a bot token

#### 2.1 Create the Slack app

1. Go to https://api.slack.com/apps
2. Click "Create New App"
3. Select "From scratch"
4. Enter an app name (e.g. Telegram Forwarder) and choose your workspace

#### 2.2 Set the bot token scopes

1. Select "OAuth & Permissions" in the left menu
2. Under "Scopes" → "Bot Token Scopes", add:
   - `chat:write` - post messages
   - `channels:read` - read public channel info
   - `groups:read` - read private channel info
   - `files:write` - upload files (required for media)

#### 2.3 Install the bot

1. Click "Install to Workspace" at the top of the "OAuth & Permissions" page
2. Review the permissions and click "Allow"
3. Copy the "Bot User OAuth Token" (it starts with `xoxb-`)

#### 2.4 Add the bot to channels

In each Slack channel you want to forward to:
```
/invite @your-app-name
```

## Usage

### Starting the app

**On first launch, setup runs automatically.**

#### Windows

```cmd
run_windows.bat
```

#### macOS / Linux

```bash
./run_mac.sh
```

The start script automatically:
- Creates a virtual environment if one doesn't exist
- Installs the dependencies
- Checks installed packages against `requirements.txt` and updates them if needed
- Starts the app

### First-time configuration

#### 1. Telegram settings

1. Click the "Telegram Settings" button
2. Enter:
   - API ID
   - API Hash
   - Phone number (international format, e.g. +81XXXXXXXXXX)
3. Click "Save"
4. **The connection check starts automatically**
5. On first connection, **a verification code dialog appears in the GUI**
6. Enter the code you received in the Telegram app or by SMS
7. If two-step verification is enabled, enter your password too
8. You're done when the "Connected" message appears

#### 2. Slack settings

1. Click the "Slack Settings" button
2. Enter your bot token
3. Click "Save"

### Adding a group

1. Click the "Add Group" button
2. Select a Telegram group
   - Groups you're a member of are listed automatically
   - On first use you may be asked for a verification code (enter it in the GUI)
   - **Use the search box to filter by group name**
3. Select a Slack channel
   - Choose from the channels the bot has been added to
   - **Use the search box to filter by channel name**
4. Choose a thread mode
   - **Daily**: a new thread every day (recommended)
   - **Weekly**: a new thread every week
   - **No Thread**: each message is posted on its own
5. Click "Save"

### Finding a registered group

Type in the "Search groups / channels" box next to the "Registered Groups" heading. The list filters as you type, matching the Telegram group name or the Slack channel name (case-insensitive). Click ✕ to clear the search.

### Starting forwarding

1. After adding your groups, click "Start Forwarding"
2. When the status changes to "Forwarding", messages are being forwarded
3. New Telegram messages are posted to Slack automatically

### Editing and deleting groups

- Edit: click the ✏️ icon on a group card
- Delete: click the 🗑️ icon on a group card
- Enable / disable: toggle the "Enabled" switch in the edit dialog

### Running on a server (24/7, no laptop)

`run_server.py` runs the forwarder without the window, as a service that starts
on boot and restarts itself after crashes. Step-by-step instructions for a free
Oracle Cloud server are in [deploy/ORACLE_SETUP.md](deploy/ORACLE_SETUP.md).

```bash
python run_server.py --check   # verify Slack + Telegram login
python run_server.py --login   # log in to Telegram over SSH if needed
python run_server.py           # forward until stopped
```

Never run the laptop app's forwarding and the server at the same time.

### Backing up and restoring

- **Groups** are saved in `groups.json` and **backed up to GitHub automatically**: a few seconds after you add, edit or delete a group, the app commits only `groups.json` and pushes it. A message at the bottom of the window confirms the backup or explains why it failed (e.g. no internet); a failed backup is retried with the next change. To turn this off, add `"git_backup": false` to `data/config.json`.
- **Keys** are not in Git, but they can always be fetched again: API ID and API Hash from https://my.telegram.org, and the bot token from your Slack app's "OAuth & Permissions" page. Storing them in a password manager makes this quicker.
- **On a new computer**: clone the repo, start the app, then enter the keys under "Telegram Settings" and "Slack Settings". All groups are already there.

## About threads

Telegram tends to have many short messages, so grouping them into Slack threads keeps channels tidy:

- **Daily**: all of a day's messages go into one thread (recommended)
  - e.g. a thread titled ":telegram: Group name - 2026-11-12" holds that day's messages
- **Weekly**: all of a week's messages go into one thread
  - e.g. ":telegram: Group name - Week of 2026-11-09"
- **No Thread**: each message is posted separately (can make Slack busy)

Thread information is cached in `data/thread_cache.json`, so the app keeps posting to the same thread after a restart.

**Time zone**: the app reads your PC's system settings and sorts messages into threads by local time (e.g. JST in Japan, ICT in Cambodia, PST/EST in the US).

## Media files (photos, videos, etc.)

Media files are **uploaded directly to Slack**.

### Supported files

- 📷 Photos (JPEG, PNG, etc.)
- 🎥 Videos (MP4, MOV, etc.)
- 📄 Documents (PDF, Word, Excel, etc.)
- 🎵 Audio files
- 🎤 Voice messages
- All other media types

### How it works

1. The file is downloaded from Telegram into the temporary `downloads/` folder
2. It is uploaded to Slack
3. The temporary file is deleted automatically

### Benefits

- ✅ View and download files directly in Slack
- ✅ No Telegram account needed to view them
- ✅ Works with every media type

### Slack storage limits

- **Per file**: up to 1GB
- **Free plan total**: up to 5GB
- **Message and file history**: 90 days

Keep an eye on storage if you forward a lot of files.

## Notes

### Telegram

- This tool connects to Telegram as **your user account**
- It uses the MTProto API rather than the Bot API, so it works in groups with external users
- Please follow Telegram's Terms of Service
- Avoid spam or sending large volumes of messages

### Slack

- The bot needs the correct scopes
- The bot can't post to channels it hasn't been added to
- Watch out for rate limits (normal business use is fine)

### Security

- Keep your API keys and tokens safe
- `data/config.json` contains your credentials — never commit it to Git
- `groups.json` (your registered groups) contains no secrets and **is** committed, so a fresh clone keeps all your groups. Keep the repository private, as it lists your group and channel names
- `telegram_session.session` is a logged-in Telegram session — treat it like a password and never commit it either
- Both are already excluded in `.gitignore`

## Troubleshooting

### Can't connect to Telegram

- Check that your API ID, API Hash and phone number are correct
- If the verification code dialog doesn't appear in the GUI, restart the app
- Check your firewall and proxy settings

### Can't post to Slack

- Check that the bot token is correct
- Check that the bot has the required scopes
- Check that the bot has been added to the channel (`/invite @bot-name`)
- If you see a `not_in_channel` error, add the bot to the channel

### A group doesn't appear

- Check that you're a member of the group in Telegram
- It may be a private chat rather than a group (private chats aren't supported)
- If asked for a verification code, enter it in the GUI

### SSL certificate error (macOS)

- Run `pip install --upgrade certifi`
- If that doesn't fix it, note that SSL certificates are already configured in the code

### Encoding errors on Windows

If you see errors like `'charmap' codec can't encode character` or `'locale' codec can't encode character`, Windows is using a non-UTF-8 code page. These usually happen when the app is started some other way than `run_windows.bat` (which switches the console to UTF-8).

**Fix 1: start the app with `run_windows.bat` (recommended)**

**Fix 2: enable UTF-8 support in Windows**

1. **Settings** → **Time & language** → **Language & region** → **Administrative language settings**
2. Click "**Change system locale**"
3. Check "**Beta: Use Unicode UTF-8 for worldwide language support**"
4. Restart your PC

## Project structure

```
forward_to_slack/
├── gui.py                    # Flet GUI (entry point)
├── config.py                 # Settings management
├── telegram_handler.py       # Telegram API integration
├── slack_handler.py          # Slack API integration
├── message_forwarder.py      # Forwarding logic
├── run_windows.bat           # Windows start script (includes setup)
├── run_mac.sh                # macOS/Linux start script (includes setup)
├── requirements.txt          # Dependencies (pinned versions)
├── .gitignore                # Git exclusions
├── groups.json               # Registered groups (in Git, as a backup)
├── data/                     # Created automatically, not in Git
│   ├── config.json           # Telegram/Slack credentials
│   └── thread_cache.json     # Thread cache
├── downloads/                # Temporary media files (auto-created and auto-deleted)
├── venv/                     # Python virtual environment (auto-created)
├── telegram_session.session  # Telegram login session (auto-created, not in Git)
└── README.md                 # This file
```

## Technical details

### Dependencies

- **Telethon 1.42.0** - Telegram MTProto API client
- **slack-sdk 3.39.0** - Slack Web API client
- **flet 0.28.3** - Cross-platform GUI framework
- **python-dotenv 1.2.1** - Environment variable management
- **aiofiles 25.1.0** - Async file operations

### Automatic version management

The start scripts (`run_windows.bat` / `run_mac.sh`):

- Create the virtual environment automatically (first run only)
- Check installed packages against `requirements.txt`
- Update packages automatically when versions don't match
- Resolve dependencies automatically

### File size limit

- Slack upload limit: 1GB per file
- For files over 1GB, only a warning message is posted and the upload is skipped

## Support

If something goes wrong, check:

1. Your Python version (3.9 or later)
2. That you started the app with `run_windows.bat` or `run_mac.sh`
3. That your API keys and token are correct
4. Your firewall and network settings
5. That the Slack bot has been added to the channel (`/invite @bot-name`)

### FAQ

**Q: I deleted the virtual environment.**
A: Run `run_windows.bat` or `run_mac.sh` and it will be recreated automatically.

**Q: I want to change a package version.**
A: Edit `requirements.txt`; it will be synced automatically on the next launch.

**Q: Startup is slow.**
A: The first launch and package updates take a while. Later launches are fast.

---

Created: 2025
Last updated: 2026-11-12 (English translation, registered-group search)
