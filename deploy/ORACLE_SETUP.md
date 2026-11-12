# Moving the forwarder to Oracle Cloud (Always Free)

This replaces "laptop open 24/7". The server runs `run_server.py` (no window) as a
service that starts on boot and restarts itself after crashes or disconnects.

Commands marked **Laptop** run in PowerShell on your Windows laptop, from the
project folder (`C:\Users\USer\Desktop\TelegramSlackToolShare\code_10`).
Commands marked **Server** run on the server after you connect with `ssh`.

---

## 1. Create the Oracle Cloud account

1. Sign up at https://signup.cloud.oracle.com
2. **Home region**: pick one close to you, e.g. *Singapore*. It can't be changed later.
3. A credit card is required for verification. Always Free resources are not charged.
4. *(Recommended)* After the account is active, upgrade to **Pay As You Go**
   (Billing → Upgrade). You still pay $0 if you only use Always Free resources,
   but Oracle stops reclaiming "idle" free machines — and this app is mostly idle.

## 2. Create the server

Menu → **Compute → Instances → Create instance**

| Setting | Value |
|---|---|
| Name | `telegram-forwarder` |
| Image | **Canonical Ubuntu 24.04** |
| Shape | **VM.Standard.E2.1.Micro** (AMD, "Always Free-eligible") — or **VM.Standard.A1.Flex** with 1 OCPU / 6 GB if available |
| Networking | Keep defaults (public subnet, **assign a public IPv4 address**) |
| SSH keys | **Generate a key pair for me** → click **Save private key** |

Click **Create**. When it shows *Running*, copy the **Public IP address**.

> "Out of capacity" for A1.Flex is common — just use E2.1.Micro. It's enough for this app.

No firewall ports need to be opened: the forwarder only makes outgoing connections.

**Laptop** — move the downloaded key somewhere safe and lock it down
(Windows' ssh refuses keys that other users can read):

```powershell
mkdir $HOME\.ssh -Force
Move-Item $HOME\Downloads\ssh-key-*.key $HOME\.ssh\oracle.key
icacls $HOME\.ssh\oracle.key /inheritance:r /grant:r "$($env:USERNAME):R"
```

Test the connection (replace `SERVER_IP`; type `yes` the first time):

```powershell
ssh -i $HOME\.ssh\oracle.key ubuntu@SERVER_IP
```

Type `exit` to come back to the laptop.

## 3. Stop the laptop and copy the project

1. In the laptop app click **Stop Forwarding**, then **close the app**.
   (The session file and thread cache must not be in use while copying, and
   the laptop and server must never forward at the same time.)

2. **Laptop** — copy the code, groups, keys, thread cache and Telegram login:

```powershell
$ip  = "SERVER_IP"
$key = "$HOME\.ssh\oracle.key"
ssh -i $key ubuntu@$ip "mkdir -p forward_to_slack/data forward_to_slack/deploy"
scp -i $key config.py message_forwarder.py slack_handler.py telegram_handler.py run_server.py requirements-server.txt groups.json telegram_session.session ubuntu@${ip}:forward_to_slack/
scp -i $key deploy/setup_server.sh deploy/telegram-forwarder.service ubuntu@${ip}:forward_to_slack/deploy/
scp -i $key data/config.json data/thread_cache.json ubuntu@${ip}:forward_to_slack/data/
```

## 4. Install on the server

```powershell
ssh -i $HOME\.ssh\oracle.key ubuntu@SERVER_IP
```

**Server:**

```bash
cd ~/forward_to_slack
bash deploy/setup_server.sh
```

This installs Python, sets the time zone to UTC+7 (`Asia/Bangkok`, same as the
laptop — threads roll over at your midnight), installs the auto-restart service
and runs a check. You should see:

```
Slack: OK
Telegram: OK (logged in)
Groups: N enabled / N total
```

If Telegram says **NOT LOGGED IN**, run `venv/bin/python run_server.py --login`,
enter the code Telegram sends you (and your 2-step password), then continue.

## 5. Switch over and test

**Server:**

```bash
sudo systemctl start telegram-forwarder
journalctl -u telegram-forwarder -f
```

Send a message in your **Forwarder test** Telegram group and check it appears in
`#seats-forwarding_tool` on Slack, and in the log. Press `Ctrl+C` to stop
watching the log (the service keeps running).

Then reboot once to prove it comes back by itself:

```bash
sudo reboot
# wait ~1 minute, ssh in again, then:
systemctl status telegram-forwarder
```

Your laptop can now be turned off. 🎉

---

## Everyday commands (Server)

| What | Command |
|---|---|
| Is it running? | `systemctl status telegram-forwarder` |
| Live log | `journalctl -u telegram-forwarder -f` |
| Last hour of log | `journalctl -u telegram-forwarder --since "1 hour ago"` |
| Restart | `sudo systemctl restart telegram-forwarder` |
| Stop | `sudo systemctl stop telegram-forwarder` |
| Check setup | `cd ~/forward_to_slack && venv/bin/python run_server.py --check` |

## Adding / editing groups

The server has no window, so edit groups with the laptop app. The laptop app
logs in to Telegram with the same session to list groups, so **stop the server
first** to avoid using one login from two places at once.

1. **Server:** `sudo systemctl stop telegram-forwarder`
2. **Laptop:** open the app, add/edit groups — **don't** click Start Forwarding — close the app.
3. **Laptop:** upload only the group list (not the thread cache — the server's is newer):
   ```powershell
   scp -i $HOME\.ssh\oracle.key groups.json ubuntu@SERVER_IP:forward_to_slack/
   ```
   (The laptop app already backed the change up to GitHub automatically.)
4. **Server:** `sudo systemctl start telegram-forwarder`

## Updating the code

**Laptop:** copy the changed `.py` file(s) as in step 3, then
**Server:** `sudo systemctl restart telegram-forwarder`.

## Going back to the laptop

1. **Server:** `sudo systemctl stop telegram-forwarder && sudo systemctl disable telegram-forwarder`
2. **Laptop:** download the newer thread cache so today's threads continue:
   ```powershell
   scp -i $HOME\.ssh\oracle.key ubuntu@SERVER_IP:forward_to_slack/data/thread_cache.json data/
   ```
3. Open the laptop app and click **Start Forwarding**.

## Troubleshooting

- **`UNPROTECTED PRIVATE KEY FILE` / `Permission denied (publickey)`** — rerun the
  `icacls` command in step 2 and make sure you use the user `ubuntu`.
- **Service stopped with "Telegram is not logged in"** — the session was rejected
  (e.g. it was used on the laptop at the same time). Run
  `sudo systemctl stop telegram-forwarder`, then
  `cd ~/forward_to_slack && venv/bin/python run_server.py --login`, then start it again.
- **Threads change at the wrong hour** — check `timedatectl`; fix with
  `sudo timedatectl set-timezone Asia/Bangkok` and restart the service.
- **The server disappeared** — Oracle reclaimed an idle free instance. Upgrade to
  Pay As You Go (step 1.4) and recreate it.
