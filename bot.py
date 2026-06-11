cat > /mnt/user-data/outputs/roblox_update_bot/bot.py << 'BOTEOF'
"""
Roblox Update Tracker Bot — Ultimate Edition
"""

import asyncio
import collections
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BOT_TOKEN              = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
UPDATE_CHANNEL_ID      = int(os.getenv("UPDATE_CHANNEL_ID", "0"))
CHECK_INTERVAL_MINUTES = 15
PING_EVERYONE          = True

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("roblox-bot")

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
ROBLOX_CLIENT_VERSION_URL  = "https://clientsettingscdn.roblox.com/v2/client-version/WindowsPlayer"
DEVFORUM_ANNOUNCEMENTS_URL = "https://devforum.roblox.com/c/announcements/official-roblox-staff/191.json"
DEVFORUM_RELEASES_URL      = "https://devforum.roblox.com/c/updates/releases/36.json"
DEVFORUM_BETA_URL          = "https://devforum.roblox.com/c/updates/beta-features/22.json"
ROBLOX_DEPLOY_LOG_URL      = "https://setup.rbxcdn.com/DeployHistory.txt"
ROBLOX_STATUS_SUMMARY_URL  = "https://status.roblox.com/api/v2/summary.json"
ROBLOX_INCIDENTS_URL       = "https://status.roblox.com/api/v2/incidents/unresolved.json"
ROBLOX_INCIDENT_HISTORY_URL= "https://status.roblox.com/api/v2/incidents.json"
ROBLOX_GAME_API_URL        = "https://games.roblox.com/v1/games?universeIds={}"
ROBLOX_UNIVERSE_URL        = "https://apis.roblox.com/universes/v1/places/{}/universe"
ROBLOX_CATALOG_URL         = "https://catalog.roblox.com/v1/search/items/details?Category=1&salesTypeFilter=1&limit=30&sortType=3"
ROBLOX_ECONOMY_URL         = "https://economy.roblox.com/v1/assets/{}/resale-data"
ROBLOX_ITEM_DETAILS_URL    = "https://catalog.roblox.com/v1/catalog/items/{}/details"
ROBLOX_USER_URL            = "https://users.roblox.com/v1/users/search?keyword={}&limit=10"
ROBLOX_USER_ID_URL         = "https://users.roblox.com/v1/users/{}"
ROBLOX_USER_FRIENDS_URL    = "https://friends.roblox.com/v1/users/{}/friends/count"
ROBLOX_USER_BADGES_URL     = "https://badges.roblox.com/v1/users/{}/badges?limit=10"
ROBLOX_GROUP_URL           = "https://groups.roblox.com/v1/groups/{}"
ROBLOX_BADGE_URL           = "https://badges.roblox.com/v1/badges/{}"
ROBLOX_USER_HAS_BADGE_URL  = "https://badges.roblox.com/v1/users/{}/badges/awarded-dates?badgeIds={}"
ROBLOX_GAMES_LIST_URL      = "https://games.roblox.com/v1/games/list?sortToken=&gameFilter=default&startRows=0&maxRows=20"

# ---------------------------------------------------------------------------
# Auto-mod helpers
# ---------------------------------------------------------------------------
LEET_MAP = {ord('@'): 'a', ord('3'): 'e', ord('1'): 'i', ord('0'): 'o',
            ord('5'): 's', ord('$'): 's', ord('4'): 'a', ord('7'): 't',
            ord('+'): 't', ord('!'): 'i', ord('|'): 'i'}

DEFAULT_BAD_WORDS = [
    "fuck", "shit", "bitch", "cunt", "dick", "cock", "pussy", "nigger",
    "nigga", "faggot", "retard", "whore", "slut", "asshole", "bastard",
]

def _normalize(text: str) -> str:
    text = text.lower().translate(LEET_MAP)
    text = re.sub(r'[^a-z0-9\s]', '', text)
    text = re.sub(r'(.)\1{2,}', r'\1\1', text)
    text = re.sub(r'(?<!\w)(\w)\s+(?=(\w\s)*\w(?!\w))', r'\1', text)
    return text

PRESENCE_ACTIVITIES = [
    ("Tracking Roblox updates",  discord.ActivityType.watching),
    ("for new builds",           discord.ActivityType.watching),
    ("Roblox v{client}",         discord.ActivityType.playing),
    ("DevForum announcements",   discord.ActivityType.watching),
    ("for security patches",     discord.ActivityType.watching),
    ("the UGC market",           discord.ActivityType.watching),
]

# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------
class RobloxBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

        self.update_channel_id: int = UPDATE_CHANNEL_ID
        self._session: aiohttp.ClientSession | None = None
        self._start_time: float = time.time()
        self._presence_index: int = 0
        self._command_uses: int = 0
        self._muted_until: float = 0
        self._filters: dict = {"client": True, "devforum": True, "incident": True}
        self._alert_threshold: float = 0.0
        self._last_client_version: str | None = None
        self._last_incident_id:    str | None = None
        self._last_devforum_id:    int | None = None
        self._last_check_time:     str        = "Never"
        self._client_changelog: list[dict] = []
        self._watched_items: dict[int, dict] = {}
        self._warnings: dict[str, list[dict]] = {}
        self._log_channel_id: int | None = None
        self._audit_log: list[dict] = []
        self._ping_role_id: int | None = None
        self._autorole_id: int | None = None
        self._scheduled: list[dict] = []
        self._prefix: str = "!"
        self._antiraid_enabled:   bool  = False
        self._antiraid_auto:      bool  = True
        self._antiraid_threshold: int   = 10
        self._antiraid_window:    int   = 10
        self._antiraid_action:    str   = "kick"
        self._join_times: collections.deque = collections.deque()
        self._mod_role_id:   int | None = None
        self._admin_role_id: int | None = None
        self._automod_enabled: bool      = False
        self._automod_words:   list[str] = list(DEFAULT_BAD_WORDS)
        self._automod_strikes: dict[str, int] = {}
        self._automod_penalty: str = "timeout_week"
        self._automod_log: list[dict] = []
        self._reports:     list[dict] = []
        self._load_data()

    DATA_FILE = "bot_data.json"

    def _load_data(self):
        try:
            with open(self.DATA_FILE, "r") as f:
                d = json.load(f)
            self._warnings        = d.get("warnings", {})
            self._log_channel_id  = d.get("log_channel_id")
            self._audit_log       = d.get("audit_log", [])
            self._ping_role_id    = d.get("ping_role_id")
            self._autorole_id     = d.get("autorole_id")
            self._scheduled       = d.get("scheduled", [])
            self._prefix          = d.get("prefix", "!")
            self._filters         = d.get("filters", {"client": True, "devforum": True, "incident": True})
            self._alert_threshold = d.get("alert_threshold", 0.0)
            watched = d.get("watched_items", {})
            self._watched_items   = {int(k): v for k, v in watched.items()}
            self._antiraid_auto      = d.get("antiraid_auto", True)
            self._antiraid_threshold = d.get("antiraid_threshold", 10)
            self._antiraid_window    = d.get("antiraid_window", 10)
            self._antiraid_action    = d.get("antiraid_action", "kick")
            self._mod_role_id        = d.get("mod_role_id")
            self._admin_role_id      = d.get("admin_role_id")
            self._automod_enabled    = d.get("automod_enabled", False)
            self._automod_words      = d.get("automod_words", list(DEFAULT_BAD_WORDS))
            self._automod_penalty    = d.get("automod_penalty", "timeout_week")
            self._automod_log        = d.get("automod_log", [])
            self._reports            = d.get("reports", [])
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_data(self):
        try:
            with open(self.DATA_FILE, "w") as f:
                json.dump({
                    "warnings":        self._warnings,
                    "log_channel_id":  self._log_channel_id,
                    "audit_log":       self._audit_log[-200:],
                    "ping_role_id":    self._ping_role_id,
                    "autorole_id":     self._autorole_id,
                    "scheduled":       self._scheduled,
                    "prefix":          self._prefix,
                    "filters":         self._filters,
                    "alert_threshold": self._alert_threshold,
                    "watched_items":      {str(k): v for k, v in self._watched_items.items()},
                    "antiraid_auto":      self._antiraid_auto,
                    "antiraid_threshold": self._antiraid_threshold,
                    "antiraid_window":    self._antiraid_window,
                    "antiraid_action":    self._antiraid_action,
                    "mod_role_id":        self._mod_role_id,
                    "admin_role_id":      self._admin_role_id,
                    "automod_enabled":    self._automod_enabled,
                    "automod_words":      self._automod_words,
                    "automod_penalty":    self._automod_penalty,
                    "automod_log":        self._automod_log[-100:],
                    "reports":            self._reports[-200:],
                }, f, indent=2)
        except Exception as e:
            log.warning("Failed to save data: %s", e)

    def _add_audit(self, action: str, user, detail: str = ""):
        self._audit_log.append({
            "time":   datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "action": action,
            "by":     f"{user} ({user.id})",
            "detail": detail,
        })
        self._audit_log = self._audit_log[-200:]
        self._save_data()

    async def _log_action(self, embed: discord.Embed):
        if self._log_channel_id:
            ch = self.get_channel(self._log_channel_id)
            if ch:
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass

    async def setup_hook(self):
        # Sync globally first so commands appear everywhere
        await self.tree.sync()
        log.info("Global command sync complete")
        self.poll_updates.start()
        self.rotate_presence.start()
        self.poll_ugc_prices.start()
        self.check_scheduled.start()

    async def on_ready(self):
        self._start_time = time.time()
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        # Also sync to each guild for instant propagation
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                log.info("Synced to guild %s", guild.name)
            except Exception as e:
                log.warning("Guild sync failed %s: %s", guild.id, e)
        channel = self.get_channel(self.update_channel_id)
        if channel:
            cv = await self.get_client_version()
            em = discord.Embed(
                title="🚀 Roblox Update Tracker — Online",
                description="Bot is online and monitoring for updates!",
                colour=0x4cc9f0,
                timestamp=datetime.now(timezone.utc),
            )
            em.add_field(name="🎮 Client", value=f"`{cv or 'N/A'}`", inline=True)
            em.set_footer(text=f"Polling every {CHECK_INTERVAL_MINUTES} min")
            await channel.send(embed=em)

    async def _session_(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers={"User-Agent": "RobloxUpdateBot/3.0"})
        return self._session

    async def _json(self, url: str):
        s = await self._session_()
        try:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
        except Exception as e:
            log.warning("fetch_json %s: %s", url, e)
        return None

    async def _text(self, url: str):
        s = await self._session_()
        try:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return await r.text()
        except Exception as e:
            log.warning("fetch_text %s: %s", url, e)
        return None

    async def get_client_version(self) -> str | None:
        d = await self._json(ROBLOX_CLIENT_VERSION_URL)
        return d.get("clientVersionUpload") or d.get("version") if d else None

    async def get_devforum_posts(self, url: str, limit: int = 5) -> list[dict]:
        d = await self._json(url)
        if not d:
            return []
        topics = d.get("topic_list", {}).get("topics", [])
        return [{"id": t.get("id"), "title": t.get("title","Untitled"),
                 "url": f"https://devforum.roblox.com/t/{t.get('slug','')}/{t.get('id','')}",
                 "posts_count": t.get("posts_count", 0)} for t in topics[:limit]]

    async def get_deploy_history(self, lines: int = 15) -> list[str]:
        text = await self._text(ROBLOX_DEPLOY_LOG_URL)
        if not text:
            return []
        return [l.strip() for l in text.splitlines() if l.strip()][-lines:]

    async def get_status_summary(self) -> dict | None:
        return await self._json(ROBLOX_STATUS_SUMMARY_URL)

    async def get_unresolved_incidents(self) -> list[dict]:
        d = await self._json(ROBLOX_INCIDENTS_URL)
        if not d:
            return []
        return [{"id": inc.get("id"), "name": inc.get("name","Unknown"),
                 "status": inc.get("status",""), "impact": inc.get("impact","none"),
                 "url": inc.get("shortlink","https://status.roblox.com"),
                 "created_at": inc.get("created_at",""),
                 "latest_update": (inc.get("incident_updates") or [{}])[0].get("body","No details")[:300]}
                for inc in d.get("incidents",[])]

    async def get_incident_history(self, limit: int = 10) -> list[dict]:
        d = await self._json(ROBLOX_INCIDENT_HISTORY_URL)
        if not d:
            return []
        return [{"name": inc.get("name","?"), "status": inc.get("status",""),
                 "impact": inc.get("impact","none"), "url": inc.get("shortlink",""),
                 "created_at": inc.get("created_at","")[:10]}
                for inc in d.get("incidents",[])[:limit]]

    async def get_game_info(self, universe_id: int) -> dict | None:
        d = await self._json(ROBLOX_GAME_API_URL.format(universe_id))
        return d["data"][0] if d and d.get("data") else None

    async def get_universe_id(self, place_id: int) -> int | None:
        d = await self._json(ROBLOX_UNIVERSE_URL.format(place_id))
        return d.get("universeId") if d else None

    async def get_catalog_items(self, limit: int = 8) -> list[dict]:
        d = await self._json(ROBLOX_CATALOG_URL)
        if not d:
            return []
        return [{"id": i.get("id"), "name": i.get("name","?"),
                 "price": i.get("price") or i.get("lowestPrice") or 0,
                 "creator": i.get("creatorName","?")} for i in d.get("data",[])[:limit]]

    async def get_item_resale(self, asset_id: int) -> dict | None:
        return await self._json(ROBLOX_ECONOMY_URL.format(asset_id))

    async def get_item_details(self, asset_id: int) -> dict | None:
        return await self._json(ROBLOX_ITEM_DETAILS_URL.format(asset_id))

    async def lookup_user(self, username: str) -> dict | None:
        d = await self._json(ROBLOX_USER_URL.format(username))
        if d and d.get("data"):
            uid = d["data"][0]["id"]
            return await self._json(ROBLOX_USER_ID_URL.format(uid))
        return None

    async def get_friend_count(self, user_id: int) -> int:
        d = await self._json(ROBLOX_USER_FRIENDS_URL.format(user_id))
        return d.get("count", 0) if d else 0

    async def get_user_badges(self, user_id: int) -> list[dict]:
        d = await self._json(ROBLOX_USER_BADGES_URL.format(user_id))
        return d.get("data", []) if d else []

    async def get_group(self, group_id: int) -> dict | None:
        return await self._json(ROBLOX_GROUP_URL.format(group_id))

    async def get_badge(self, badge_id: int) -> dict | None:
        return await self._json(ROBLOX_BADGE_URL.format(badge_id))

    async def user_has_badge(self, user_id: int, badge_id: int) -> bool:
        d = await self._json(ROBLOX_USER_HAS_BADGE_URL.format(user_id, badge_id))
        return bool(d and d.get("data"))

    @tasks.loop(minutes=5)
    async def rotate_presence(self):
        cv = self._last_client_version or "unknown"
        label, atype = PRESENCE_ACTIVITIES[self._presence_index % len(PRESENCE_ACTIVITIES)]
        await self.change_presence(activity=discord.Activity(type=atype, name=label.replace("{client}", cv)))
        self._presence_index += 1

    @rotate_presence.before_loop
    async def before_presence(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=30)
    async def poll_ugc_prices(self):
        if not self._watched_items:
            return
        channel = self.get_channel(self.update_channel_id)
        if not channel:
            return
        for asset_id, info in list(self._watched_items.items()):
            resale = await self.get_item_resale(asset_id)
            if not resale:
                continue
            new_price = resale.get("recentAveragePrice") or resale.get("originalPrice") or 0
            old_price = info.get("price", 0)
            if not old_price or not new_price or new_price == old_price:
                continue
            change = new_price - old_price
            pct = abs(change / old_price * 100)
            if pct < self._alert_threshold:
                continue
            direction = "📈 UP" if change > 0 else "📉 DOWN"
            color = 0x06d6a0 if change > 0 else 0xe63946
            em = discord.Embed(title=f"{direction} — UGC Price Change!", colour=color, timestamp=datetime.now(timezone.utc))
            em.description = f"**[{info.get('name','Item')}](https://www.roblox.com/catalog/{asset_id})**"
            em.add_field(name="Old Price", value=f"R${old_price:,}", inline=True)
            em.add_field(name="New Price", value=f"R${new_price:,}", inline=True)
            em.add_field(name="Change",    value=f"{'+' if change>0 else ''}{change:,} ({pct:+.1f}%)", inline=True)
            em.set_footer(text="Roblox Economy Tracker")
            await channel.send(content="@everyone\n" if PING_EVERYONE else "", embed=em)
            self._watched_items[asset_id]["price"] = new_price

    @poll_ugc_prices.before_loop
    async def before_ugc(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=30)
    async def check_scheduled(self):
        now = time.time()
        remaining = []
        for item in self._scheduled:
            if now >= item["send_at"]:
                ch = self.get_channel(item["channel_id"])
                if ch:
                    em = discord.Embed(
                        title=item.get("title", "📢 Announcement"),
                        description=item["message"],
                        colour=0x4cc9f0,
                        timestamp=datetime.now(timezone.utc),
                    )
                    em.set_footer(text=f"Scheduled by {item['author']}")
                    try:
                        await ch.send(embed=em)
                    except Exception as e:
                        log.warning("Scheduled announcement failed: %s", e)
            else:
                remaining.append(item)
        if len(remaining) != len(self._scheduled):
            self._scheduled = remaining
            self._save_data()

    @check_scheduled.before_loop
    async def before_scheduled(self):
        await self.wait_until_ready()

    async def on_member_join(self, member: discord.Member):
        now = time.time()
        self._join_times.append(now)
        while self._join_times and self._join_times[0] < now - self._antiraid_window:
            self._join_times.popleft()
        if (self._antiraid_auto and not self._antiraid_enabled
                and len(self._join_times) >= self._antiraid_threshold):
            self._antiraid_enabled = True
            alert_em = discord.Embed(
                title="🚨 ANTI-RAID LOCKDOWN TRIGGERED",
                description=f"**{len(self._join_times)} members** joined in **{self._antiraid_window}s** — lockdown!\nUse `/antiraid_off` to disable.",
                colour=0xe63946, timestamp=datetime.now(timezone.utc),
            )
            await self._log_action(alert_em)
        if self._antiraid_enabled:
            try:
                reason = "Anti-raid lockdown"
                if self._antiraid_action == "ban":
                    await member.ban(reason=reason, delete_message_days=0)
                else:
                    await member.kick(reason=reason)
            except Exception as e:
                log.warning("Anti-raid action failed: %s", e)
            return
        if self._autorole_id:
            role = member.guild.get_role(self._autorole_id)
            if role:
                try:
                    await member.add_roles(role, reason="Auto-role")
                except Exception as e:
                    log.warning("Auto-role failed: %s", e)

    async def on_message(self, message: discord.Message):
        if message.author.bot or not self._automod_enabled or not message.guild:
            return
        content = message.content
        if not content:
            return
        normalized = _normalize(content)
        triggered_word = next((w for w in self._automod_words if w in normalized), None)
        if not triggered_word:
            return
        try:
            await message.delete()
        except Exception:
            pass
        uid = str(message.author.id)
        self._automod_strikes[uid] = self._automod_strikes.get(uid, 0) + 1
        strikes = self._automod_strikes[uid]
        import datetime as dt
        member = message.author
        try:
            if strikes >= 3:
                if self._automod_penalty == "kick":
                    await member.kick(reason=f"Auto-mod: profanity ({strikes} strikes)")
                    action_text = "**Kicked**"
                    self._automod_strikes[uid] = 0
                else:
                    until = discord.utils.utcnow() + dt.timedelta(days=7)
                    await member.timeout(until, reason=f"Auto-mod: profanity ({strikes} strikes)")
                    action_text = "**7-day timeout**"
                color = 0xe63946
            else:
                until = discord.utils.utcnow() + dt.timedelta(minutes=10)
                await member.timeout(until, reason=f"Auto-mod: profanity (strike {strikes}/3)")
                action_text = "**10-min timeout**"
                color = 0xffd166
        except discord.Forbidden:
            action_text = "⚠️ Could not punish (missing perms)"
            color = 0xaaaaaa
        warn_em = discord.Embed(
            title="🤬 Language Warning",
            description=f"{member.mention} your message was removed.\nStrike **{strikes}/3** — {action_text}.",
            colour=color, timestamp=datetime.now(timezone.utc),
        )
        try:
            await message.channel.send(embed=warn_em, delete_after=15)
        except Exception:
            pass
        self._automod_log.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "user": f"{member} ({member.id})",
            "uid": str(member.id),
            "word": triggered_word,
            "strikes": strikes,
            "action": action_text,
            "channel": str(message.channel),
        })
        self._automod_log = self._automod_log[-100:]
        self._save_data()

    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def poll_updates(self):
        self._last_check_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if time.time() < self._muted_until:
            return
        channel = self.get_channel(self.update_channel_id)
        if not channel:
            return
        ping = "@everyone\n" if PING_EVERYONE else ""
        now = datetime.now(timezone.utc)
        ts = now.strftime("%B %d, %Y %I:%M %p")
        date_str = now.strftime("%m/%d/%Y %I:%M %p")

        if self._filters.get("client"):
            cv = await self.get_client_version()
            if cv and cv != self._last_client_version:
                if self._last_client_version is not None:
                    self._client_changelog.append({"version": cv, "time": self._last_check_time})
                    self._client_changelog = self._client_changelog[-10:]
                    em = discord.Embed(
                        title="🚨 Roblox Update Detected!",
                        description="This is a live update, Roblox is **patched**.",
                        colour=0xe63946, timestamp=now,
                    )
                    em.add_field(name="Platform",     value="Windows", inline=False)
                    em.add_field(name="Version Hash", value=f"`{cv}`", inline=False)
                    em.add_field(name="Date",         value=ts,        inline=False)
                    em.set_footer(text=date_str)
                    await channel.send(content=ping, embed=em)
                self._last_client_version = cv

        if self._filters.get("devforum"):
            posts = await self.get_devforum_posts(DEVFORUM_ANNOUNCEMENTS_URL, limit=1)
            if posts:
                latest = posts[0]
                if latest["id"] != self._last_devforum_id:
                    if self._last_devforum_id is not None:
                        em = discord.Embed(title="📢 New DevForum Announcement",
                                           description=f"[{latest['title']}]({latest['url']})",
                                           colour=0xffd166, timestamp=now)
                        em.set_footer(text="Roblox DevForum")
                        await channel.send(content=ping, embed=em)
                    self._last_devforum_id = latest["id"]

        if self._filters.get("incident"):
            incidents = await self.get_unresolved_incidents()
            if incidents:
                latest_inc = incidents[0]
                if latest_inc["id"] != self._last_incident_id:
                    if self._last_incident_id is not None:
                        colors = {"none":0x06d6a0,"minor":0xffd166,"major":0xff6b35,"critical":0xe63946}
                        em = discord.Embed(title=f"🚨 Roblox Incident: {latest_inc['name']}",
                                           description=latest_inc["latest_update"],
                                           colour=colors.get(latest_inc["impact"],0xaaa), timestamp=now)
                        em.add_field(name="Status", value=latest_inc["status"].replace("_"," ").title(), inline=True)
                        em.add_field(name="Impact", value=latest_inc["impact"].title(), inline=True)
                        em.add_field(name="Details", value=f"[View]({latest_inc['url']})", inline=False)
                        em.set_footer(text="status.roblox.com")
                        await channel.send(content=ping, embed=em)
                    self._last_incident_id = latest_inc["id"]

    @poll_updates.before_loop
    async def before_poll(self):
        await self.wait_until_ready()


# ---------------------------------------------------------------------------
# Bot instance
# ---------------------------------------------------------------------------
bot = RobloxBot()

# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------
def mod_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        m = interaction.user
        if m.guild_permissions.administrator:
            return True
        if bot._admin_role_id:
            r = interaction.guild.get_role(bot._admin_role_id)
            if r and r in m.roles:
                return True
        if bot._mod_role_id:
            r = interaction.guild.get_role(bot._mod_role_id)
            if r and r in m.roles:
                return True
        if any([m.guild_permissions.manage_messages, m.guild_permissions.kick_members,
                m.guild_permissions.ban_members, m.guild_permissions.moderate_members]):
            return True
        raise app_commands.MissingPermissions(["manage_messages"])
    return app_commands.check(predicate)

def admin_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        m = interaction.user
        if m.guild_permissions.administrator:
            return True
        if bot._admin_role_id:
            r = interaction.guild.get_role(bot._admin_role_id)
            if r and r in m.roles:
                return True
        raise app_commands.MissingPermissions(["administrator"])
    return app_commands.check(predicate)

@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
    else:
        log.error("Command error: %s", error)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred.", ephemeral=True)

# ---------------------------------------------------------------------------
# All slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="roblox_version", description="Current live Roblox client version")
async def cmd_roblox_version(interaction: discord.Interaction):
    await interaction.response.defer()
    v = await bot.get_client_version()
    now = datetime.now(timezone.utc)
    em = discord.Embed(title="🚨 Roblox Update Info", colour=0xe63946, timestamp=now)
    em.add_field(name="Platform",     value="Windows",          inline=False)
    em.add_field(name="Version Hash", value=f"`{v or 'N/A'}`", inline=False)
    em.add_field(name="Date",         value=now.strftime("%B %d, %Y %I:%M %p"), inline=False)
    em.set_footer(text=now.strftime("%m/%d/%Y %I:%M %p"))
    await interaction.followup.send(embed=em)

@bot.tree.command(name="latest_updates", description="Latest DevForum announcements")
async def cmd_latest_updates(interaction: discord.Interaction):
    await interaction.response.defer()
    posts = await bot.get_devforum_posts(DEVFORUM_ANNOUNCEMENTS_URL, limit=5)
    em = discord.Embed(title="📢 Latest DevForum Announcements", colour=0xffd166)
    if posts:
        for p in posts:
            em.add_field(name=p["title"], value=f"[Read more]({p['url']}) • {p['posts_count']} replies", inline=False)
    else:
        em.description = "Could not retrieve announcements right now."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="release_notes", description="Official Roblox release notes")
async def cmd_release_notes(interaction: discord.Interaction):
    await interaction.response.defer()
    posts = await bot.get_devforum_posts(DEVFORUM_RELEASES_URL, limit=5)
    em = discord.Embed(title="📋 Roblox Release Notes", colour=0x06d6a0)
    if posts:
        for p in posts:
            em.add_field(name=p["title"], value=f"[Read more]({p['url']}) • {p['posts_count']} replies", inline=False)
    else:
        em.description = "Could not retrieve release notes right now."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="upcoming_features", description="Beta & upcoming Roblox features")
async def cmd_upcoming_features(interaction: discord.Interaction):
    await interaction.response.defer()
    posts = await bot.get_devforum_posts(DEVFORUM_BETA_URL, limit=5)
    em = discord.Embed(title="🔭 Upcoming & Beta Features", colour=0x9b5de5)
    if posts:
        for p in posts:
            em.add_field(name=p["title"], value=f"[Read more]({p['url']}) • {p['posts_count']} replies", inline=False)
    else:
        em.description = "No upcoming features found right now."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="security_updates", description="Recent Roblox security patches and incidents")
async def cmd_security_updates(interaction: discord.Interaction):
    await interaction.response.defer()
    incidents = await bot.get_unresolved_incidents()
    posts = await bot.get_devforum_posts(DEVFORUM_ANNOUNCEMENTS_URL, limit=10)
    sec = [p for p in posts if any(k in p["title"].lower() for k in ["security","patch","hotfix","vulnerability","exploit","fix"])]
    em = discord.Embed(title="🔒 Security Updates & Patches", colour=0xe63946, timestamp=datetime.now(timezone.utc))
    if incidents:
        for inc in incidents[:3]:
            icon = {"none":"🟢","minor":"🟡","major":"🟠","critical":"🔴"}.get(inc["impact"],"⚪")
            em.add_field(name=f"{icon} {inc['name']}",
                         value=f"`{inc['status'].replace('_',' ').title()}`\n{inc['latest_update'][:150]}\n[View]({inc['url']})", inline=False)
    else:
        em.add_field(name="✅ No Active Incidents", value="Roblox is clean.", inline=False)
    if sec:
        em.add_field(name="━━━━━━━━━━━━━━", value="**Security DevForum Posts**", inline=False)
        for p in sec[:3]:
            em.add_field(name=p["title"], value=f"[Read more]({p['url']})", inline=False)
    em.set_footer(text="status.roblox.com + DevForum")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="status", description="Full Roblox platform status")
async def cmd_status(interaction: discord.Interaction):
    await interaction.response.defer()
    data = await bot.get_status_summary()
    if not data:
        await interaction.followup.send("❌ Could not reach status page.")
        return
    page = data.get("status", {})
    ind = page.get("indicator","none")
    colors = {"none":0x06d6a0,"minor":0xffd166,"major":0xff6b35,"critical":0xe63946}
    icons  = {"none":"🟢","minor":"🟡","major":"🟠","critical":"🔴"}
    em = discord.Embed(title=f"{icons.get(ind,'⚪')} Roblox Platform Status",
                       description=f"**{page.get('description','Unknown')}**",
                       colour=colors.get(ind,0xaaa), timestamp=datetime.now(timezone.utc))
    for comp in data.get("components",[])[:10]:
        s = comp.get("status","?").replace("_"," ").title()
        em.add_field(name=comp.get("name","?"), value=f"{'🟢' if comp.get('status')=='operational' else '🔴'} {s}", inline=True)
    em.set_footer(text="status.roblox.com")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="stats", description="Bot stats")
async def cmd_stats(interaction: discord.Interaction):
    bot._command_uses += 1
    uptime = int(time.time() - bot._start_time)
    h, rem = divmod(uptime, 3600)
    m, s = divmod(rem, 60)
    muted = f"<t:{int(bot._muted_until)}:R>" if time.time() < bot._muted_until else "Not muted"
    em = discord.Embed(title="📊 Bot Stats", colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="⏱️ Uptime",         value=f"{h}h {m}m {s}s",                         inline=True)
    em.add_field(name="🕐 Last Check",     value=bot._last_check_time,                       inline=True)
    em.add_field(name="🔄 Interval",       value=f"Every {CHECK_INTERVAL_MINUTES} min",      inline=True)
    em.add_field(name="🎮 Client Version", value=f"`{bot._last_client_version or 'N/A'}`",   inline=True)
    em.add_field(name="🔔 @everyone",      value="Enabled" if PING_EVERYONE else "Disabled", inline=True)
    em.add_field(name="🔕 Muted",          value=muted,                                      inline=True)
    em.add_field(name="📋 Changelog",      value=f"{len(bot._client_changelog)} entries",    inline=True)
    em.add_field(name="👁️ Watched Items",  value=str(len(bot._watched_items)),               inline=True)
    em.add_field(name="💬 Commands Used",  value=str(bot._command_uses),                     inline=True)
    em.set_footer(text="Roblox Update Tracker")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="changelog", description="Last 10 detected version changes")
async def cmd_changelog(interaction: discord.Interaction):
    bot._command_uses += 1
    em = discord.Embed(title="📅 Version Changelog", colour=0xffd166, timestamp=datetime.now(timezone.utc))
    if bot._client_changelog:
        em.add_field(name="🎮 Client Updates",
                     value="\n".join([f"`{e['version']}` — {e['time']}" for e in reversed(bot._client_changelog)]),
                     inline=False)
    else:
        em.add_field(name="🎮 Client Updates", value="No updates detected this session.", inline=False)
    em.set_footer(text="Resets on restart")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="compare_versions", description="Compare two Roblox version strings")
@app_commands.describe(version1="First version string", version2="Second version string")
async def cmd_compare_versions(interaction: discord.Interaction, version1: str, version2: str):
    bot._command_uses += 1
    def parse(v):
        return [int(x) for x in v.replace("version-","").split(".") if x.isdigit()]
    try:
        v1, v2 = parse(version1), parse(version2)
        if v1 == v2:   result, color = "🟰 **Identical**", 0xaaaaaa
        elif v1 > v2:  result, color = f"⬆️ **`{version1}` is newer**", 0x06d6a0
        else:          result, color = f"⬆️ **`{version2}` is newer**", 0x4cc9f0
    except Exception:
        result, color = "❌ Could not parse versions.", 0xe63946
    em = discord.Embed(title="🔀 Version Comparison", description=result, colour=color)
    em.add_field(name="Version A", value=f"`{version1}`", inline=True)
    em.add_field(name="Version B", value=f"`{version2}`", inline=True)
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="game_status", description="Check status of a Roblox game by Place ID")
@app_commands.describe(place_id="The Roblox Place ID")
async def cmd_game_status(interaction: discord.Interaction, place_id: str):
    bot._command_uses += 1
    await interaction.response.defer()
    try:
        pid = int(place_id)
    except ValueError:
        await interaction.followup.send("❌ Invalid Place ID.")
        return
    uid = await bot.get_universe_id(pid)
    if not uid:
        await interaction.followup.send("❌ Could not find that game.")
        return
    game = await bot.get_game_info(uid)
    if not game:
        await interaction.followup.send("❌ Could not fetch game info.")
        return
    active = game.get("isActive", False)
    em = discord.Embed(title=f"🎮 {game.get('name','Unknown')}", url=f"https://www.roblox.com/games/{pid}",
                       colour=0x06d6a0 if active else 0xe63946, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Status",  value="🟢 Active" if active else "🔴 Inactive", inline=True)
    em.add_field(name="Playing", value=f"{game.get('playing',0):,}",              inline=True)
    em.add_field(name="Visits",  value=f"{game.get('visits',0):,}",               inline=True)
    em.add_field(name="Creator", value=game.get("creator",{}).get("name","?"),    inline=True)
    em.add_field(name="Updated", value=game.get("updated","?")[:10],              inline=True)
    em.set_footer(text="Roblox Games API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="random_game", description="Get a random popular Roblox game")
async def cmd_random_game(interaction: discord.Interaction):
    bot._command_uses += 1
    await interaction.response.defer()
    import random
    d = await bot._json(ROBLOX_GAMES_LIST_URL)
    if not d or not d.get("games"):
        await interaction.followup.send("❌ Could not fetch games list.")
        return
    game = random.choice(d["games"])
    em = discord.Embed(title=f"🎲 Random Game: {game.get('name','?')}",
                       url=f"https://www.roblox.com/games/{game.get('placeId',0)}",
                       colour=0x9b5de5, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Playing", value=f"{game.get('playerCount',0):,}", inline=True)
    em.add_field(name="👍",      value=f"{game.get('totalUpVotes',0):,}", inline=True)
    em.set_footer(text="Roblox Games API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="player_lookup", description="Look up a Roblox player by username")
@app_commands.describe(username="Roblox username")
async def cmd_player_lookup(interaction: discord.Interaction, username: str):
    bot._command_uses += 1
    await interaction.response.defer()
    user = await bot.lookup_user(username)
    if not user:
        await interaction.followup.send("❌ Could not find that user.")
        return
    uid = user.get("id")
    friends = await bot.get_friend_count(uid)
    badges = await bot.get_user_badges(uid)
    em = discord.Embed(title=f"👤 {user.get('displayName','?')} (@{user.get('name','?')})",
                       url=f"https://www.roblox.com/users/{uid}/profile",
                       colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="User ID",  value=str(uid),                  inline=True)
    em.add_field(name="Joined",   value=user.get("created","")[:10], inline=True)
    em.add_field(name="Friends",  value=str(friends),              inline=True)
    em.add_field(name="Badges",   value=f"{len(badges)}+",         inline=True)
    em.add_field(name="Banned",   value="❌ Yes" if user.get("isBanned") else "✅ No", inline=True)
    if user.get("description"):
        em.add_field(name="Bio",  value=user["description"][:200], inline=False)
    em.set_footer(text="Roblox Users API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="group_info", description="Look up a Roblox group by ID")
@app_commands.describe(group_id="Roblox group ID")
async def cmd_group_info(interaction: discord.Interaction, group_id: str):
    bot._command_uses += 1
    await interaction.response.defer()
    try:
        gid = int(group_id)
    except ValueError:
        await interaction.followup.send("❌ Invalid group ID.")
        return
    group = await bot.get_group(gid)
    if not group:
        await interaction.followup.send("❌ Could not find that group.")
        return
    em = discord.Embed(title=f"👥 {group.get('name','?')}",
                       url=f"https://www.roblox.com/groups/{gid}",
                       colour=0xffd166, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Members", value=f"{group.get('memberCount',0):,}", inline=True)
    em.add_field(name="Owner",   value=group.get("owner",{}).get("username","?"), inline=True)
    em.add_field(name="Public",  value="✅ Yes" if group.get("publicEntryAllowed") else "🔒 No", inline=True)
    if group.get("description"):
        em.add_field(name="Description", value=group["description"][:300], inline=False)
    em.set_footer(text="Roblox Groups API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="badge_check", description="Check if a user has a specific badge")
@app_commands.describe(username="Roblox username", badge_id="Badge ID")
async def cmd_badge_check(interaction: discord.Interaction, username: str, badge_id: str):
    bot._command_uses += 1
    await interaction.response.defer()
    try:
        bid = int(badge_id)
    except ValueError:
        await interaction.followup.send("❌ Invalid badge ID.")
        return
    user = await bot.lookup_user(username)
    if not user:
        await interaction.followup.send("❌ User not found.")
        return
    badge = await bot.get_badge(bid)
    has_it = await bot.user_has_badge(user["id"], bid)
    em = discord.Embed(title="🏅 Badge Check", colour=0x06d6a0 if has_it else 0xe63946)
    em.add_field(name="Player", value=f"@{user.get('name','?')}", inline=True)
    em.add_field(name="Badge",  value=badge.get("name","?") if badge else str(bid), inline=True)
    em.add_field(name="Result", value="✅ Has it!" if has_it else "❌ Does not have it", inline=False)
    await interaction.followup.send(embed=em)

@bot.tree.command(name="robux_rates", description="Robux to USD exchange and DevEx rates")
async def cmd_robux_rates(interaction: discord.Interaction):
    bot._command_uses += 1
    em = discord.Embed(title="💰 Robux Exchange Rates", colour=0x06d6a0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Buy Rate",       value="$0.0035 per Robux (~286 R$ per $1)",        inline=False)
    em.add_field(name="DevEx Rate",     value="$0.0035 per R$ earned (min 30,000 R$)",     inline=False)
    em.add_field(name="Premium",        value="$4.99→450 R$\n$9.99→1,000 R$\n$19.99→2,200 R$", inline=False)
    em.add_field(name="Gift Cards",     value="$10→800 R$\n$25→2,000 R$\n$50→4,500 R$",   inline=False)
    em.set_footer(text="Rates as of 2026 — verify at roblox.com")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="trade_calculator", description="Calculate if a Roblox trade is worth it")
@app_commands.describe(your_rap="Your items total RAP", their_rap="Their items total RAP")
async def cmd_trade_calculator(interaction: discord.Interaction, your_rap: int, their_rap: int):
    bot._command_uses += 1
    diff = their_rap - your_rap
    pct = (diff / your_rap * 100) if your_rap else 0
    if diff > 0:   verdict, color = f"✅ Good trade! +R${diff:,} ({pct:+.1f}%)", 0x06d6a0
    elif diff < 0: verdict, color = f"❌ Bad trade! -R${abs(diff):,} ({pct:+.1f}%)", 0xe63946
    else:          verdict, color = "🟰 Even trade", 0xaaaaaa
    em = discord.Embed(title="⚖️ Trade Calculator", description=verdict, colour=color)
    em.add_field(name="Your RAP",   value=f"R${your_rap:,}",  inline=True)
    em.add_field(name="Their RAP",  value=f"R${their_rap:,}", inline=True)
    em.add_field(name="Difference", value=f"R${diff:+,}",     inline=True)
    em.set_footer(text="RAP = Recent Average Price")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="limited_tracker", description="Check resale data for a Roblox limited item")
@app_commands.describe(asset_id="Asset ID of the limited item")
async def cmd_limited_tracker(interaction: discord.Interaction, asset_id: str):
    bot._command_uses += 1
    await interaction.response.defer()
    try:
        aid = int(asset_id)
    except ValueError:
        await interaction.followup.send("❌ Invalid asset ID.")
        return
    resale = await bot.get_item_resale(aid)
    details = await bot.get_item_details(aid)
    if not resale:
        await interaction.followup.send("❌ Could not fetch item.")
        return
    name = details.get("name", f"Item {aid}") if details else f"Item {aid}"
    rap = resale.get("recentAveragePrice", 0)
    orig = resale.get("originalPrice", 0)
    vol = resale.get("volume", 0)
    em = discord.Embed(title=f"📈 Limited: {name}", url=f"https://www.roblox.com/catalog/{aid}",
                       colour=0xffd166, timestamp=datetime.now(timezone.utc))
    em.add_field(name="RAP",            value=f"R${rap:,}",  inline=True)
    em.add_field(name="Original Price", value=f"R${orig:,}", inline=True)
    em.add_field(name="Volume",         value=f"{vol:,}",    inline=True)
    if orig and rap:
        em.add_field(name="ROI", value=f"{((rap-orig)/orig*100):+.1f}%", inline=True)
    em.set_footer(text="Roblox Economy API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="ugc_trending", description="Trending UGC items on the Roblox catalog")
async def cmd_ugc_trending(interaction: discord.Interaction):
    bot._command_uses += 1
    await interaction.response.defer()
    items = await bot.get_catalog_items(8)
    em = discord.Embed(title="🛍️ Trending UGC Items", colour=0xf72585, timestamp=datetime.now(timezone.utc))
    if items:
        for item in items:
            price_str = f"R${item['price']:,}" if item["price"] else "Free"
            em.add_field(name=item["name"][:50],
                         value=f"💰 {price_str} | 👤 {item['creator']}\n[View](https://www.roblox.com/catalog/{item['id']})",
                         inline=True)
    else:
        em.description = "Could not fetch catalog right now."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="ugc_price", description="Check resale price of a UGC item")
@app_commands.describe(asset_id="Roblox asset ID")
async def cmd_ugc_price(interaction: discord.Interaction, asset_id: str):
    bot._command_uses += 1
    await interaction.response.defer()
    try:
        aid = int(asset_id)
    except ValueError:
        await interaction.followup.send("❌ Invalid asset ID.")
        return
    resale = await bot.get_item_resale(aid)
    details = await bot.get_item_details(aid)
    if not resale:
        await interaction.followup.send("❌ Could not fetch item.")
        return
    name = details.get("name", f"Item {aid}") if details else f"Item {aid}"
    em = discord.Embed(title=f"💰 {name}", url=f"https://www.roblox.com/catalog/{aid}",
                       colour=0xffd166, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Original Price",   value=f"R${resale.get('originalPrice',0):,}",     inline=True)
    em.add_field(name="Recent Avg Price", value=f"R${resale.get('recentAveragePrice',0):,}", inline=True)
    em.add_field(name="Total Volume",     value=f"{resale.get('volume',0):,} sales",         inline=True)
    em.set_footer(text="Roblox Economy API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="ugc_watch", description="Watch a UGC item for price change alerts")
@app_commands.describe(asset_id="Roblox asset ID to watch")
async def cmd_ugc_watch(interaction: discord.Interaction, asset_id: str):
    bot._command_uses += 1
    await interaction.response.defer()
    try:
        aid = int(asset_id)
    except ValueError:
        await interaction.followup.send("❌ Invalid asset ID.")
        return
    if len(bot._watched_items) >= 20:
        await interaction.followup.send("❌ Max 20 items. Use `/ugc_unwatch` to remove one.")
        return
    resale = await bot.get_item_resale(aid)
    details = await bot.get_item_details(aid)
    if not resale:
        await interaction.followup.send("❌ Could not find that item.")
        return
    name = details.get("name", f"Item {aid}") if details else f"Item {aid}"
    price = resale.get("recentAveragePrice") or resale.get("originalPrice") or 0
    bot._watched_items[aid] = {"name": name, "price": price}
    em = discord.Embed(title="👁️ Now Watching", description=f"**[{name}](https://www.roblox.com/catalog/{aid})**",
                       colour=0x06d6a0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Price",    value=f"R${price:,}",                       inline=True)
    em.add_field(name="Watching", value=f"{len(bot._watched_items)}/20 items", inline=True)
    em.set_footer(text="Checks every 30 min")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="ugc_unwatch", description="Stop watching a UGC item")
@app_commands.describe(asset_id="Asset ID to stop watching")
async def cmd_ugc_unwatch(interaction: discord.Interaction, asset_id: str):
    bot._command_uses += 1
    try:
        aid = int(asset_id)
    except ValueError:
        await interaction.response.send_message("❌ Invalid asset ID.")
        return
    if aid in bot._watched_items:
        name = bot._watched_items.pop(aid).get("name", str(aid))
        await interaction.response.send_message(f"✅ Stopped watching **{name}**.")
    else:
        await interaction.response.send_message("❌ That item is not being watched.")

@bot.tree.command(name="ugc_watchlist", description="Show all watched UGC items")
async def cmd_ugc_watchlist(interaction: discord.Interaction):
    bot._command_uses += 1
    em = discord.Embed(title="👁️ UGC Watchlist", colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    if bot._watched_items:
        for aid, info in bot._watched_items.items():
            em.add_field(name=info.get("name", str(aid)),
                         value=f"💰 R${info.get('price',0):,} | [View](https://www.roblox.com/catalog/{aid})", inline=True)
    else:
        em.description = "No items watched. Use `/ugc_watch <asset_id>`!"
    em.set_footer(text=f"{len(bot._watched_items)}/20 items")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="alert_threshold", description="Only alert on UGC price changes above X percent")
@app_commands.describe(percent="Minimum % change to trigger alert (0 = any change)")
async def cmd_alert_threshold(interaction: discord.Interaction, percent: float):
    bot._command_uses += 1
    bot._alert_threshold = max(0.0, percent)
    await interaction.response.send_message(f"✅ Alerts fire when price changes **{bot._alert_threshold:.1f}%+**.")

@bot.tree.command(name="mute_updates", description="Pause auto-alerts for X hours (Admin only)")
@app_commands.describe(hours="Hours to mute (0 to unmute)")
@admin_check()
async def cmd_mute_updates(interaction: discord.Interaction, hours: float):
    bot._command_uses += 1
    if hours <= 0:
        bot._muted_until = 0
        await interaction.response.send_message("🔔 Alerts **unmuted**.")
    else:
        bot._muted_until = time.time() + hours * 3600
        await interaction.response.send_message(f"🔕 Muted for **{hours}h**. Resumes <t:{int(bot._muted_until)}:R>.")

@bot.tree.command(name="filter_updates", description="Choose which update types to alert (Admin only)")
@app_commands.describe(client="Client updates", devforum="DevForum posts", incident="Status incidents")
@admin_check()
async def cmd_filter_updates(interaction: discord.Interaction,
                              client: bool = True, devforum: bool = True, incident: bool = True):
    bot._command_uses += 1
    bot._filters = {"client": client, "devforum": devforum, "incident": incident}
    em = discord.Embed(title="🔍 Filters Updated", colour=0x4cc9f0)
    em.add_field(name="🎮 Client",   value="✅" if client   else "❌", inline=True)
    em.add_field(name="📢 DevForum", value="✅" if devforum else "❌", inline=True)
    em.add_field(name="🚨 Incidents",value="✅" if incident else "❌", inline=True)
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="server_stats", description="Bot usage stats for this server")
async def cmd_server_stats(interaction: discord.Interaction):
    bot._command_uses += 1
    uptime = int(time.time() - bot._start_time)
    h, rem = divmod(uptime, 3600)
    m, _ = divmod(rem, 60)
    em = discord.Embed(title="📈 Server Stats", colour=0x9b5de5, timestamp=datetime.now(timezone.utc))
    em.add_field(name="💬 Commands Used",  value=str(bot._command_uses),   inline=True)
    em.add_field(name="⏱️ Uptime",         value=f"{h}h {m}m",             inline=True)
    em.add_field(name="🔔 Alert Channel",  value=f"<#{bot.update_channel_id}>" if bot.update_channel_id else "Not set", inline=True)
    em.add_field(name="👁️ Watched Items",  value=str(len(bot._watched_items)), inline=True)
    em.add_field(name="📋 Version Changes",value=str(len(bot._client_changelog)), inline=True)
    em.add_field(name="🔕 Muted",          value="Yes" if time.time() < bot._muted_until else "No", inline=True)
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="poll", description="Create a quick poll")
@app_commands.describe(question="Poll question", option_a="Option A", option_b="Option B")
async def cmd_poll(interaction: discord.Interaction, question: str, option_a: str, option_b: str):
    bot._command_uses += 1
    em = discord.Embed(title=f"📊 {question}", colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="🅰️", value=option_a, inline=True)
    em.add_field(name="🅱️", value=option_b, inline=True)
    em.set_footer(text=f"Poll by {interaction.user.display_name}")
    await interaction.response.send_message(embed=em)
    message = await interaction.original_response()
    await message.add_reaction("🅰️")
    await message.add_reaction("🅱️")

@bot.tree.command(name="uptime_history", description="Roblox incident history last 30 days")
async def cmd_uptime_history(interaction: discord.Interaction):
    bot._command_uses += 1
    await interaction.response.defer()
    incidents = await bot.get_incident_history(10)
    em = discord.Embed(title="📅 Roblox Incident History", colour=0xff6b35, timestamp=datetime.now(timezone.utc))
    if incidents:
        for inc in incidents:
            icon = {"none":"🟢","minor":"🟡","major":"🟠","critical":"🔴"}.get(inc["impact"],"⚪")
            em.add_field(name=f"{icon} {inc['name']}",
                         value=f"`{inc['status'].replace('_',' ').title()}` | {inc['created_at']}\n[View]({inc['url']})",
                         inline=False)
    else:
        em.description = "✅ No incidents in the last 30 days!"
    em.set_footer(text="status.roblox.com")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="deploy_history", description="Last 15 CDN deploy log entries")
async def cmd_deploy_history(interaction: discord.Interaction):
    bot._command_uses += 1
    await interaction.response.defer()
    entries = await bot.get_deploy_history(15)
    em = discord.Embed(title="📦 CDN Deploy History", colour=0x4cc9f0)
    if entries:
        em.description = f"```\n{chr(10).join(entries)[-3900:]}\n```"
    else:
        em.description = "Could not retrieve deploy history."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="set_update_channel", description="Set the alert channel (Admin only)")
@admin_check()
@app_commands.describe(channel="Channel to post alerts in")
async def cmd_set_update_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    bot.update_channel_id = channel.id
    await interaction.response.send_message(f"✅ Alerts will post in {channel.mention}.")

# Moderation
@bot.tree.command(name="warn", description="Warn a user")
@app_commands.describe(member="Member to warn", reason="Reason")
@mod_check()
async def cmd_warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    bot._command_uses += 1
    uid = str(member.id)
    entry = {"reason": reason, "by": str(interaction.user), "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    bot._warnings.setdefault(uid, []).append(entry)
    bot._save_data()
    count = len(bot._warnings[uid])
    em = discord.Embed(title="⚠️ User Warned", colour=0xffd166, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Member",      value=f"{member.mention}", inline=True)
    em.add_field(name="Total Warns", value=str(count),           inline=True)
    em.add_field(name="Reason",      value=reason,               inline=False)
    await interaction.response.send_message(embed=em)
    bot._add_audit("warn", interaction.user, f"Warned {member}: {reason}")
    await bot._log_action(em)

@bot.tree.command(name="warnings", description="Show warnings for a user")
@app_commands.describe(member="Member to check")
async def cmd_warnings(interaction: discord.Interaction, member: discord.Member):
    bot._command_uses += 1
    warns = bot._warnings.get(str(member.id), [])
    em = discord.Embed(title=f"⚠️ Warnings — {member.display_name}", colour=0xffd166)
    if warns:
        for i, w in enumerate(warns, 1):
            em.add_field(name=f"#{i} {w['time']}", value=f"**{w['reason']}** by {w['by']}", inline=False)
    else:
        em.description = "✅ No warnings."
    em.set_footer(text=f"Total: {len(warns)}")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="clearwarnings", description="Clear all warnings for a user")
@app_commands.describe(member="Member to clear")
@mod_check()
async def cmd_clearwarnings(interaction: discord.Interaction, member: discord.Member):
    bot._command_uses += 1
    count = len(bot._warnings.pop(str(member.id), []))
    bot._save_data()
    await interaction.response.send_message(f"✅ Cleared **{count}** warning(s) for {member.mention}.")
    bot._add_audit("clearwarnings", interaction.user, f"Cleared {count} warnings for {member}")

@bot.tree.command(name="kick", description="Kick a member")
@app_commands.describe(member="Member to kick", reason="Reason")
@mod_check()
async def cmd_kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
    bot._command_uses += 1
    try:
        await member.kick(reason=reason)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Missing permission to kick.", ephemeral=True)
        return
    em = discord.Embed(title="👢 Member Kicked", colour=0xff6b35, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Member", value=f"{member}", inline=True)
    em.add_field(name="Reason", value=reason,      inline=True)
    await interaction.response.send_message(embed=em)
    bot._add_audit("kick", interaction.user, f"Kicked {member}: {reason}")
    await bot._log_action(em)

@bot.tree.command(name="ban", description="Ban a member")
@app_commands.describe(member="Member to ban", reason="Reason")
@mod_check()
async def cmd_ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
    bot._command_uses += 1
    try:
        await member.ban(reason=reason, delete_message_days=0)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Missing permission to ban.", ephemeral=True)
        return
    em = discord.Embed(title="🔨 Member Banned", colour=0xe63946, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Member", value=f"{member}", inline=True)
    em.add_field(name="Reason", value=reason,      inline=True)
    await interaction.response.send_message(embed=em)
    bot._add_audit("ban", interaction.user, f"Banned {member}: {reason}")
    await bot._log_action(em)

@bot.tree.command(name="timeout", description="Timeout a member for X minutes")
@app_commands.describe(member="Member", minutes="Duration in minutes", reason="Reason")
@mod_check()
async def cmd_timeout(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "No reason"):
    bot._command_uses += 1
    import datetime as dt
    until = discord.utils.utcnow() + dt.timedelta(minutes=minutes)
    try:
        await member.timeout(until, reason=reason)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Missing permission.", ephemeral=True)
        return
    em = discord.Embed(title="⏱️ Member Timed Out", colour=0xffd166, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Member",   value=f"{member.mention}", inline=True)
    em.add_field(name="Duration", value=f"{minutes}m",       inline=True)
    em.add_field(name="Expires",  value=f"<t:{int(until.timestamp())}:R>", inline=True)
    em.add_field(name="Reason",   value=reason, inline=False)
    await interaction.response.send_message(embed=em)
    bot._add_audit("timeout", interaction.user, f"Timed out {member} for {minutes}m: {reason}")
    await bot._log_action(em)

@bot.tree.command(name="purge", description="Bulk-delete up to 100 messages")
@app_commands.describe(amount="Messages to delete (1-100)", channel="Channel (default: current)")
@mod_check()
async def cmd_purge(interaction: discord.Interaction, amount: int, channel: discord.TextChannel | None = None):
    bot._command_uses += 1
    ch = channel or interaction.channel
    if not 1 <= amount <= 100:
        await interaction.response.send_message("❌ Amount must be 1-100.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        deleted = await ch.purge(limit=amount)
    except discord.Forbidden:
        await interaction.followup.send("❌ Missing permission.", ephemeral=True)
        return
    await interaction.followup.send(f"🗑️ Deleted **{len(deleted)}** messages in {ch.mention}.", ephemeral=True)
    bot._add_audit("purge", interaction.user, f"Purged {len(deleted)} in #{ch.name}")

# Announcements
@bot.tree.command(name="announce", description="Post a formatted announcement to any channel")
@app_commands.describe(channel="Channel", title="Title", message="Message", color="Hex color (optional)")
@mod_check()
async def cmd_announce(interaction: discord.Interaction, channel: discord.TextChannel,
                        title: str, message: str, color: str = "4cc9f0"):
    bot._command_uses += 1
    try:
        clr = int(color.lstrip("#"), 16)
    except ValueError:
        clr = 0x4cc9f0
    em = discord.Embed(title=title, description=message, colour=clr, timestamp=datetime.now(timezone.utc))
    em.set_footer(text=f"By {interaction.user.display_name}")
    try:
        await channel.send(embed=em)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Can't send in that channel.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ Posted in {channel.mention}.", ephemeral=True)
    bot._add_audit("announce", interaction.user, f"#{channel.name}: {title}")

@bot.tree.command(name="dm_blast", description="DM all members with a message (Admin only)")
@app_commands.describe(message="Message to DM")
@admin_check()
async def cmd_dm_blast(interaction: discord.Interaction, message: str):
    bot._command_uses += 1
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    em = discord.Embed(title=f"📣 Message from {guild.name}", description=message, colour=0x4cc9f0)
    em.set_footer(text=f"By {interaction.user.display_name}")
    sent = failed = 0
    for member in guild.members:
        if member.bot:
            continue
        try:
            await member.send(embed=em)
            sent += 1
            await asyncio.sleep(0.5)
        except Exception:
            failed += 1
    await interaction.followup.send(f"✅ Sent to **{sent}**, failed **{failed}**.", ephemeral=True)
    bot._add_audit("dm_blast", interaction.user, f"{sent} members: {message[:80]}")

@bot.tree.command(name="schedule_announcement", description="Schedule a message to post later")
@app_commands.describe(channel="Channel", title="Title", message="Message", minutes_from_now="Minutes until sent")
@mod_check()
async def cmd_schedule(interaction: discord.Interaction, channel: discord.TextChannel,
                        title: str, message: str, minutes_from_now: int):
    bot._command_uses += 1
    if minutes_from_now < 1:
        await interaction.response.send_message("❌ Must be at least 1 minute.", ephemeral=True)
        return
    send_at = time.time() + minutes_from_now * 60
    bot._scheduled.append({"channel_id": channel.id, "title": title, "message": message,
                            "send_at": send_at, "author": str(interaction.user)})
    bot._save_data()
    ts = int(send_at)
    em = discord.Embed(title="🕐 Scheduled", colour=0x9b5de5)
    em.add_field(name="Channel", value=channel.mention, inline=True)
    em.add_field(name="Sends",   value=f"<t:{ts}:R>",   inline=True)
    em.add_field(name="Title",   value=title,            inline=False)
    await interaction.response.send_message(embed=em)

# Logging
@bot.tree.command(name="set_log_channel", description="Set channel for bot action logs (Admin only)")
@app_commands.describe(channel="Log channel")
@admin_check()
async def cmd_set_log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    bot._command_uses += 1
    bot._log_channel_id = channel.id
    bot._save_data()
    await interaction.response.send_message(f"✅ Logging to {channel.mention}.")
    bot._add_audit("set_log_channel", interaction.user, f"#{channel.name}")

@bot.tree.command(name="audit", description="Show last 15 bot actions")
@mod_check()
async def cmd_audit(interaction: discord.Interaction):
    bot._command_uses += 1
    entries = bot._audit_log[-15:]
    em = discord.Embed(title="📋 Audit Log", colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    if entries:
        for e in reversed(entries):
            em.add_field(name=f"`{e['action']}` • {e['time']}",
                         value=f"By: **{e['by']}**" + (f"\n{e['detail']}" if e.get("detail") else ""),
                         inline=False)
    else:
        em.description = "No entries yet."
    await interaction.response.send_message(embed=em)

# Roles
@bot.tree.command(name="set_ping_role", description="Ping a role instead of @everyone (Admin only)")
@app_commands.describe(role="Role to ping (blank = @everyone)")
@admin_check()
async def cmd_set_ping_role(interaction: discord.Interaction, role: discord.Role | None = None):
    bot._command_uses += 1
    bot._ping_role_id = role.id if role else None
    bot._save_data()
    await interaction.response.send_message(f"✅ Pinging {role.mention if role else '@everyone'} for updates.")
    bot._add_audit("set_ping_role", interaction.user, str(role))

@bot.tree.command(name="autorole", description="Auto-assign a role to new members (Admin only)")
@app_commands.describe(role="Role to assign (blank = disable)")
@admin_check()
async def cmd_autorole(interaction: discord.Interaction, role: discord.Role | None = None):
    bot._command_uses += 1
    bot._autorole_id = role.id if role else None
    bot._save_data()
    await interaction.response.send_message(f"✅ Auto-role {'set to ' + role.mention if role else 'disabled'}.")
    bot._add_audit("autorole", interaction.user, str(role))

@bot.tree.command(name="role_info", description="Show info about a role")
@app_commands.describe(role="The role")
async def cmd_role_info(interaction: discord.Interaction, role: discord.Role):
    bot._command_uses += 1
    em = discord.Embed(title=f"🎭 {role.name}", colour=role.colour, timestamp=datetime.now(timezone.utc))
    em.add_field(name="ID",          value=str(role.id),                            inline=True)
    em.add_field(name="Members",     value=str(len(role.members)),                  inline=True)
    em.add_field(name="Position",    value=str(role.position),                      inline=True)
    em.add_field(name="Mentionable", value="✅" if role.mentionable else "❌",       inline=True)
    em.add_field(name="Hoisted",     value="✅" if role.hoist else "❌",             inline=True)
    em.add_field(name="Color",       value=str(role.colour),                        inline=True)
    em.add_field(name="Created",     value=role.created_at.strftime("%Y-%m-%d"),    inline=True)
    await interaction.response.send_message(embed=em)

# Configuration
@bot.tree.command(name="set_prefix", description="Change the bot prefix (Admin only)")
@app_commands.describe(prefix="New prefix")
@admin_check()
async def cmd_set_prefix(interaction: discord.Interaction, prefix: str):
    bot._command_uses += 1
    if len(prefix) > 5:
        await interaction.response.send_message("❌ Max 5 characters.", ephemeral=True)
        return
    bot._prefix = prefix
    bot._save_data()
    await interaction.response.send_message(f"✅ Prefix set to `{prefix}`.")
    bot._add_audit("set_prefix", interaction.user, prefix)

@bot.tree.command(name="bot_info", description="Show full bot configuration")
async def cmd_bot_info(interaction: discord.Interaction):
    bot._command_uses += 1
    uptime = int(time.time() - bot._start_time)
    h, rem = divmod(uptime, 3600)
    m, s = divmod(rem, 60)
    guild = interaction.guild
    def fmt_role(rid):
        if not rid or not guild: return "Not set"
        r = guild.get_role(rid)
        return r.mention if r else "Unknown"
    em = discord.Embed(title="⚙️ Bot Configuration", colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="⏱️ Uptime",        value=f"{h}h {m}m {s}s",                               inline=True)
    em.add_field(name="💬 Prefix",        value=f"`{bot._prefix}`",                              inline=True)
    em.add_field(name="📣 Alert Channel", value=f"<#{bot.update_channel_id}>" if bot.update_channel_id else "Not set", inline=True)
    em.add_field(name="📋 Log Channel",   value=f"<#{bot._log_channel_id}>" if bot._log_channel_id else "Not set", inline=True)
    em.add_field(name="🔔 Ping Role",     value=fmt_role(bot._ping_role_id),                     inline=True)
    em.add_field(name="🎭 Auto-role",     value=fmt_role(bot._autorole_id),                      inline=True)
    em.add_field(name="🤬 Auto-mod",      value="✅ On" if bot._automod_enabled else "❌ Off",    inline=True)
    em.add_field(name="🛡️ Anti-raid",    value="🔴 ON" if bot._antiraid_enabled else "🟢 Off",  inline=True)
    em.add_field(name="👁️ Watched",      value=str(len(bot._watched_items)),                    inline=True)
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="reset_settings", description="Reset all settings to defaults (Admin only)")
@admin_check()
async def cmd_reset_settings(interaction: discord.Interaction):
    bot._command_uses += 1
    bot._warnings = {}; bot._log_channel_id = None; bot._audit_log = []
    bot._ping_role_id = None; bot._autorole_id = None; bot._scheduled = []
    bot._prefix = "!"; bot._filters = {"client": True, "devforum": True, "incident": True}
    bot._alert_threshold = 0.0; bot._watched_items = {}; bot._muted_until = 0
    bot._save_data()
    await interaction.response.send_message("🔄 All settings reset to defaults.")
    bot._add_audit("reset_settings", interaction.user)

@bot.tree.command(name="backup_settings", description="Export settings as JSON (Admin only)")
@admin_check()
async def cmd_backup_settings(interaction: discord.Interaction):
    bot._command_uses += 1
    await interaction.response.defer(ephemeral=True)
    import io
    data = {"exported_at": datetime.now(timezone.utc).isoformat(), "prefix": bot._prefix,
            "filters": bot._filters, "alert_threshold": bot._alert_threshold,
            "watched_items": {str(k): v for k, v in bot._watched_items.items()}}
    buf = io.BytesIO(json.dumps(data, indent=2).encode())
    buf.seek(0)
    fname = f"backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    await interaction.followup.send(file=discord.File(buf, filename=fname), ephemeral=True)
    bot._add_audit("backup_settings", interaction.user)

# Anti-raid
@bot.tree.command(name="antiraid_on", description="Enable anti-raid lockdown (Admin only)")
@app_commands.describe(action="kick or ban")
@admin_check()
async def cmd_antiraid_on(interaction: discord.Interaction, action: str | None = None):
    bot._command_uses += 1
    if action and action.lower() in ("kick","ban"):
        bot._antiraid_action = action.lower()
    bot._antiraid_enabled = True
    bot._save_data()
    em = discord.Embed(title="🚨 Anti-Raid ENABLED", colour=0xe63946, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Action", value=bot._antiraid_action.upper(), inline=True)
    await interaction.response.send_message(embed=em)
    bot._add_audit("antiraid_on", interaction.user)

@bot.tree.command(name="antiraid_off", description="Disable anti-raid lockdown (Admin only)")
@admin_check()
async def cmd_antiraid_off(interaction: discord.Interaction):
    bot._command_uses += 1
    bot._antiraid_enabled = False
    bot._join_times.clear()
    bot._save_data()
    await interaction.response.send_message("✅ Anti-raid lockdown **disabled**.")
    bot._add_audit("antiraid_off", interaction.user)

@bot.tree.command(name="antiraid_config", description="Configure anti-raid detection (Admin only)")
@app_commands.describe(threshold="Joins to trigger (default 10)", window="Seconds window (default 10)",
                        action="kick or ban", auto="Auto-detect enabled")
@admin_check()
async def cmd_antiraid_config(interaction: discord.Interaction, threshold: int | None = None,
                               window: int | None = None, action: str | None = None, auto: bool | None = None):
    bot._command_uses += 1
    if threshold and threshold >= 2: bot._antiraid_threshold = threshold
    if window and window >= 3:       bot._antiraid_window = window
    if action and action.lower() in ("kick","ban"): bot._antiraid_action = action.lower()
    if auto is not None:             bot._antiraid_auto = auto
    bot._save_data()
    em = discord.Embed(title="⚙️ Anti-Raid Config", colour=0x9b5de5)
    em.add_field(name="Auto",      value="✅" if bot._antiraid_auto else "❌",            inline=True)
    em.add_field(name="Threshold", value=f"{bot._antiraid_threshold} joins/{bot._antiraid_window}s", inline=True)
    em.add_field(name="Action",    value=bot._antiraid_action.upper(),                    inline=True)
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="antiraid_status", description="Show anti-raid status")
async def cmd_antiraid_status(interaction: discord.Interaction):
    bot._command_uses += 1
    now = time.time()
    recent = sum(1 for t in bot._join_times if t >= now - bot._antiraid_window)
    em = discord.Embed(title="🛡️ Anti-Raid Status",
                       colour=0xe63946 if bot._antiraid_enabled else 0x06d6a0,
                       timestamp=datetime.now(timezone.utc))
    em.add_field(name="Lockdown",     value="🔴 ACTIVE" if bot._antiraid_enabled else "🟢 Off", inline=True)
    em.add_field(name="Auto-detect",  value="✅" if bot._antiraid_auto else "❌",               inline=True)
    em.add_field(name="Threshold",    value=f"{bot._antiraid_threshold}/{bot._antiraid_window}s", inline=True)
    em.add_field(name="Action",       value=bot._antiraid_action.upper(),                        inline=True)
    em.add_field(name="Recent Joins", value=str(recent),                                         inline=True)
    await interaction.response.send_message(embed=em)

# Role permissions
@bot.tree.command(name="set_mod_role", description="Set role for mod commands (Admin only)")
@app_commands.describe(role="Mod role (blank = clear)")
@admin_check()
async def cmd_set_mod_role(interaction: discord.Interaction, role: discord.Role | None = None):
    bot._command_uses += 1
    bot._mod_role_id = role.id if role else None
    bot._save_data()
    await interaction.response.send_message(f"✅ Mod role {'set to ' + role.mention if role else 'cleared'}.")
    bot._add_audit("set_mod_role", interaction.user, str(role))

@bot.tree.command(name="set_admin_role", description="Set role for admin commands (Admin only)")
@app_commands.describe(role="Admin role (blank = clear)")
@admin_check()
async def cmd_set_admin_role(interaction: discord.Interaction, role: discord.Role | None = None):
    bot._command_uses += 1
    bot._admin_role_id = role.id if role else None
    bot._save_data()
    await interaction.response.send_message(f"✅ Admin role {'set to ' + role.mention if role else 'cleared'}.")
    bot._add_audit("set_admin_role", interaction.user, str(role))

# Auto-mod
@bot.tree.command(name="automod_enable", description="Enable profanity filter (Admin only)")
@app_commands.describe(penalty="timeout_week or kick (default: timeout_week)")
@admin_check()
async def cmd_automod_enable(interaction: discord.Interaction, penalty: str | None = None):
    bot._command_uses += 1
    if penalty and penalty.lower() in ("kick","timeout_week"):
        bot._automod_penalty = penalty.lower()
    bot._automod_enabled = True
    bot._save_data()
    await interaction.response.send_message(f"✅ Auto-mod enabled. Strike 3+ penalty: **{bot._automod_penalty}**.")
    bot._add_audit("automod_enable", interaction.user)

@bot.tree.command(name="automod_disable", description="Disable profanity filter (Admin only)")
@admin_check()
async def cmd_automod_disable(interaction: discord.Interaction):
    bot._command_uses += 1
    bot._automod_enabled = False
    bot._save_data()
    await interaction.response.send_message("✅ Auto-mod disabled.")
    bot._add_audit("automod_disable", interaction.user)

@bot.tree.command(name="automod_addword", description="Add a word to the filter (Admin only)")
@app_commands.describe(word="Word to block")
@admin_check()
async def cmd_automod_addword(interaction: discord.Interaction, word: str):
    bot._command_uses += 1
    w = word.lower().strip()
    if w in bot._automod_words:
        await interaction.response.send_message(f"⚠️ `{w}` already in filter.", ephemeral=True)
        return
    bot._automod_words.append(w)
    bot._save_data()
    await interaction.response.send_message(f"✅ Added `{w}`. ({len(bot._automod_words)} total)")
    bot._add_audit("automod_addword", interaction.user, w)

@bot.tree.command(name="automod_removeword", description="Remove a word from the filter (Admin only)")
@app_commands.describe(word="Word to remove")
@admin_check()
async def cmd_automod_removeword(interaction: discord.Interaction, word: str):
    bot._command_uses += 1
    w = word.lower().strip()
    if w not in bot._automod_words:
        await interaction.response.send_message(f"⚠️ `{w}` not in filter.", ephemeral=True)
        return
    bot._automod_words.remove(w)
    bot._save_data()
    await interaction.response.send_message(f"✅ Removed `{w}`. ({len(bot._automod_words)} total)")
    bot._add_audit("automod_removeword", interaction.user, w)

@bot.tree.command(name="automod_status", description="Show auto-mod config")
@mod_check()
async def cmd_automod_status(interaction: discord.Interaction):
    bot._command_uses += 1
    em = discord.Embed(title="🤬 Auto-Mod Status",
                       colour=0x06d6a0 if bot._automod_enabled else 0xe63946)
    em.add_field(name="Status",  value="✅ On" if bot._automod_enabled else "❌ Off", inline=True)
    em.add_field(name="Penalty", value=bot._automod_penalty,                          inline=True)
    em.add_field(name="Words",   value=str(len(bot._automod_words)),                  inline=True)
    words = ", ".join(f"`{w}`" for w in sorted(bot._automod_words))
    em.add_field(name="Blocked Words", value=words[:900] or "None", inline=False)
    await interaction.response.send_message(embed=em, ephemeral=True)

@bot.tree.command(name="automod_logs", description="Recent auto-mod violations (Mod only)")
@app_commands.describe(member="Filter by member (optional)")
@mod_check()
async def cmd_automod_logs(interaction: discord.Interaction, member: discord.Member | None = None):
    bot._command_uses += 1
    entries = list(reversed(bot._automod_log))
    if member:
        entries = [e for e in entries if e["uid"] == str(member.id)]
    em = discord.Embed(title="🤬 Auto-Mod Logs", colour=0xe63946, timestamp=datetime.now(timezone.utc))
    if entries[:10]:
        lines = []
        for e in entries[:10]:
            lines.append(f"**{e['user']}** — `{e['word']}` | Strike {e['strikes']} | {e['action']}")
        em.description = "\n".join(lines)
    else:
        em.description = "No violations recorded."
    await interaction.response.send_message(embed=em, ephemeral=True)

@bot.tree.command(name="automod_clearstrikes", description="Clear strikes for a user (Admin only)")
@app_commands.describe(member="Member to clear")
@admin_check()
async def cmd_automod_clearstrikes(interaction: discord.Interaction, member: discord.Member):
    bot._command_uses += 1
    old = bot._automod_strikes.pop(str(member.id), 0)
    await interaction.response.send_message(f"✅ Cleared **{old}** strike(s) for {member.mention}.", ephemeral=True)

@bot.tree.command(name="strike_leaderboard", description="Top users by auto-mod strikes (Mod only)")
@mod_check()
async def cmd_strike_leaderboard(interaction: discord.Interaction):
    bot._command_uses += 1
    totals: dict[str, int] = {}
    names: dict[str, str] = {}
    for e in bot._automod_log:
        uid = e["uid"]
        totals[uid] = totals.get(uid, 0) + 1
        names[uid] = e["user"]
    if not totals:
        await interaction.response.send_message("📊 No strikes recorded yet!", ephemeral=True)
        return
    ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:10]
    medals = ["🥇","🥈","🥉"]
    lines = [f"{medals[i] if i<3 else f'**{i+1}.**'} {names.get(uid,'?')} — **{c}** violation(s)"
             for i, (uid, c) in enumerate(ranked)]
    em = discord.Embed(title="📊 Strike Leaderboard", description="\n".join(lines), colour=0xe63946)
    await interaction.response.send_message(embed=em, ephemeral=True)

# Reports
@bot.tree.command(name="user_report", description="Anonymously report a member")
@app_commands.describe(reported="Member to report", reason="What happened", attachment="Evidence screenshot")
async def cmd_user_report(interaction: discord.Interaction, reported: discord.Member,
                           reason: str, attachment: discord.Attachment):
    bot._command_uses += 1
    if reported.id == interaction.user.id:
        await interaction.response.send_message("❌ Can't report yourself.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    ts = datetime.now(timezone.utc)
    report_id = f"RPT-{int(ts.timestamp())}"
    bot._reports.append({
        "id": report_id, "ts": ts.isoformat(),
        "reporter_id": str(interaction.user.id),
        "reported": f"{reported} ({reported.id})",
        "reported_id": str(reported.id),
        "reason": reason,
        "attachments": [attachment.url],
        "guild": str(interaction.guild.id),
        "status": "open",
    })
    bot._reports = bot._reports[-200:]
    bot._save_data()
    if bot._log_channel_id:
        ch = bot.get_channel(bot._log_channel_id)
        if ch:
            em = discord.Embed(title=f"🚨 Report {report_id}", colour=0xff6b6b, timestamp=ts)
            em.add_field(name="Reported", value=f"{reported.mention} ({reported})", inline=False)
            em.add_field(name="Reporter", value=str(interaction.user), inline=True)
            em.add_field(name="Reason",   value=reason, inline=False)
            em.add_field(name="Evidence", value=attachment.url, inline=False)
            try:
                await ch.send(embed=em)
            except Exception:
                pass
    await interaction.followup.send(f"✅ Report `{report_id}` submitted anonymously.", ephemeral=True)
    bot._add_audit("user_report", interaction.user, f"Reported {reported} — {report_id}")

@bot.tree.command(name="view_reports", description="Browse member reports (Mod only)")
@app_commands.describe(status="all/open/resolved/dismissed")
@mod_check()
async def cmd_view_reports(interaction: discord.Interaction, status: str = "open"):
    bot._command_uses += 1
    entries = [e for e in reversed(bot._reports) if status == "all" or e.get("status","open") == status]
    em = discord.Embed(title=f"📋 Reports ({status})", colour=0xff6b6b, timestamp=datetime.now(timezone.utc))
    if entries[:5]:
        for e in entries[:5]:
            icon = {"open":"🔴","resolved":"✅","dismissed":"🔕"}.get(e.get("status","open"),"🔴")
            em.add_field(name=f"{icon} `{e['id']}` — {e['reported']}",
                         value=f"**{e['reason'][:100]}**\n[Evidence]({e['attachments'][0] if e.get('attachments') else '#'})",
                         inline=False)
    else:
        em.description = "No reports found."
    em.set_footer(text=f"{len(entries)} total")
    await interaction.response.send_message(embed=em, ephemeral=True)

@bot.tree.command(name="resolve_report", description="Mark a report as resolved (Mod only)")
@app_commands.describe(report_id="Report ID e.g. RPT-123456", note="Closing note")
@mod_check()
async def cmd_resolve_report(interaction: discord.Interaction, report_id: str, note: str = ""):
    bot._command_uses += 1
    rid = report_id.upper().strip()
    for e in bot._reports:
        if e["id"] == rid:
            e["status"] = "resolved"
            e["closed_by"] = str(interaction.user)
            e["close_note"] = note
            bot._save_data()
            await interaction.response.send_message(f"✅ Report `{rid}` resolved.", ephemeral=True)
            bot._add_audit("resolve_report", interaction.user, rid)
            return
    await interaction.response.send_message(f"❌ Report `{rid}` not found.", ephemeral=True)

@bot.tree.command(name="dismiss_report", description="Dismiss a report (Mod only)")
@app_commands.describe(report_id="Report ID", reason="Reason")
@mod_check()
async def cmd_dismiss_report(interaction: discord.Interaction, report_id: str, reason: str = ""):
    bot._command_uses += 1
    rid = report_id.upper().strip()
    for e in bot._reports:
        if e["id"] == rid:
            e["status"] = "dismissed"
            e["closed_by"] = str(interaction.user)
            e["close_note"] = reason
            bot._save_data()
            await interaction.response.send_message(f"🔕 Report `{rid}` dismissed.", ephemeral=True)
            bot._add_audit("dismiss_report", interaction.user, rid)
            return
    await interaction.response.send_message(f"❌ Report `{rid}` not found.", ephemeral=True)

# Sync
@bot.tree.command(name="sync", description="Force re-sync commands to this server (Admin only)")
@admin_check()
async def cmd_sync(interaction: discord.Interaction):
    bot._command_uses += 1
    await interaction.response.defer(ephemeral=True)
    try:
        bot.tree.copy_global_to(guild=interaction.guild)
        synced = await bot.tree.sync(guild=interaction.guild)
        await interaction.followup.send(f"✅ Synced **{len(synced)}** commands.", ephemeral=True)
        log.info("Manual sync: %d commands to %s", len(synced), interaction.guild.id)
    except Exception as e:
        await interaction.followup.send(f"❌ Sync failed: {e}", ephemeral=True)

# Help
@bot.tree.command(name="help_roblox", description="Show all commands")
async def cmd_help(interaction: discord.Interaction):
    bot._command_uses += 1
    em = discord.Embed(title="🤖 Roblox Update Tracker — All Commands", colour=0x4cc9f0)
    categories = {
        "📡 Updates": ["/roblox_version","/latest_updates","/release_notes","/upcoming_features","/changelog","/compare_versions","/deploy_history"],
        "🔒 Security": ["/security_updates","/status","/uptime_history"],
        "🎮 Games": ["/game_status","/random_game","/player_lookup","/group_info","/badge_check"],
        "💰 Economy": ["/robux_rates","/trade_calculator","/limited_tracker","/ugc_trending","/ugc_price","/ugc_watch","/ugc_unwatch","/ugc_watchlist","/alert_threshold"],
        "⚙️ Management": ["/stats","/server_stats","/poll","/mute_updates","/filter_updates","/set_update_channel","/bot_info","/reset_settings","/backup_settings","/set_prefix"],
        "🔨 Moderation": ["/warn","/warnings","/clearwarnings","/kick","/ban","/timeout","/purge"],
        "📢 Announcements": ["/announce","/dm_blast","/schedule_announcement"],
        "📋 Logging": ["/set_log_channel","/audit"],
        "🎭 Roles": ["/set_ping_role","/autorole","/role_info","/set_mod_role","/set_admin_role"],
        "🛡️ Anti-Raid": ["/antiraid_on","/antiraid_off","/antiraid_config","/antiraid_status"],
        "🤬 Auto-Mod": ["/automod_enable","/automod_disable","/automod_addword","/automod_removeword","/automod_status","/automod_logs","/automod_clearstrikes","/strike_leaderboard"],
        "🚨 Reports": ["/user_report","/view_reports","/resolve_report","/dismiss_report"],
        "🔄 Sync": ["/sync"],
    }
    for cat, cmds in categories.items():
        em.add_field(name=cat, value=" ".join(f"`{c}`" for c in cmds), inline=False)
    em.set_footer(text=f"Polls every {CHECK_INTERVAL_MINUTES} min")
    await interaction.response.send_message(embed=em)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        bot.run(BOT_TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        print("\n" + "="*60)
        print("❌ PRIVILEGED INTENTS REQUIRED")
        print("Enable in Discord Dev Portal → Bot → Privileged Gateway Intents:")
        print("  • Message Content Intent")
        print("  • Server Members Intent")
        print("="*60 + "\n")
BOTEOF
Output

exit code 0
