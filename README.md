🎮 Roblox Update Tracker Bot
A Discord bot that monitors Roblox and Roblox Studio for new version deployments, release notes, beta features, and DevForum announcements — and posts them to your server automatically.
---
✨ Features
🔔 Auto-alerts when a new Roblox client version is deployed
🛠️ Studio update detection — separate alerts for Roblox Studio
📢 DevForum announcements pulled directly from Roblox staff posts
📋 Release notes from the official Roblox releases category
🔭 Upcoming & beta features filtered from DevForum
📦 CDN deploy history for the technically curious
⚡ Checks for updates every 15 minutes, around the clock
---
🤖 Commands
Command	Description
`/roblox_version`	Current live Roblox client version
`/studio_version`	Current live Roblox Studio version
`/latest_updates`	Latest DevForum announcements
`/release_notes`	Official Roblox release notes
`/upcoming_features`	Beta & upcoming features
`/deploy_history`	Last 15 CDN deploy log entries
`/set_update_channel`	Set your alert channel (Admin only)
`/help_roblox`	Show all commands
---
🚀 Setup
1. Clone the repo
```bash
git clone https://github.com/YOURUSERNAME/roblox-update-bot.git
cd roblox-update-bot
```
2. Install dependencies
```bash
pip install -r requirements.txt
```
3. Configure the bot
Open `bot.py` and edit the top section:
```python
BOT_TOKEN         = "your token here"
UPDATE_CHANNEL_ID = 0        # or set via /set_update_channel
CHECK_INTERVAL_MINUTES = 15
```
4. Run the bot
```bash
python bot.py
```
---
🔧 Requirements
Python 3.11 or newer
discord.py 2.3+
aiohttp
beautifulsoup4
lxml
All dependencies are listed in `requirements.txt`
---
📋 Permissions Needed
Permission	Reason
Send Messages	Post update alerts
Embed Links	Send formatted embed cards
Read Message History	Read the alert channel
View Channels	See the channel to post in
Permission integer: `277025392640`
---
🌐 Hosting 24/7
Platform	Cost	Notes
Railway	Free tier	Easiest option
Render	Free tier	Background worker
Replit	Free	Pair with UptimeRobot
VPS / Home server	Varies	Use `pm2` or `screen`
---
⚠️ Disclaimer
This bot is not affiliated with or endorsed by Roblox Corporation. It only reads publicly available Roblox APIs and RSS feeds. All Roblox trademarks belong to Roblox Corporation.
---
📄 License
This project is licensed under the MIT License
---
📃 Terms of Service
By using this bot you agree to the Terms of Service
---
🐛 Issues & Contributions
Found a bug or want to suggest a feature? Open an issue on GitHub or submit a pull request — contributions are welcome!
---
Made with ❤️ for the Roblox community
