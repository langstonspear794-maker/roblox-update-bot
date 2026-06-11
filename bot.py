"""
Roblox Update Tracker Bot — Ultimate Edition
(Complete & Working)
"""

import asyncio
import collections
import json
import logging
import os
import random
import re
import time
import typing
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
GROQ_API_KEY           = os.getenv("GROQ_API_KEY", "")

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
# Simple keyword responses (fallback)
# ---------------------------------------------------------------------------
CHAT_RESPONSES = {
    "hello": ["Hello! 👋 How can I help you today?", "Hi there! What's up?", "Hey! Need something?"],
    "hi": ["Hey! How can I assist you?", "Hi! What do you need?", "Hello! I'm here to help."],
    "how are you": ["I'm just a bunch of code, but I'm doing great! 😄", "Feeling electric! ⚡", "All systems operational!"],
    "help": ["Sure! I can track Roblox updates, moderate the server, and more. Try `!help` to see all commands.", "Need assistance? I can help with moderation, Roblox info, and server management. Just ask!", "I'm here to help! What do you need?"],
    "roblox": ["I love Roblox! I can check game status, player info, and more. Use `/game_status` or `/player_lookup`.", "Roblox is my specialty! Try `/ugc_trending` or `/latest_updates`.", "I track Roblox updates live! Want to see the latest version? Use `/roblox_version`."],
    "thanks": ["You're welcome! 😊", "No problem! Happy to help.", "Anytime!"],
    "bye": ["Goodbye! 👋", "See you later!", "Bye! Come back soon."],
    "joke": ["Why do Roblox developers never sleep? They just `wait()` for the next update! 😆", "Why did the Lua script go to therapy? Too many nil references!", "What's a developer's favorite drink? Java! ... oh wait, wrong platform."],
    "ticket": ["To create a ticket, just type `!ticket` followed by your reason (e.g., `!ticket I need help with my account`).", "Need support? Use `!ticket <reason>` and a staff member will assist you!", "I can open a ticket for you! Just say `!ticket` with your issue."],
}

FALLBACK_RESPONSES = [
    "I'm not sure I understand. Try `!help` to see what I can do.",
    "That's interesting! But I'm a Roblox tracker bot, maybe ask something Roblox related?",
    "I'm just a bot, but I'm here to help with Roblox stuff and server management.",
    "Sorry, I didn't catch that. Can you rephrase?",
    "🤖 Beep boop! That's not in my database, but I'm always learning (sort of)."
]

# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------
class RobloxBot(discord.Client):
    def __init__(self) -> None:
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
        self._filters: dict[str, bool] = {"client": True, "devforum": True, "incident": True}
        self._alert_threshold: float = 0.0
        self._last_client_version: str | None = None
        self._last_incident_id: str | None = None
        self._last_devforum_id: int | None = None
        self._last_check_time: str = "Never"
        self._client_changelog: list[dict] = []
        self._watched_items: dict[int, dict] = {}
        self._warnings: dict[str, list[dict]] = {}
        self._log_channel_id: int | None = None
        self._audit_log: list[dict] = []
        self._ping_role_id: int | None = None
        self._autorole_id: int | None = None
        self._scheduled: list[dict] = []
        self._prefix: str = "!"
        self._antiraid_enabled: bool = False
        self._antiraid_auto: bool = True
        self._antiraid_threshold: int = 10
        self._antiraid_window: int = 10
        self._antiraid_action: str = "kick"
        self._join_times: collections.deque[float] = collections.deque()
        self._mod_role_id: int | None = None
        self._admin_role_id: int | None = None
        self._automod_enabled: bool = True
        self._automod_words: list[str] = list(DEFAULT_BAD_WORDS)
        self._automod_strikes: dict[str, int] = {}
        self._automod_penalty: str = "timeout_week"
        self._automod_log: list[dict] = []
        self._reports: list[dict] = []
        self._banned_users: dict[str, dict] = {}

        # Server management extras
        self._welcome_channel_id: int | None = None
        self._welcome_message: str = "Welcome {mention} to **{server}**! Enjoy your stay."
        self._verified_role_id: int | None = None
        self._suggestion_channel_id: int | None = None
        self._reaction_roles: dict[str, dict[str, int]] = {}
        self._giveaways: dict[int, dict] = {}
        self._temp_vcs: dict[int, dict] = {}
        self._ticket_counter: int = 0

        self._load_data()
        self._cleanup_banned_users()

    # ---------- Persistence ----------
    DATA_FILE = "bot_data.json"

    def _load_data(self) -> None:
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
            self._automod_enabled    = d.get("automod_enabled", True)
            self._automod_words      = d.get("automod_words", list(DEFAULT_BAD_WORDS))
            self._automod_penalty    = d.get("automod_penalty", "timeout_week")
            self._automod_log        = d.get("automod_log", [])
            self._reports            = d.get("reports", [])
            raw_banned = d.get("banned_users", {})
            self._banned_users = {}
            for uid, data in raw_banned.items():
                data["timestamp"] = float(data.get("timestamp", 0))
                self._banned_users[uid] = data
            self._welcome_channel_id    = d.get("welcome_channel_id")
            self._welcome_message       = d.get("welcome_message", self._welcome_message)
            self._verified_role_id      = d.get("verified_role_id")
            self._suggestion_channel_id = d.get("suggestion_channel_id")
            self._reaction_roles        = d.get("reaction_roles", {})
            raw_giveaways = d.get("giveaways", {})
            self._giveaways = {}
            for mid, gdata in raw_giveaways.items():
                gdata["end_time"] = float(gdata.get("end_time", 0))
                self._giveaways[int(mid)] = gdata
            raw_tempvcs = d.get("temp_vcs", {})
            self._temp_vcs = {}
            for cid, vcdata in raw_tempvcs.items():
                vcdata["expires"] = float(vcdata.get("expires", 0))
                self._temp_vcs[int(cid)] = vcdata
            self._ticket_counter = d.get("ticket_counter", 0)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_data(self) -> None:
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
                    "watched_items":   {str(k): v for k, v in self._watched_items.items()},
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
                    "banned_users":       self._banned_users,
                    "welcome_channel_id": self._welcome_channel_id,
                    "welcome_message":    self._welcome_message,
                    "verified_role_id":   self._verified_role_id,
                    "suggestion_channel_id": self._suggestion_channel_id,
                    "reaction_roles":     self._reaction_roles,
                    "giveaways":          self._giveaways,
                    "temp_vcs":           self._temp_vcs,
                    "ticket_counter":     self._ticket_counter,
                }, f, indent=2)
        except Exception as e:
            log.warning("Failed to save data: %s", e)

    def _cleanup_banned_users(self) -> None:
        now = time.time()
        expired = [uid for uid, data in self._banned_users.items()
                   if now - data.get("timestamp", 0) > 7 * 24 * 3600]
        for uid in expired:
            del self._banned_users[uid]
        if expired:
            self._save_data()

    def _add_audit(self, action: str, user: discord.User | discord.Member, detail: str = "") -> None:
        self._audit_log.append({
            "time":   datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "action": action,
            "by":     f"{user} ({user.id})",
            "detail": detail,
        })
        self._audit_log = self._audit_log[-200:]
        self._save_data()

    async def _log_action(self, embed: discord.Embed) -> None:
        if self._log_channel_id:
            ch = self.get_channel(self._log_channel_id)
            if isinstance(ch, discord.abc.Messageable):
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass

    # ---------- HTTP helpers ----------
    async def _session_(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers={"User-Agent": "RobloxUpdateBot/3.0"})
        return self._session

    async def _json(self, url: str) -> typing.Any:
        s = await self._session_()
        try:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
        except Exception as e:
            log.warning("fetch_json %s: %s", url, e)
        return None

    async def _text(self, url: str) -> str | None:
        s = await self._session_()
        try:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return await r.text()
        except Exception as e:
            log.warning("fetch_text %s: %s", url, e)
        return None

    # ---------- Data fetchers ----------
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

    # ---------- Loops ----------
    @tasks.loop(minutes=5)
    async def rotate_presence(self) -> None:
        cv = self._last_client_version or "unknown"
        label, atype = PRESENCE_ACTIVITIES[self._presence_index % len(PRESENCE_ACTIVITIES)]
        await self.change_presence(activity=discord.Activity(type=atype, name=label.replace("{client}", cv)))
        self._presence_index += 1

    @rotate_presence.before_loop
    async def before_presence(self): await self.wait_until_ready()

    @tasks.loop(minutes=30)
    async def poll_ugc_prices(self) -> None:
        if not self._watched_items:
            return
        channel = self.get_channel(self.update_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
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
            em.add_field(name="Change", value=f"{'+' if change>0 else ''}{change:,} ({pct:+.1f}%)", inline=True)
            em.set_footer(text="Roblox Economy Tracker")
            ping_content = ""
            if PING_EVERYONE:
                guild = channel.guild if isinstance(channel, discord.TextChannel) else None
                if guild and self._ping_role_id:
                    role = guild.get_role(self._ping_role_id)
                    ping_content = f"{role.mention}\n" if role else "@everyone\n"
                else:
                    ping_content = "@everyone\n"
            await channel.send(content=ping_content, embed=em)
            self._watched_items[asset_id]["price"] = new_price

    @poll_ugc_prices.before_loop
    async def before_ugc(self): await self.wait_until_ready()

    @tasks.loop(seconds=30)
    async def check_scheduled(self) -> None:
        now = time.time()
        remaining = []
        for item in self._scheduled:
            if now >= item["send_at"]:
                ch = self.get_channel(item["channel_id"])
                if isinstance(ch, discord.abc.Messageable):
                    em = discord.Embed(
                        title=item.get("title", "📢 Announcement"),
                        description=item["message"],
                        colour=0x4cc9f0, timestamp=datetime.now(timezone.utc),
                    )
                    em.set_footer(text=f"Scheduled by {item['author']}")
                    try: await ch.send(embed=em)
                    except Exception as e: log.warning("Scheduled announcement failed: %s", e)
            else:
                remaining.append(item)
        if len(remaining) != len(self._scheduled):
            self._scheduled = remaining
            self._save_data()
        self._cleanup_banned_users()

    @check_scheduled.before_loop
    async def before_scheduled(self): await self.wait_until_ready()

    # ---------- Events ----------
    async def on_member_join(self, member: discord.Member) -> None:
        now = time.time()
        self._join_times.append(now)
        while self._join_times and self._join_times[0] < now - self._antiraid_window:
            self._join_times.popleft()
        if (self._antiraid_auto and not self._antiraid_enabled
                and len(self._join_times) >= self._antiraid_threshold):
            self._antiraid_enabled = True
            log.warning("Anti-raid triggered! %d joins in %ds", len(self._join_times), self._antiraid_window)
            alert_em = discord.Embed(
                title="🚨 ANTI-RAID LOCKDOWN TRIGGERED",
                description=f"**{len(self._join_times)} members** joined in **{self._antiraid_window}s** – lockdown activated!\nAction: **{self._antiraid_action.upper()}**\nUse `/antiraid_off` to disable.",
                colour=0xe63946, timestamp=datetime.now(timezone.utc),
            )
            await self._log_action(alert_em)
            if self._log_channel_id:
                ch = self.get_channel(self._log_channel_id)
                if isinstance(ch, discord.abc.Messageable):
                    try: await ch.send("@here", embed=alert_em)
                    except Exception: pass
        if self._antiraid_enabled:
            try:
                reason = "Anti-raid lockdown — bot-enforced"
                if self._antiraid_action == "ban":
                    await member.ban(reason=reason, delete_message_days=0)
                else:
                    await member.kick(reason=reason)
                action_em = discord.Embed(
                    title=f"🛡️ Anti-Raid: Member {'Banned' if self._antiraid_action == 'ban' else 'Kicked'}",
                    colour=0xe63946, timestamp=datetime.now(timezone.utc),
                )
                action_em.add_field(name="Member", value=f"{member} ({member.id})", inline=True)
                action_em.add_field(name="Action", value=self._antiraid_action.title(), inline=True)
                await self._log_action(action_em)
            except Exception as e: log.warning("Anti-raid action failed for %s: %s", member, e)
            return
        if self._autorole_id:
            role = member.guild.get_role(self._autorole_id)
            if role:
                try:
                    await member.add_roles(role, reason="Auto-role on join")
                    em = discord.Embed(title="👋 Member Joined — Auto-role Applied", colour=0x06d6a0, timestamp=datetime.now(timezone.utc))
                    em.add_field(name="Member", value=f"{member.mention} ({member})", inline=True)
                    em.add_field(name="Role", value=role.mention, inline=True)
                    await self._log_action(em)
                except Exception as e: log.warning("Auto-role failed for %s: %s", member, e)
        if self._welcome_channel_id and self._welcome_message:
            ch = member.guild.get_channel(self._welcome_channel_id)
            if isinstance(ch, discord.TextChannel):
                msg = self._welcome_message.format(mention=member.mention, server=member.guild.name, user=member.display_name)
                try: await ch.send(msg)
                except discord.Forbidden: pass

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if str(payload.message_id) in self._reaction_roles:
            guild = self.get_guild(payload.guild_id) if payload.guild_id else None
            if not guild: return
            member = payload.member
            if not member or member.bot: return
            emoji = str(payload.emoji)
            roles = self._reaction_roles[str(payload.message_id)]
            if emoji in roles:
                role = guild.get_role(roles[emoji])
                if role:
                    try: await member.add_roles(role)
                    except discord.Forbidden: pass

    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if str(payload.message_id) in self._reaction_roles:
            guild = self.get_guild(payload.guild_id) if payload.guild_id else None
            if not guild: return
            member = guild.get_member(payload.user_id)
            if not member or member.bot: return
            emoji = str(payload.emoji)
            roles = self._reaction_roles[str(payload.message_id)]
            if emoji in roles:
                role = guild.get_role(roles[emoji])
                if role:
                    try: await member.remove_roles(role)
                    except discord.Forbidden: pass

    # ---------- Core message handler (auto-mod + prefix) ----------
    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return

        # DM handling
        if message.guild is None:
            content = message.content.strip().lower()
            if content == "!ticket" or content == "/ticket" or content.startswith("!ticket ") or content.startswith("/ticket "):
                reason = "No reason provided"
                if content.startswith("!ticket "): reason = message.content[len("!ticket "):].strip()
                elif content.startswith("/ticket "): reason = message.content[len("/ticket "):].strip()
                user = message.author
                mutual_guilds = [g for g in self.guilds if g.get_member(user.id)]
                if not mutual_guilds:
                    await message.channel.send("❌ You don't share any server with me.")
                    return
                guild = mutual_guilds[0]
                self._ticket_counter += 1
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                    guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                }
                if self._mod_role_id:
                    mod_role = guild.get_role(self._mod_role_id)
                    if mod_role: overwrites[mod_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                if self._admin_role_id:
                    admin_role = guild.get_role(self._admin_role_id)
                    if admin_role: overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                category = discord.utils.get(guild.categories, name="Tickets")
                if not category:
                    try: category = await guild.create_category("Tickets")
                    except discord.Forbidden:
                        await message.channel.send("❌ I can't create a category.")
                        return
                try:
                    ticket_ch = await guild.create_text_channel(
                        name=f"ticket-{self._ticket_counter}", category=category, overwrites=overwrites
                    )
                except discord.Forbidden:
                    await message.channel.send("❌ I can't create a channel.")
                    return
                em = discord.Embed(title="📩 Ticket Created", description=f"Hello {user.mention}, your ticket has been created.\nReason: {reason}\nUse `/close` to close.", colour=0x4cc9f0)
                await ticket_ch.send(embed=em)
                self._save_data()
                await message.channel.send(f"✅ Ticket created in **{guild.name}**! Channel: {ticket_ch.mention}")
                return
            else:
                response = await self._chat_with_llm(message.content)
                if response is None:
                    response = self._get_chat_response(message.content)
                await message.channel.send(response)
                return

        # Guild messages
        if not message.guild or message.author.bot:
            return

        # Auto-mod
        if self._automod_enabled and isinstance(message.author, discord.Member):
            content = message.content
            if content:
                normalized = _normalize(content)
                triggered_word = next((w for w in self._automod_words if w in normalized), None)
                if triggered_word:
                    try: await message.delete()
                    except Exception: pass
                    uid = str(message.author.id)
                    self._automod_strikes[uid] = self._automod_strikes.get(uid, 0) + 1
                    strikes = self._automod_strikes[uid]
                    import datetime as dt
                    member = message.author
                    try:
                        if strikes >= 3:
                            if self._automod_penalty == "kick":
                                await member.kick(reason=f"Auto-mod: repeated profanity ({strikes} strikes)")
                                action_text = "**Kicked** from the server"
                                self._automod_strikes[uid] = 0
                            else:
                                until = discord.utils.utcnow() + dt.timedelta(days=7)
                                await member.timeout(until, reason=f"Auto-mod: repeated profanity ({strikes} strikes)")
                                action_text = "**Timed out for 7 days**"
                            color = 0xe63946
                        else:
                            until = discord.utils.utcnow() + dt.timedelta(minutes=10)
                            await member.timeout(until, reason=f"Auto-mod: profanity (strike {strikes}/3)")
                            action_text = "**Timed out for 10 minutes**"
                            color = 0xffd166
                    except discord.Forbidden:
                        action_text = "⚠️ Could not punish (missing permissions)"
                        color = 0xaaaaaa
                    warn_em = discord.Embed(
                        title="🤬 Language Warning",
                        description=f"{member.mention} your message was removed.\nStrike **{strikes}/3** — {action_text}.",
                        colour=color, timestamp=datetime.now(timezone.utc),
                    )
                    warn_em.set_footer(text="3 strikes = kick or 7-day timeout")
                    try: await message.channel.send(embed=warn_em, delete_after=15)
                    except Exception: pass
                    log_em = discord.Embed(title="🤬 Auto-mod: Profanity Detected", colour=color, timestamp=datetime.now(timezone.utc))
                    log_em.add_field(name="Member", value=f"{member} ({member.id})", inline=True)
                    log_em.add_field(name="Strikes", value=f"{strikes}/3", inline=True)
                    log_em.add_field(name="Action", value=action_text, inline=True)
                    log_em.add_field(name="Channel", value=message.channel.mention, inline=True)
                    await self._log_action(log_em)
                    self._automod_log.append({
                        "ts": datetime.now(timezone.utc).isoformat(), "user": f"{member} ({member.id})",
                        "uid": str(member.id), "word": triggered_word, "strikes": strikes,
                        "action": action_text, "channel": str(message.channel),
                    })
                    self._automod_log = self._automod_log[-100:]
                    self._save_data()
                    return

        # Prefix commands
        if not message.content.startswith(self._prefix):
            return
        cmd, *args = message.content[len(self._prefix):].split()
        cmd = cmd.lower()
        channel = message.channel
        author = message.author
        guild = message.guild

        async def send_embed(title, description, color=0x4cc9f0):
            em = discord.Embed(title=title, description=description, colour=color)
            await channel.send(embed=em)

        def is_mod():
            return (author.guild_permissions.administrator or
                    (self._mod_role_id and guild.get_role(self._mod_role_id) in author.roles) or
                    (self._admin_role_id and guild.get_role(self._admin_role_id) in author.roles) or
                    author.guild_permissions.manage_messages or author.guild_permissions.kick_members or
                    author.guild_permissions.ban_members or author.guild_permissions.moderate_members)

        def is_admin():
            return (author.guild_permissions.administrator or
                    (self._admin_role_id and guild.get_role(self._admin_role_id) in author.roles))

        # ---- Moderation ----
        if cmd == "kick":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}kick @member [reason]")
            member = await self._get_member_from_mention(guild, args[0])
            if not member: return await send_embed("❌ Error", "Member not found.")
            reason = " ".join(args[1:]) if len(args) > 1 else "No reason provided"
            anon = "-a" in args or "--anonymous" in args
            if anon: reason = reason.replace("-a", "").replace("--anonymous", "").strip()
            try:
                dm_content = f"You have been **kicked** from **{guild.name}**.\nReason: {reason}" if anon else f"You have been **kicked** from **{guild.name}** by {author.mention}.\nReason: {reason}"
                try: await member.send(dm_content)
                except discord.Forbidden: pass
                await member.kick(reason=reason)
                await send_embed("👢 Member Kicked", f"{member} kicked.\nReason: {reason}")
            except discord.Forbidden: await send_embed("❌ Error", "I don't have permission to kick that member.", 0xe63946)

        elif cmd == "ban":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}ban @member [reason]")
            member = await self._get_member_from_mention(guild, args[0])
            if not member: return await send_embed("❌ Error", "Member not found.")
            reason = " ".join(args[1:]) if len(args) > 1 else "No reason provided"
            anon = "-a" in args or "--anonymous" in args
            if anon: reason = reason.replace("-a", "").replace("--anonymous", "").strip()
            try:
                dm_content = f"You have been **banned** from **{guild.name}**.\nReason: {reason}" if anon else f"You have been **banned** from **{guild.name}** by {author.mention}.\nReason: {reason}"
                try: await member.send(dm_content)
                except discord.Forbidden: pass
                await member.ban(reason=reason, delete_message_days=0)
                self._banned_users[str(member.id)] = {
                    "user": str(member), "reason": reason,
                    "banned_by": "Anonymous" if anon else str(author), "timestamp": time.time()
                }
                self._save_data()
                await send_embed("🔨 Member Banned", f"{member} banned.\nReason: {reason}")
            except discord.Forbidden: await send_embed("❌ Error", "I don't have permission to ban that member.", 0xe63946)

        elif cmd == "unban":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}unban <user_id>")
            user_id = args[0]
            try:
                user = await self.fetch_user(int(user_id))
                await guild.unban(user, reason=f"Unbanned by {author}")
                if user_id in self._banned_users:
                    del self._banned_users[user_id]
                    self._save_data()
                await send_embed("🔓 Unbanned", f"Unbanned {user}")
            except discord.NotFound: await send_embed("❌ Error", "User not found in ban list.", 0xe63946)
            except discord.Forbidden: await send_embed("❌ Error", "I don't have permission to unban.", 0xe63946)

        elif cmd == "timeout":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            if len(args) < 2: return await send_embed("Usage", f"{self._prefix}timeout @member <minutes> [reason]")
            member = await self._get_member_from_mention(guild, args[0])
            if not member: return await send_embed("❌ Error", "Member not found.")
            try: minutes = int(args[1])
            except ValueError: return await send_embed("❌ Error", "Minutes must be a number.")
            reason = " ".join(args[2:]) if len(args) > 2 else "No reason provided"
            until = discord.utils.utcnow() + __import__("datetime").timedelta(minutes=minutes)
            try:
                await member.timeout(until, reason=reason)
                await send_embed("⏱️ Timed Out", f"{member} timed out for {minutes} min.\nReason: {reason}")
            except discord.Forbidden: await send_embed("❌ Error", "I don't have permission to timeout that member.", 0xe63946)

        elif cmd == "warn":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            if len(args) < 2: return await send_embed("Usage", f"{self._prefix}warn @member <reason>")
            member = await self._get_member_from_mention(guild, args[0])
            if not member: return await send_embed("❌ Error", "Member not found.")
            reason = " ".join(args[1:])
            uid = str(member.id)
            entry = {"reason": reason, "by": str(author), "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
            self._warnings.setdefault(uid, []).append(entry)
            self._save_data()
            await send_embed("⚠️ Warned", f"{member} warned: {reason}")

        elif cmd == "warnings":
            if len(args) < 1: member = author
            else: member = await self._get_member_from_mention(guild, args[0])
            if not member: return await send_embed("❌ Error", "Member not found.")
            uid = str(member.id)
            warns = self._warnings.get(uid, [])
            if not warns: return await send_embed("✅ No warnings", f"{member} has no warnings.")
            em = discord.Embed(title=f"Warnings for {member}", colour=0xffd166)
            for i, w in enumerate(warns, 1):
                em.add_field(name=f"#{i} - {w['time']}", value=f"Reason: {w['reason']}\nBy: {w['by']}", inline=False)
            await channel.send(embed=em)

        elif cmd == "clearwarnings":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}clearwarnings @member")
            member = await self._get_member_from_mention(guild, args[0])
            if not member: return await send_embed("❌ Error", "Member not found.")
            uid = str(member.id)
            count = len(self._warnings.pop(uid, []))
            self._save_data()
            await send_embed("✅ Warnings Cleared", f"Cleared {count} warnings for {member}")

        elif cmd == "bannedlist":
            self._cleanup_banned_users()
            if not self._banned_users: return await send_embed("📜 Banned List", "No users banned recently.")
            entries = sorted(self._banned_users.values(), key=lambda x: x["timestamp"], reverse=True)
            em = discord.Embed(title="Recently Banned Users", colour=0xff6b35)
            for entry in entries[:10]:
                ts = int(entry["timestamp"])
                em.add_field(name=entry["user"], value=f"Reason: {entry['reason']}\nBanned by: {entry['banned_by']}\nWhen: <t:{ts}:R>", inline=False)
            await channel.send(embed=em)

        # ---- Utility ----
        elif cmd == "purge":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}purge <amount>")
            try: amount = int(args[0])
            except ValueError: return await send_embed("❌ Error", "Amount must be a number.")
            if not 1 <= amount <= 100: return await send_embed("❌ Error", "Amount must be between 1 and 100.")
            await message.delete()
            deleted = await channel.purge(limit=amount)
            await channel.send(f"🗑️ Deleted {len(deleted)} messages.", delete_after=5)

        elif cmd == "announce":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            try:
                parts = message.content[len(self._prefix)+len("announce "):].split("|", 1)
                title = parts[0].strip()
                message_body = parts[1].strip() if len(parts) > 1 else ""
            except Exception: return await send_embed("Usage", f"{self._prefix}announce Title | Message")
            em = discord.Embed(title=title, description=message_body, colour=0x4cc9f0)
            await channel.send(embed=em)
            await message.delete()

        elif cmd == "poll":
            try:
                regex = re.findall(r'"([^"]*)"', message.content)
                if len(regex) < 3: return await send_embed("Usage", f'{self._prefix}poll "Question" "Option A" "Option B"')
                question, opt_a, opt_b = regex[0], regex[1], regex[2]
                em = discord.Embed(title=f"📊 {question}", colour=0x4cc9f0)
                em.add_field(name="🅰️", value=opt_a, inline=True)
                em.add_field(name="🅱️", value=opt_b, inline=True)
                msg = await channel.send(embed=em)
                await msg.add_reaction("🅰️")
                await msg.add_reaction("🅱️")
                await message.delete()
            except Exception as e: await send_embed("Error", str(e))

        # ---- Server Management ----
        elif cmd == "setwelcome":
            if not is_admin(): return await send_embed("❌ Permission Denied", "You need admin permissions.", 0xe63946)
            try:
                params = " ".join(args)
                if "|" in params:
                    ch_str, msg_part = params.split("|", 1)
                    ch = await self._get_channel_from_mention(guild, ch_str.strip())
                    if ch: self._welcome_channel_id = ch.id
                    else: return await send_embed("❌ Error", "Invalid channel.")
                    self._welcome_message = msg_part.strip()
                else:
                    self._welcome_message = params
                self._save_data()
                await send_embed("✅ Welcome Message Set", f"Channel: {f'<#{self._welcome_channel_id}>' if self._welcome_channel_id else 'current'}\nMessage: {self._welcome_message}")
            except Exception as e: await send_embed("Error", str(e))

        elif cmd == "setverifiedrole":
            if not is_admin(): return await send_embed("❌ Permission Denied", "You need admin permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}setverifiedrole @role")
            role = await self._get_role_from_mention(guild, args[0])
            if not role: return await send_embed("❌ Error", "Role not found.")
            self._verified_role_id = role.id
            self._save_data()
            await send_embed("✅ Verified Role Set", f"Verified role: {role.mention}")

        elif cmd == "setsuggest":
            if not is_admin(): return await send_embed("❌ Permission Denied", "You need admin permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}setsuggest #channel")
            ch = await self._get_channel_from_mention(guild, args[0])
            if not ch: return await send_embed("❌ Error", "Channel not found.")
            self._suggestion_channel_id = ch.id
            self._save_data()
            await send_embed("✅ Suggestion Channel Set", f"Suggestions will go to {ch.mention}")

        elif cmd == "suggest":
            if not self._suggestion_channel_id: return await send_embed("❌ Error", "Suggestion channel not configured.")
            suggestion_ch = guild.get_channel(self._suggestion_channel_id)
            if not suggestion_ch or not isinstance(suggestion_ch, discord.TextChannel):
                return await send_embed("❌ Error", "Suggestion channel not found.")
            text = " ".join(args)
            if not text: return await send_embed("Usage", f"{self._prefix}suggest <your suggestion>")
            em = discord.Embed(description=text, colour=0x9b5de5, timestamp=datetime.now(timezone.utc))
            em.set_author(name=f"Suggestion by {author.display_name}", icon_url=author.display_avatar.url)
            msg = await suggestion_ch.send(embed=em)
            await msg.add_reaction("👍")
            await msg.add_reaction("👎")
            await send_embed("✅ Suggestion Sent", f"Your suggestion has been posted in {suggestion_ch.mention}")
            try: await message.delete()
            except Exception: pass

        elif cmd == "verify":
            if not self._verified_role_id: return await send_embed("❌ Error", "Verified role not set. Admins use `!setverifiedrole`.")
            role = guild.get_role(self._verified_role_id)
            if not role: return await send_embed("❌ Error", "Verified role not found.")
            view = discord.ui.View()
            btn = discord.ui.Button(label="Verify", style=discord.ButtonStyle.green)
            async def verify_callback(interaction: discord.Interaction):
                if role in interaction.user.roles:
                    await interaction.response.send_message("You are already verified.", ephemeral=True)
                    return
                try:
                    await interaction.user.add_roles(role)
                    await interaction.response.send_message("✅ You are now verified!", ephemeral=True)
                except discord.Forbidden:
                    await interaction.response.send_message("❌ I can't assign roles.", ephemeral=True)
            btn.callback = verify_callback
            view.add_item(btn)
            em = discord.Embed(title="Verification", description="Click the button below to verify yourself.", colour=0x06d6a0)
            await channel.send(embed=em, view=view)
            await message.delete()

        elif cmd == "reactionrole":
            if not is_admin(): return await send_embed("❌ Permission Denied", "You need admin permissions.", 0xe63946)
            if len(args) < 2: return await send_embed("Usage", f"{self._prefix}reactionrole add <channel> <message_id> <emoji> <role>\n{self._prefix}reactionrole remove <message_id> <emoji>")
            action = args[0].lower()
            if action == "add":
                if len(args) < 5: return await send_embed("Usage", f"{self._prefix}reactionrole add <channel> <message_id> <emoji> <role>")
                ch = await self._get_channel_from_mention(guild, args[1])
                if not ch: return await send_embed("❌ Error", "Invalid channel.")
                try: msg_id = int(args[2])
                except ValueError: return await send_embed("❌ Error", "Message ID must be a number.")
                emoji = args[3]
                role = await self._get_role_from_mention(guild, args[4])
                if not role: return await send_embed("❌ Error", "Role not found.")
                msg = await ch.fetch_message(msg_id)
                try: await msg.add_reaction(emoji)
                except Exception: return await send_embed("❌ Error", "Cannot add that emoji.")
                self._reaction_roles.setdefault(str(msg_id), {})[emoji] = role.id
                self._save_data()
                await send_embed("✅ Reaction Role Added", f"React with {emoji} to get {role.mention}")
            elif action == "remove":
                if len(args) < 3: return await send_embed("Usage", f"{self._prefix}reactionrole remove <message_id> <emoji>")
                try: msg_id = int(args[1])
                except ValueError: return await send_embed("❌ Error", "Message ID must be a number.")
                emoji = args[2]
                if str(msg_id) in self._reaction_roles and emoji in self._reaction_roles[str(msg_id)]:
                    del self._reaction_roles[str(msg_id)][emoji]
                    if not self._reaction_roles[str(msg_id)]:
                        del self._reaction_roles[str(msg_id)]
                    self._save_data()
                    await send_embed("✅ Removed", f"Reaction role removed for emoji {emoji}")
                else: await send_embed("❌ Error", "That reaction role does not exist.")
            else: await send_embed("❌ Error", "Unknown action. Use `add` or `remove`.")

        elif cmd == "ticket":
            reason = " ".join(args) if args else "No reason specified"
            self._ticket_counter += 1
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                author: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            if self._mod_role_id:
                mod_role = guild.get_role(self._mod_role_id)
                if mod_role: overwrites[mod_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            if self._admin_role_id:
                admin_role = guild.get_role(self._admin_role_id)
                if admin_role: overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            category = discord.utils.get(guild.categories, name="Tickets")
            if not category:
                try: category = await guild.create_category("Tickets")
                except discord.Forbidden: return await send_embed("❌ Error", "I can't create a category.")
            try:
                ticket_ch = await guild.create_text_channel(
                    name=f"ticket-{self._ticket_counter}", category=category, overwrites=overwrites
                )
            except discord.Forbidden: return await send_embed("❌ Error", "I can't create channels.")
            em = discord.Embed(title="📩 Ticket Created", description=f"Hello {author.mention}, your ticket has been created.\nReason: {reason}\nStaff will assist you soon.\nType `{self._prefix}close` to close.", colour=0x4cc9f0)
            await ticket_ch.send(embed=em)
            self._save_data()
            await send_embed("✅ Ticket Created", f"Your ticket channel: {ticket_ch.mention}")

        elif cmd == "close":
            if not isinstance(channel, discord.TextChannel) or not channel.name.startswith("ticket-"):
                return await send_embed("❌ Error", "This is not a ticket channel.")
            try: await channel.delete(reason="Ticket closed.")
            except discord.Forbidden: await send_embed("❌ Error", "I don't have permission to delete this channel.")

        elif cmd == "giveaway":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            try:
                full = " ".join(args)
                parts = full.split("|")
                prize = parts[0].strip()
                duration_min = int(parts[1].strip())
                winners = int(parts[2].strip())
            except Exception: return await send_embed("Usage", f"{self._prefix}giveaway Prize | DurationMinutes | Winners")
            if duration_min < 1: return await send_embed("❌ Error", "Duration must be at least 1 minute.")
            end_time = time.time() + duration_min * 60
            em = discord.Embed(title="🎉 Giveaway!", description=f"**Prize:** {prize}\nReact with 🎉 to enter!\nEnds: <t:{int(end_time)}:R>", colour=0xf72585)
            msg = await channel.send(embed=em)
            await msg.add_reaction("🎉")
            self._giveaways[msg.id] = {"prize": prize, "end_time": end_time, "winners": winners, "channel_id": channel.id}
            self._save_data()

        elif cmd == "tempvc":
            if not is_admin(): return await send_embed("❌ Permission Denied", "You need admin permissions.", 0xe63946)
            if len(args) < 2: return await send_embed("Usage", f"{self._prefix}tempvc create <name> <duration_minutes>")
            action = args[0].lower()
            if action != "create": return await send_embed("Usage", f"{self._prefix}tempvc create <name> <duration_minutes>")
            try:
                name = " ".join(args[1:-1])
                minutes = int(args[-1])
            except ValueError: return await send_embed("❌ Error", "Duration must be a number.")
            if minutes < 1: return await send_embed("❌ Error", "Duration must be at least 1 minute.")
            try:
                vc = await guild.create_voice_channel(name)
                self._temp_vcs[vc.id] = {"expires": time.time() + minutes * 60, "creator_id": author.id}
                self._save_data()
                await send_embed("🎤 Temporary VC Created", f"{vc.mention} will be deleted in {minutes} min.")
            except discord.Forbidden: await send_embed("❌ Error", "I can't create voice channels.")

        elif cmd == "help":
            em = discord.Embed(title="Bot Help", description=f"Prefix: `{self._prefix}`\nUse slash commands for more features.", colour=0x4cc9f0)
            em.add_field(name="Moderation", value="kick, ban, unban, timeout, warn, warnings, clearwarnings, bannedlist, purge", inline=False)
            em.add_field(name="Server Management", value="setwelcome, verify, suggest, reactionrole, ticket, giveaway, tempvc", inline=False)
            em.add_field(name="Other", value="announce, poll, setprefix, stats, ask", inline=False)
            await channel.send(embed=em)

        elif cmd == "setprefix":
            if not is_admin(): return await send_embed("❌ Permission Denied", "You need admin permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}setprefix <new_prefix>")
            new_prefix = args[0]
            if len(new_prefix) > 5: return await send_embed("❌ Error", "Prefix must be 5 characters or fewer.")
            self._prefix = new_prefix
            self._save_data()
            await send_embed("✅ Prefix Changed", f"Prefix set to `{self._prefix}`")

        elif cmd == "stats":
            em = discord.Embed(title="Bot Stats", colour=0x4cc9f0)
            em.add_field(name="Commands Used", value=str(self._command_uses))
            em.add_field(name="Prefix", value=self._prefix)
            await channel.send(embed=em)

        elif cmd == "ask":
            question = " ".join(args)
            async with channel.typing():
                response = await self._chat_with_llm(question)
                if response is None: response = self._get_chat_response(question)
                await channel.send(response)

        else:
            # unknown command → LLM
            async with channel.typing():
                response = await self._chat_with_llm(message.content[len(self._prefix):])
                if response is None: response = self._get_chat_response(message.content[len(self._prefix):])
                await channel.send(response)

    # ---------- LLM integration ----------
    async def _chat_with_llm(self, user_message: str) -> str | None:
        if not GROQ_API_KEY:
            return None
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": "You are a friendly Discord bot. Be concise, fun, and helpful."},
                {"role": "user", "content": user_message}
            ],
            "max_tokens": 150,
            "temperature": 0.7
        }
        try:
            s = await self._session_()
            async with s.post(url, json=payload, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    log.warning("Groq API error: %s", resp.status)
                    return None
        except Exception as e:
            log.warning("Groq API call failed: %s", e)
            return None

    def _get_chat_response(self, message: str) -> str:
        msg = message.lower().strip()
        for keyword, responses in CHAT_RESPONSES.items():
            if keyword in msg:
                return random.choice(responses)
        return random.choice(FALLBACK_RESPONSES)

    async def _get_member_from_mention(self, guild: discord.Guild, mention: str) -> discord.Member | None:
        if mention.startswith("<@") and mention.endswith(">"):
            try:
                member_id = int(mention.strip("<@!>"))
                return guild.get_member(member_id) or await guild.fetch_member(member_id)
            except Exception: pass
        return None

    async def _get_role_from_mention(self, guild: discord.Guild, mention: str) -> discord.Role | None:
        if mention.startswith("<@&") and mention.endswith(">"):
            try:
                role_id = int(mention.strip("<@&>"))
                return guild.get_role(role_id)
            except Exception: pass
        return None

    async def _get_channel_from_mention(self, guild: discord.Guild, mention: str) -> discord.TextChannel | None:
        if mention.startswith("<#") and mention.endswith(">"):
            try:
                channel_id = int(mention.strip("<#>"))
                ch = guild.get_channel(channel_id)
                if isinstance(ch, discord.TextChannel): return ch
            except Exception: pass
        return None

    # ---------- Background tasks ----------
    @tasks.loop(seconds=15)
    async def check_giveaways(self) -> None:
        now = time.time()
        expired = []
        for msg_id, gdata in list(self._giveaways.items()):
            if now >= gdata["end_time"]:
                expired.append(msg_id)
                channel = self.get_channel(gdata["channel_id"])
                if not isinstance(channel, discord.TextChannel): continue
                try: message = await channel.fetch_message(msg_id)
                except discord.NotFound: continue
                reaction = discord.utils.get(message.reactions, emoji="🎉")
                users = []
                if reaction:
                    async for user in reaction.users():
                        if not user.bot: users.append(user)
                winners_needed = min(gdata["winners"], len(users))
                winners = random.sample(users, winners_needed) if winners_needed > 0 else []
                winner_mentions = ", ".join(w.mention for w in winners) if winners else "No one"
                em = discord.Embed(title="🎉 Giveaway Ended!", description=f"**Prize:** {gdata['prize']}\n**Winners:** {winner_mentions}", colour=0x06d6a0)
                await channel.send(embed=em)
                del self._giveaways[msg_id]
        if expired: self._save_data()

    @tasks.loop(seconds=30)
    async def check_tempvcs(self) -> None:
        now = time.time()
        to_delete = [cid for cid, vcdata in self._temp_vcs.items() if now >= vcdata["expires"]]
        for cid in to_delete:
            vc = self.get_channel(cid)
            if vc and isinstance(vc, discord.VoiceChannel):
                try: await vc.delete()
                except discord.Forbidden: pass
            del self._temp_vcs[cid]
        if to_delete: self._save_data()

    @check_giveaways.before_loop
    async def before_giveaways(self): await self.wait_until_ready()

    @check_tempvcs.before_loop
    async def before_tempvcs(self): await self.wait_until_ready()

    # ---------- Main update polling ----------
    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def poll_updates(self) -> None:
        self._last_check_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if time.time() < self._muted_until: return
        channel = self.get_channel(self.update_channel_id)
        if not isinstance(channel, discord.abc.Messageable): return
        ping_content = ""
        if PING_EVERYONE:
            guild = channel.guild if isinstance(channel, discord.TextChannel) else None
            if guild and self._ping_role_id:
                role = guild.get_role(self._ping_role_id)
                ping_content = f"{role.mention}\n" if role else "@everyone\n"
            else: ping_content = "@everyone\n"
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
                        title="🚨 Roblox Update Detected!", description="This is a live update, Roblox is **patched**.",
                        colour=0xe63946, timestamp=now,
                    )
                    em.add_field(name="Platform", value="Windows", inline=False)
                    em.add_field(name="Version Hash", value=f"`{cv}`", inline=False)
                    em.add_field(name="Date", value=ts, inline=False)
                    em.set_footer(text=date_str)
                    await channel.send(content=ping_content, embed=em)
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
                        await channel.send(content=ping_content, embed=em)
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
                        await channel.send(content=ping_content, embed=em)
                    self._last_incident_id = latest_inc["id"]

    @poll_updates.before_loop
    async def before_poll(self): await self.wait_until_ready()

    # ---------- Setup & Ready ----------
    async def setup_hook(self) -> None:
        self.poll_updates.start()
        self.rotate_presence.start()
        self.poll_ugc_prices.start()
        self.check_scheduled.start()
        self.check_giveaways.start()
        self.check_tempvcs.start()

    async def on_ready(self) -> None:
        if not self.user: return
        self._start_time = time.time()
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                log.info("Synced commands to guild %s (%s)", guild.name, guild.id)
            except Exception as e:
                log.warning("Failed to sync to guild %s: %s", guild.id, e)
        channel = self.get_channel(self.update_channel_id)
        if isinstance(channel, discord.abc.Messageable):
            cv = await self.get_client_version()
            em = discord.Embed(
                title="🚀 Roblox Update Tracker — Online",
                description="Bot is online and monitoring for updates!",
                colour=0x4cc9f0, timestamp=datetime.now(timezone.utc),
            )
            em.add_field(name="🎮 Client", value=f"`{cv or 'N/A'}`", inline=True)
            em.set_footer(text=f"Polling every {CHECK_INTERVAL_MINUTES} min")
            await channel.send(embed=em)


# ============================================================================
# Instantiate bot
# ============================================================================
bot = RobloxBot()

# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------
def mod_check() -> typing.Callable:
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not interaction.guild:
            raise app_commands.CheckFailure("Not in a guild or not a Member")
        m = interaction.user
        if m.guild_permissions.administrator: return True
        if bot._admin_role_id:
            r = interaction.guild.get_role(bot._admin_role_id)
            if r and r in m.roles: return True
        if bot._mod_role_id:
            r = interaction.guild.get_role(bot._mod_role_id)
            if r and r in m.roles: return True
        if m.guild_permissions.manage_messages or m.guild_permissions.kick_members \
                or m.guild_permissions.ban_members or m.guild_permissions.moderate_members:
            return True
        raise app_commands.MissingPermissions(["manage_messages"])
    return app_commands.check(predicate)

def admin_check() -> typing.Callable:
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not interaction.guild:
            raise app_commands.CheckFailure("Not in a guild or not a Member")
        m = interaction.user
        if m.guild_permissions.administrator: return True
        if bot._admin_role_id:
            r = interaction.guild.get_role(bot._admin_role_id)
            if r and r in m.roles: return True
        raise app_commands.MissingPermissions(["administrator"])
    return app_commands.check(predicate)

@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
    else:
        log.error("Unhandled command error: %s", error)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred.", ephemeral=True)

# ============================================================================
# SLASH COMMANDS (unchanged, all here)
# ============================================================================
@bot.tree.command(name="roblox_version", description="Current live Roblox client version")
async def cmd_roblox_version(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    v = await bot.get_client_version()
    now = datetime.now(timezone.utc)
    em = discord.Embed(title="🚨 Roblox Update Info", description="Current live version from Roblox CDN.", colour=0xe63946, timestamp=now)
    em.add_field(name="Platform", value="Windows", inline=False)
    em.add_field(name="Version Hash", value=f"`{v or 'N/A'}`", inline=False)
    em.add_field(name="Date", value=now.strftime("%B %d, %Y %I:%M %p"), inline=False)
    em.set_footer(text=now.strftime("%m/%d/%Y %I:%M %p"))
    await interaction.followup.send(embed=em)

@bot.tree.command(name="latest_updates", description="Latest DevForum announcements")
async def cmd_latest_updates(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    posts = await bot.get_devforum_posts(DEVFORUM_ANNOUNCEMENTS_URL, limit=5)
    em = discord.Embed(title="📢 Latest DevForum Announcements", colour=0xffd166)
    if posts:
        for p in posts: em.add_field(name=p["title"], value=f"[Read more]({p['url']}) • {p['posts_count']} replies", inline=False)
    else: em.description = "Could not retrieve announcements right now."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="release_notes", description="Official Roblox release notes")
async def cmd_release_notes(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    posts = await bot.get_devforum_posts(DEVFORUM_RELEASES_URL, limit=5)
    em = discord.Embed(title="📋 Roblox Release Notes", colour=0x06d6a0)
    if posts:
        for p in posts: em.add_field(name=p["title"], value=f"[Read more]({p['url']}) • {p['posts_count']} replies", inline=False)
    else: em.description = "Could not retrieve release notes right now."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="upcoming_features", description="Beta & upcoming Roblox features")
async def cmd_upcoming_features(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    posts = await bot.get_devforum_posts(DEVFORUM_BETA_URL, limit=5)
    em = discord.Embed(title="🔭 Upcoming & Beta Features", colour=0x9b5de5)
    if posts:
        for p in posts: em.add_field(name=p["title"], value=f"[Read more]({p['url']}) • {p['posts_count']} replies", inline=False)
    else: em.description = "No upcoming features found right now."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="security_updates", description="Recent Roblox security patches and incidents")
async def cmd_security_updates(interaction: discord.Interaction) -> None:
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
    else: em.add_field(name="✅ No Active Incidents", value="Roblox is clean.", inline=False)
    if sec:
        em.add_field(name="━━━━━━━━━━━━━━", value="**Security DevForum Posts**", inline=False)
        for p in sec[:3]: em.add_field(name=p["title"], value=f"[Read more]({p['url']})", inline=False)
    em.set_footer(text="status.roblox.com + DevForum")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="status", description="Full Roblox platform status")
async def cmd_status(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    data = await bot.get_status_summary()
    if not data: await interaction.followup.send("❌ Could not reach status page."); return
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
async def cmd_stats(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    uptime = int(time.time() - bot._start_time)
    h, rem = divmod(uptime, 3600)
    m, s = divmod(rem, 60)
    muted = f"<t:{int(bot._muted_until)}:R>" if time.time() < bot._muted_until else "Not muted"
    em = discord.Embed(title="📊 Bot Stats", colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="⏱️ Uptime", value=f"{h}h {m}m {s}s", inline=True)
    em.add_field(name="🕐 Last Check", value=bot._last_check_time, inline=True)
    em.add_field(name="🔄 Interval", value=f"Every {CHECK_INTERVAL_MINUTES} min", inline=True)
    em.add_field(name="🎮 Client Version", value=f"`{bot._last_client_version or 'N/A'}`", inline=True)
    em.add_field(name="🔔 @everyone", value="Enabled" if PING_EVERYONE else "Disabled", inline=True)
    em.add_field(name="🔕 Muted", value=muted, inline=True)
    em.add_field(name="📋 Changelog", value=f"{len(bot._client_changelog)} entries", inline=True)
    em.add_field(name="👁️ Watched Items", value=str(len(bot._watched_items)), inline=True)
    em.add_field(name="💬 Commands Used", value=str(bot._command_uses), inline=True)
    em.add_field(name="🔍 Active Filters", value=", ".join(k for k,v in bot._filters.items() if v) or "None", inline=False)
    em.set_footer(text="Roblox Update Tracker")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="changelog", description="Last 10 detected version changes")
async def cmd_changelog(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    em = discord.Embed(title="📅 Version Changelog", colour=0xffd166, timestamp=datetime.now(timezone.utc))
    if bot._client_changelog:
        em.add_field(name="🎮 Client Updates",
                     value="\n".join([f"`{e['version']}` — {e['time']}" for e in reversed(bot._client_changelog)]),
                     inline=False)
    else: em.add_field(name="🎮 Client Updates", value="No updates detected this session.", inline=False)
    em.set_footer(text="Resets on restart")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="compare_versions", description="Compare two Roblox version strings")
@app_commands.describe(version1="First version string", version2="Second version string")
async def cmd_compare_versions(interaction: discord.Interaction, version1: str, version2: str) -> None:
    bot._command_uses += 1
    def parse(v: str): return [int(x) for x in v.replace("version-","").split(".") if x.isdigit()]
    try:
        v1, v2 = parse(version1), parse(version2)
        if v1 == v2: result, color = "🟰 **Identical** — same version", 0xaaaaaa
        elif v1 > v2: result, color = f"⬆️ **`{version1}` is newer** than `{version2}`", 0x06d6a0
        else: result, color = f"⬆️ **`{version2}` is newer** than `{version1}`", 0x4cc9f0
    except Exception: result, color = "❌ Could not parse one or both versions.", 0xe63946
    em = discord.Embed(title="🔀 Version Comparison", description=result, colour=color)
    em.add_field(name="Version A", value=f"`{version1}`", inline=True)
    em.add_field(name="Version B", value=f"`{version2}`", inline=True)
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="game_status", description="Check status of a Roblox game by Place ID")
@app_commands.describe(place_id="The Roblox Place ID")
async def cmd_game_status(interaction: discord.Interaction, place_id: str) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    try: pid = int(place_id)
    except ValueError: await interaction.followup.send("❌ Invalid Place ID."); return
    uid = await bot.get_universe_id(pid)
    if not uid: await interaction.followup.send("❌ Could not find that game."); return
    game = await bot.get_game_info(uid)
    if not game: await interaction.followup.send("❌ Could not fetch game info."); return
    active = game.get("isActive", False)
    em = discord.Embed(title=f"🎮 {game.get('name','Unknown')}", url=f"https://www.roblox.com/games/{pid}",
                       colour=0x06d6a0 if active else 0xe63946, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Status", value="🟢 Active" if active else "🔴 Inactive", inline=True)
    em.add_field(name="Playing", value=f"{game.get('playing',0):,}", inline=True)
    em.add_field(name="Visits", value=f"{game.get('visits',0):,}", inline=True)
    em.add_field(name="Creator", value=game.get("creator",{}).get("name","?"), inline=True)
    em.add_field(name="Updated", value=game.get("updated","?")[:10], inline=True)
    em.set_footer(text="Roblox Games API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="random_game", description="Get a random popular Roblox game")
async def cmd_random_game(interaction: discord.Interaction) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    d = await bot._json(ROBLOX_GAMES_LIST_URL)
    if not d or not d.get("games"): await interaction.followup.send("❌ Could not fetch games list."); return
    games = d["games"]
    game = random.choice(games)
    em = discord.Embed(title=f"🎲 Random Game: {game.get('name','?')}",
                       url=f"https://www.roblox.com/games/{game.get('placeId',0)}",
                       colour=0x9b5de5, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Playing", value=f"{game.get('playerCount',0):,}", inline=True)
    em.add_field(name="Visits", value=f"{game.get('totalUpVotes',0):,} 👍", inline=True)
    em.set_footer(text="Roblox Games API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="player_lookup", description="Look up a Roblox player by username")
@app_commands.describe(username="Roblox username to look up")
async def cmd_player_lookup(interaction: discord.Interaction, username: str) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    user = await bot.lookup_user(username)
    if not user: await interaction.followup.send("❌ Could not find that user."); return
    uid = user.get("id")
    if not uid: await interaction.followup.send("❌ User ID missing."); return
    friends = await bot.get_friend_count(uid)
    badges = await bot.get_user_badges(uid)
    created = user.get("created","")[:10]
    em = discord.Embed(title=f"👤 {user.get('displayName','?')} (@{user.get('name','?')})",
                       url=f"https://www.roblox.com/users/{uid}/profile",
                       colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="User ID", value=str(uid), inline=True)
    em.add_field(name="Joined", value=created, inline=True)
    em.add_field(name="Friends", value=str(friends), inline=True)
    em.add_field(name="Badges", value=f"{len(badges)}+", inline=True)
    em.add_field(name="Banned", value="✅ No" if not user.get("isBanned") else "❌ Yes", inline=True)
    if user.get("description"): em.add_field(name="Bio", value=user["description"][:200], inline=False)
    em.set_footer(text="Roblox Users API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="group_info", description="Look up a Roblox group by ID")
@app_commands.describe(group_id="Roblox group ID")
async def cmd_group_info(interaction: discord.Interaction, group_id: str) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    try: gid = int(group_id)
    except ValueError: await interaction.followup.send("❌ Invalid group ID."); return
    group = await bot.get_group(gid)
    if not group: await interaction.followup.send("❌ Could not find that group."); return
    em = discord.Embed(title=f"👥 {group.get('name','?')}",
                       url=f"https://www.roblox.com/groups/{gid}",
                       colour=0xffd166, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Members", value=f"{group.get('memberCount',0):,}", inline=True)
    em.add_field(name="Owner", value=group.get("owner",{}).get("username","?"), inline=True)
    em.add_field(name="Public", value="✅ Yes" if group.get("publicEntryAllowed") else "🔒 No", inline=True)
    if group.get("description"): em.add_field(name="Description", value=group["description"][:300], inline=False)
    em.set_footer(text="Roblox Groups API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="badge_check", description="Check if a user has a specific badge")
@app_commands.describe(username="Roblox username", badge_id="Badge ID to check")
async def cmd_badge_check(interaction: discord.Interaction, username: str, badge_id: str) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    try: bid = int(badge_id)
    except ValueError: await interaction.followup.send("❌ Invalid badge ID."); return
    user = await bot.lookup_user(username)
    if not user or not user.get("id"): await interaction.followup.send("❌ User not found."); return
    badge = await bot.get_badge(bid)
    has_it = await bot.user_has_badge(user["id"], bid)
    em = discord.Embed(title="🏅 Badge Check", colour=0x06d6a0 if has_it else 0xe63946)
    em.add_field(name="Player", value=f"@{user.get('name','?')}", inline=True)
    em.add_field(name="Badge", value=badge.get("name","?") if badge else str(bid), inline=True)
    em.add_field(name="Result", value="✅ Has this badge!" if has_it else "❌ Does not have this badge", inline=False)
    await interaction.followup.send(embed=em)

@bot.tree.command(name="robux_rates", description="Current Robux to USD exchange and DevEx rates")
async def cmd_robux_rates(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    em = discord.Embed(title="💰 Robux Exchange Rates", colour=0x06d6a0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Buy Rate", value="$0.0035 per Robux\n(~286 R$ per $1)", inline=False)
    em.add_field(name="DevEx Rate", value="$0.0035 per Robux earned\n(Min 30,000 R$)", inline=False)
    em.add_field(name="Roblox Premium", value="$4.99 → 450 R$\n$9.99 → 1,000 R$\n$19.99 → 2,200 R$", inline=False)
    em.add_field(name="Gift Card", value="$10 → 800 R$\n$25 → 2,000 R$\n$50 → 4,500 R$", inline=False)
    em.set_footer(text="Rates as of 2026 — check roblox.com for latest")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="trade_calculator", description="Calculate if a Roblox trade is worth it based on RAP")
@app_commands.describe(your_rap="Your items total RAP", their_rap="Their items total RAP")
async def cmd_trade_calculator(interaction: discord.Interaction, your_rap: int, their_rap: int) -> None:
    bot._command_uses += 1
    diff = their_rap - your_rap
    pct = (diff / your_rap * 100) if your_rap else 0
    if diff > 0: verdict = f"✅ **Good trade!** You gain R${diff:,} RAP ({pct:+.1f}%)"; color = 0x06d6a0
    elif diff < 0: verdict = f"❌ **Bad trade!** You lose R${abs(diff):,} RAP ({pct:+.1f}%)"; color = 0xe63946
    else: verdict = "🟰 **Even trade** — equal RAP value"; color = 0xaaaaaa
    em = discord.Embed(title="⚖️ Trade Calculator", description=verdict, colour=color)
    em.add_field(name="Your RAP", value=f"R${your_rap:,}", inline=True)
    em.add_field(name="Their RAP", value=f"R${their_rap:,}", inline=True)
    em.add_field(name="Difference", value=f"R${diff:+,}", inline=True)
    em.set_footer(text="RAP = Recent Average Price")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="limited_tracker", description="Check resale data for a Roblox limited item")
@app_commands.describe(asset_id="Asset ID of the limited item")
async def cmd_limited_tracker(interaction: discord.Interaction, asset_id: str) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    try: aid = int(asset_id)
    except ValueError: await interaction.followup.send("❌ Invalid asset ID."); return
    resale = await bot.get_item_resale(aid)
    details = await bot.get_item_details(aid)
    if not resale: await interaction.followup.send("❌ Could not fetch item. Is it a limited?"); return
    name = details.get("name", f"Item {aid}") if details else f"Item {aid}"
    rap  = resale.get("recentAveragePrice", 0)
    orig = resale.get("originalPrice", 0)
    vol  = resale.get("volume", 0)
    em = discord.Embed(title=f"📈 Limited: {name}", url=f"https://www.roblox.com/catalog/{aid}",
                       colour=0xffd166, timestamp=datetime.now(timezone.utc))
    em.add_field(name="RAP (Avg)", value=f"R${rap:,}", inline=True)
    em.add_field(name="Original Price", value=f"R${orig:,}", inline=True)
    em.add_field(name="Total Volume", value=f"{vol:,}", inline=True)
    if orig and rap:
        roi = ((rap - orig) / orig * 100)
        em.add_field(name="ROI vs Original", value=f"{roi:+.1f}%", inline=True)
    em.set_footer(text="Roblox Economy API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="ugc_trending", description="Trending UGC items on the Roblox catalog")
async def cmd_ugc_trending(interaction: discord.Interaction) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    items = await bot.get_catalog_items(8)
    em = discord.Embed(title="🛍️ Trending UGC Items", colour=0xf72585, timestamp=datetime.now(timezone.utc))
    if items:
        for item in items:
            price_str = f"R${item['price']:,}" if item["price"] else "Free"
            em.add_field(name=item["name"][:50], value=f"💰 {price_str} | 👤 {item['creator']}\n[View](https://www.roblox.com/catalog/{item['id']})", inline=True)
    else: em.description = "Could not fetch catalog right now."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="ugc_price", description="Check resale price of a UGC item")
@app_commands.describe(asset_id="Roblox asset ID")
async def cmd_ugc_price(interaction: discord.Interaction, asset_id: str) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    try: aid = int(asset_id)
    except ValueError: await interaction.followup.send("❌ Invalid asset ID."); return
    resale = await bot.get_item_resale(aid)
    details = await bot.get_item_details(aid)
    if not resale: await interaction.followup.send("❌ Could not fetch item."); return
    name = details.get("name", f"Item {aid}") if details else f"Item {aid}"
    em = discord.Embed(title=f"💰 {name}", url=f"https://www.roblox.com/catalog/{aid}",
                       colour=0xffd166, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Original Price", value=f"R${resale.get('originalPrice',0):,}", inline=True)
    em.add_field(name="Recent Avg Price", value=f"R${resale.get('recentAveragePrice',0):,}", inline=True)
    em.add_field(name="Total Volume", value=f"{resale.get('volume',0):,} sales", inline=True)
    em.set_footer(text="Roblox Economy API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="ugc_watch", description="Watch a UGC item for price change alerts")
@app_commands.describe(asset_id="Roblox asset ID to watch")
async def cmd_ugc_watch(interaction: discord.Interaction, asset_id: str) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    try: aid = int(asset_id)
    except ValueError: await interaction.followup.send("❌ Invalid asset ID."); return
    if len(bot._watched_items) >= 20: await interaction.followup.send("❌ Already watching 20 items max."); return
    resale = await bot.get_item_resale(aid)
    details = await bot.get_item_details(aid)
    if not resale: await interaction.followup.send("❌ Could not find that item."); return
    name = details.get("name", f"Item {aid}") if details else f"Item {aid}"
    price = resale.get("recentAveragePrice") or resale.get("originalPrice") or 0
    bot._watched_items[aid] = {"name": name, "price": price}
    em = discord.Embed(title="👁️ Now Watching", description=f"**[{name}](https://www.roblox.com/catalog/{aid})**",
                       colour=0x06d6a0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Current Price", value=f"R${price:,}", inline=True)
    em.add_field(name="Watching", value=f"{len(bot._watched_items)}/20 items", inline=True)
    em.set_footer(text="Checks every 30 min for price changes")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="ugc_unwatch", description="Stop watching a UGC item")
@app_commands.describe(asset_id="Asset ID to stop watching")
async def cmd_ugc_unwatch(interaction: discord.Interaction, asset_id: str) -> None:
    bot._command_uses += 1
    try: aid = int(asset_id)
    except ValueError: await interaction.response.send_message("❌ Invalid asset ID."); return
    if aid in bot._watched_items:
        name = bot._watched_items.pop(aid).get("name", str(aid))
        await interaction.response.send_message(f"✅ Stopped watching **{name}**.")
    else: await interaction.response.send_message("❌ That item is not being watched.")

@bot.tree.command(name="ugc_watchlist", description="Show all watched UGC items")
async def cmd_ugc_watchlist(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    em = discord.Embed(title="👁️ UGC Watchlist", colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    if bot._watched_items:
        for aid, info in bot._watched_items.items():
            em.add_field(name=info.get("name", str(aid)), value=f"💰 R${info.get('price',0):,} | [View](https://www.roblox.com/catalog/{aid})", inline=True)
    else: em.description = "No items watched. Use `/ugc_watch <asset_id>` to add one!"
    em.set_footer(text=f"{len(bot._watched_items)}/20 items • checks every 30 min")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="alert_threshold", description="Only alert on UGC price changes above X percent")
@app_commands.describe(percent="Minimum % change to trigger an alert (0 = any change)")
async def cmd_alert_threshold(interaction: discord.Interaction, percent: float) -> None:
    bot._command_uses += 1
    bot._alert_threshold = max(0.0, percent)
    await interaction.response.send_message(f"✅ UGC price alerts will only fire when price changes by **{bot._alert_threshold:.1f}%** or more.")

@bot.tree.command(name="mute_updates", description="Pause auto-alerts for X hours")
@app_commands.describe(hours="Number of hours to mute alerts (0 to unmute)")
@admin_check()
async def cmd_mute_updates(interaction: discord.Interaction, hours: float) -> None:
    bot._command_uses += 1
    if hours <= 0:
        bot._muted_until = 0
        await interaction.response.send_message("🔔 Alerts have been **unmuted**.")
    else:
        bot._muted_until = time.time() + hours * 3600
        await interaction.response.send_message(f"🔕 Alerts muted for **{hours}h**. Resumes <t:{int(bot._muted_until)}:R>.")

@bot.tree.command(name="filter_updates", description="Choose which update types to receive alerts for")
@app_commands.describe(client="Alert on Roblox client updates",
                       devforum="Alert on new DevForum announcements",
                       incident="Alert on Roblox status incidents")
@admin_check()
async def cmd_filter_updates(interaction: discord.Interaction,
                              client: bool = True, devforum: bool = True, incident: bool = True) -> None:
    bot._command_uses += 1
    bot._filters = {"client": client, "devforum": devforum, "incident": incident}
    em = discord.Embed(title="🔍 Update Filters Set", colour=0x4cc9f0)
    em.add_field(name="🎮 Client Updates", value="✅ On" if client else "❌ Off", inline=True)
    em.add_field(name="📢 DevForum Alerts", value="✅ On" if devforum else "❌ Off", inline=True)
    em.add_field(name="🚨 Incident Alerts", value="✅ On" if incident else "❌ Off", inline=True)
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="server_stats", description="Show bot usage stats for this server")
async def cmd_server_stats(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    uptime = int(time.time() - bot._start_time)
    h, rem = divmod(uptime, 3600)
    m, _ = divmod(rem, 60)
    em = discord.Embed(title="📈 Server Stats", colour=0x9b5de5, timestamp=datetime.now(timezone.utc))
    em.add_field(name="💬 Total Commands Used", value=str(bot._command_uses), inline=True)
    em.add_field(name="⏱️ Bot Uptime", value=f"{h}h {m}m", inline=True)
    em.add_field(name="🔔 Alert Channel", value=f"<#{bot.update_channel_id}>" if bot.update_channel_id else "Not set", inline=True)
    em.add_field(name="👁️ Watched UGC Items", value=str(len(bot._watched_items)), inline=True)
    em.add_field(name="📋 Version Changes", value=str(len(bot._client_changelog)), inline=True)
    em.add_field(name="🔕 Muted", value="Yes" if time.time() < bot._muted_until else "No", inline=True)
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="poll", description="Create a quick Roblox poll")
@app_commands.describe(question="Poll question", option_a="First option", option_b="Second option")
async def cmd_poll(interaction: discord.Interaction, question: str, option_a: str, option_b: str) -> None:
    bot._command_uses += 1
    em = discord.Embed(title=f"📊 {question}", colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="🅰️ Option A", value=option_a, inline=True)
    em.add_field(name="🅱️ Option B", value=option_b, inline=True)
    em.set_footer(text=f"Poll by {interaction.user.display_name}")
    await interaction.response.send_message(embed=em)
    message = await interaction.original_response()
    await message.add_reaction("🅰️")
    await message.add_reaction("🅱️")

@bot.tree.command(name="uptime_history", description="Roblox incident history for the last 30 days")
async def cmd_uptime_history(interaction: discord.Interaction) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    incidents = await bot.get_incident_history(10)
    em = discord.Embed(title="📅 Roblox Incident History (Last 30 Days)", colour=0xff6b35, timestamp=datetime.now(timezone.utc))
    if incidents:
        for inc in incidents:
            icon = {"none":"🟢","minor":"🟡","major":"🟠","critical":"🔴"}.get(inc["impact"],"⚪")
            em.add_field(name=f"{icon} {inc['name']}",
                         value=f"Status: `{inc['status'].replace('_',' ').title()}` | {inc['created_at']}\n[View]({inc['url']})",
                         inline=False)
    else: em.description = "✅ No incidents found in the last 30 days!"
    em.set_footer(text="status.roblox.com")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="deploy_history", description="Last 15 CDN deploy log entries")
async def cmd_deploy_history(interaction: discord.Interaction) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    entries = await bot.get_deploy_history(15)
    em = discord.Embed(title="📦 CDN Deploy History", colour=0x4cc9f0)
    if entries: em.description = f"```\n{chr(10).join(entries)[-3900:]}\n```"
    else: em.description = "Could not retrieve deploy history."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="set_update_channel", description="Set the alert channel (Admin only)")
@admin_check()
@app_commands.describe(channel="Channel to post alerts in")
async def cmd_set_update_channel(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
    bot.update_channel_id = channel.id
    await interaction.response.send_message(f"✅ Alerts will now post in {channel.mention}.")

@bot.tree.command(name="help_roblox", description="Show all commands")
async def cmd_help(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    em = discord.Embed(title="🤖 Roblox Update Tracker — All Commands", colour=0x4cc9f0)
    categories = {
        "📡 Updates & Versions": [
            ("/roblox_version", "Current live Roblox version"),
            ("/latest_updates", "Latest DevForum announcements"),
            ("/release_notes", "Official release notes"),
            ("/upcoming_features", "Beta & upcoming features"),
            ("/changelog", "Last 10 version changes"),
            ("/compare_versions", "Compare two version strings"),
            ("/deploy_history", "CDN deploy log"),
        ],
        "🔒 Security & Status": [
            ("/security_updates", "Security patches and incidents"),
            ("/status", "Full platform status"),
            ("/uptime_history", "Incident history last 30 days"),
        ],
        "🎮 Games & Players": [
            ("/game_status", "Check a game by Place ID"),
            ("/random_game", "Get a random popular game"),
            ("/player_lookup", "Look up a Roblox player"),
            ("/group_info", "Look up a Roblox group"),
            ("/badge_check", "Check if a user has a badge"),
        ],
        "💰 Economy & UGC": [
            ("/robux_rates", "Robux to USD exchange rates"),
            ("/trade_calculator", "Calculate if a trade is worth it"),
            ("/limited_tracker", "Track a limited item's RAP"),
            ("/ugc_trending", "Trending UGC items"),
            ("/ugc_price", "Check UGC item resale price"),
            ("/ugc_watch", "Watch item for price alerts"),
            ("/ugc_unwatch", "Stop watching an item"),
            ("/ugc_watchlist", "Show watched items"),
            ("/alert_threshold", "Set min % for price alerts"),
        ],
        "⚙️ Bot Management": [
            ("/stats", "Bot stats and uptime"),
            ("/server_stats", "Server usage stats"),
            ("/poll", "Create a quick poll"),
            ("/mute_updates", "Pause alerts for X hours (Admin)"),
            ("/filter_updates", "Choose alert types (Admin)"),
            ("/set_update_channel", "Set alert channel (Admin)"),
        ],
        "🔨 Moderation": [
            ("/warn", "Warn a user and log it"),
            ("/warnings", "See all warnings for a user"),
            ("/clearwarnings", "Clear a user's warnings"),
            ("/kick", "Kick a user (optionally anonymous)"),
            ("/ban", "Ban a user (optionally anonymous)"),
            ("/unban", "Unban a user by ID"),
            ("/banned_list", "Show recently banned users"),
            ("/timeout", "Timeout a user for X minutes"),
        ],
        "📢 Announcements": [
            ("/announce", "Post a formatted embed to any channel"),
            ("/dm_blast", "DM all members with a message (Admin)"),
            ("/schedule_announcement", "Schedule a message to post later"),
        ],
        "📊 Logging": [
            ("/set_log_channel", "Log all bot actions to a channel (Admin)"),
            ("/audit", "Show recent bot actions and who triggered them"),
        ],
        "🎭 Roles": [
            ("/set_ping_role", "Ping a role instead of @everyone (Admin)"),
            ("/autorole", "Auto-assign a role to new members (Admin)"),
            ("/role_info", "Show info about a role"),
        ],
        "⚙️ Configuration": [
            ("/set_prefix", "Change the bot prefix (Admin)"),
            ("/bot_info", "Show full bot configuration"),
            ("/reset_settings", "Reset all settings to default (Admin)"),
            ("/backup_settings", "Export all settings as JSON (Admin)"),
        ],
        "🧹 Purge": [
            ("/purge", "Bulk-delete up to 100 messages in a channel"),
        ],
        "🛡️ Anti-Raid": [
            ("/antiraid_on", "Manually enable lockdown (Admin)"),
            ("/antiraid_off", "Disable lockdown (Admin)"),
            ("/antiraid_config", "Set detection thresholds & action (Admin)"),
            ("/antiraid_status", "Show current anti-raid status"),
        ],
        "🤬 Auto-Mod": [
            ("/automod_enable", "Enable profanity filter (Admin)"),
            ("/automod_disable", "Disable profanity filter (Admin)"),
            ("/automod_addword", "Add a word to the filter (Admin)"),
            ("/automod_removeword", "Remove a word from the filter (Admin)"),
            ("/automod_status", "Show filter config and word list"),
            ("/automod_logs", "Recent violations log (Mod+)"),
            ("/strike_leaderboard", "Top users by total strikes (Mod+)"),
            ("/automod_clearstrikes", "Clear a user's strike count (Admin)"),
        ],
        "🚨 Reports": [
            ("/user_report", "Anonymously report a member with screenshot evidence"),
            ("/view_reports", "Browse reports, filter by member or status (Mod+)"),
            ("/resolve_report", "Mark a report as resolved (Mod+)"),
            ("/dismiss_report", "Dismiss a report with a reason (Mod+)"),
        ],
        "🔑 Permissions": [
            ("/set_mod_role", "Set role that can use mod commands (Admin)"),
            ("/set_admin_role", "Set role that can use admin commands (Admin)"),
            ("/sync", "Force re-sync all commands to this server (Admin)"),
        ],
        "✨ Server Management": [
            ("/setwelcome", "Set welcome channel & message (Admin)"),
            ("/verify", "Send a verification panel"),
            ("/setverifiedrole", "Set the role given by verification (Admin)"),
            ("/suggest", "Submit a suggestion"),
            ("/setsuggestchannel", "Set suggestion channel (Admin)"),
            ("/reactionrole", "Add/remove reaction roles (Admin)"),
            ("/ticket", "Create a ticket channel"),
            ("/close", "Close a ticket channel"),
            ("/giveaway", "Start a giveaway (Mod)"),
            ("/tempvc", "Create a temporary voice channel (Admin)"),
            ("/ask", "Ask the AI anything"),
        ],
    }
    for category, cmds in categories.items():
        val = "\n".join([f"`{n}` — {d}" for n,d in cmds])
        em.add_field(name=category, value=val, inline=False)
    em.set_footer(text=f"Polls every {CHECK_INTERVAL_MINUTES} min • @everyone pings {'on' if PING_EVERYONE else 'off'}")
    await interaction.response.send_message(embed=em)
"""
Roblox Update Tracker Bot — Ultimate Edition
(Complete & Working)
"""

import asyncio
import collections
import json
import logging
import os
import random
import re
import time
import typing
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
GROQ_API_KEY           = os.getenv("GROQ_API_KEY", "")

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
# Simple keyword responses (fallback)
# ---------------------------------------------------------------------------
CHAT_RESPONSES = {
    "hello": ["Hello! 👋 How can I help you today?", "Hi there! What's up?", "Hey! Need something?"],
    "hi": ["Hey! How can I assist you?", "Hi! What do you need?", "Hello! I'm here to help."],
    "how are you": ["I'm just a bunch of code, but I'm doing great! 😄", "Feeling electric! ⚡", "All systems operational!"],
    "help": ["Sure! I can track Roblox updates, moderate the server, and more. Try `!help` to see all commands.", "Need assistance? I can help with moderation, Roblox info, and server management. Just ask!", "I'm here to help! What do you need?"],
    "roblox": ["I love Roblox! I can check game status, player info, and more. Use `/game_status` or `/player_lookup`.", "Roblox is my specialty! Try `/ugc_trending` or `/latest_updates`.", "I track Roblox updates live! Want to see the latest version? Use `/roblox_version`."],
    "thanks": ["You're welcome! 😊", "No problem! Happy to help.", "Anytime!"],
    "bye": ["Goodbye! 👋", "See you later!", "Bye! Come back soon."],
    "joke": ["Why do Roblox developers never sleep? They just `wait()` for the next update! 😆", "Why did the Lua script go to therapy? Too many nil references!", "What's a developer's favorite drink? Java! ... oh wait, wrong platform."],
    "ticket": ["To create a ticket, just type `!ticket` followed by your reason (e.g., `!ticket I need help with my account`).", "Need support? Use `!ticket <reason>` and a staff member will assist you!", "I can open a ticket for you! Just say `!ticket` with your issue."],
}

FALLBACK_RESPONSES = [
    "I'm not sure I understand. Try `!help` to see what I can do.",
    "That's interesting! But I'm a Roblox tracker bot, maybe ask something Roblox related?",
    "I'm just a bot, but I'm here to help with Roblox stuff and server management.",
    "Sorry, I didn't catch that. Can you rephrase?",
    "🤖 Beep boop! That's not in my database, but I'm always learning (sort of)."
]

# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------
class RobloxBot(discord.Client):
    def __init__(self) -> None:
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
        self._filters: dict[str, bool] = {"client": True, "devforum": True, "incident": True}
        self._alert_threshold: float = 0.0
        self._last_client_version: str | None = None
        self._last_incident_id: str | None = None
        self._last_devforum_id: int | None = None
        self._last_check_time: str = "Never"
        self._client_changelog: list[dict] = []
        self._watched_items: dict[int, dict] = {}
        self._warnings: dict[str, list[dict]] = {}
        self._log_channel_id: int | None = None
        self._audit_log: list[dict] = []
        self._ping_role_id: int | None = None
        self._autorole_id: int | None = None
        self._scheduled: list[dict] = []
        self._prefix: str = "!"
        self._antiraid_enabled: bool = False
        self._antiraid_auto: bool = True
        self._antiraid_threshold: int = 10
        self._antiraid_window: int = 10
        self._antiraid_action: str = "kick"
        self._join_times: collections.deque[float] = collections.deque()
        self._mod_role_id: int | None = None
        self._admin_role_id: int | None = None
        self._automod_enabled: bool = True
        self._automod_words: list[str] = list(DEFAULT_BAD_WORDS)
        self._automod_strikes: dict[str, int] = {}
        self._automod_penalty: str = "timeout_week"
        self._automod_log: list[dict] = []
        self._reports: list[dict] = []
        self._banned_users: dict[str, dict] = {}

        # Server management extras
        self._welcome_channel_id: int | None = None
        self._welcome_message: str = "Welcome {mention} to **{server}**! Enjoy your stay."
        self._verified_role_id: int | None = None
        self._suggestion_channel_id: int | None = None
        self._reaction_roles: dict[str, dict[str, int]] = {}
        self._giveaways: dict[int, dict] = {}
        self._temp_vcs: dict[int, dict] = {}
        self._ticket_counter: int = 0

        self._load_data()
        self._cleanup_banned_users()

    # ---------- Persistence ----------
    DATA_FILE = "bot_data.json"

    def _load_data(self) -> None:
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
            self._automod_enabled    = d.get("automod_enabled", True)
            self._automod_words      = d.get("automod_words", list(DEFAULT_BAD_WORDS))
            self._automod_penalty    = d.get("automod_penalty", "timeout_week")
            self._automod_log        = d.get("automod_log", [])
            self._reports            = d.get("reports", [])
            raw_banned = d.get("banned_users", {})
            self._banned_users = {}
            for uid, data in raw_banned.items():
                data["timestamp"] = float(data.get("timestamp", 0))
                self._banned_users[uid] = data
            self._welcome_channel_id    = d.get("welcome_channel_id")
            self._welcome_message       = d.get("welcome_message", self._welcome_message)
            self._verified_role_id      = d.get("verified_role_id")
            self._suggestion_channel_id = d.get("suggestion_channel_id")
            self._reaction_roles        = d.get("reaction_roles", {})
            raw_giveaways = d.get("giveaways", {})
            self._giveaways = {}
            for mid, gdata in raw_giveaways.items():
                gdata["end_time"] = float(gdata.get("end_time", 0))
                self._giveaways[int(mid)] = gdata
            raw_tempvcs = d.get("temp_vcs", {})
            self._temp_vcs = {}
            for cid, vcdata in raw_tempvcs.items():
                vcdata["expires"] = float(vcdata.get("expires", 0))
                self._temp_vcs[int(cid)] = vcdata
            self._ticket_counter = d.get("ticket_counter", 0)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_data(self) -> None:
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
                    "watched_items":   {str(k): v for k, v in self._watched_items.items()},
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
                    "banned_users":       self._banned_users,
                    "welcome_channel_id": self._welcome_channel_id,
                    "welcome_message":    self._welcome_message,
                    "verified_role_id":   self._verified_role_id,
                    "suggestion_channel_id": self._suggestion_channel_id,
                    "reaction_roles":     self._reaction_roles,
                    "giveaways":          self._giveaways,
                    "temp_vcs":           self._temp_vcs,
                    "ticket_counter":     self._ticket_counter,
                }, f, indent=2)
        except Exception as e:
            log.warning("Failed to save data: %s", e)

    def _cleanup_banned_users(self) -> None:
        now = time.time()
        expired = [uid for uid, data in self._banned_users.items()
                   if now - data.get("timestamp", 0) > 7 * 24 * 3600]
        for uid in expired:
            del self._banned_users[uid]
        if expired:
            self._save_data()

    def _add_audit(self, action: str, user: discord.User | discord.Member, detail: str = "") -> None:
        self._audit_log.append({
            "time":   datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "action": action,
            "by":     f"{user} ({user.id})",
            "detail": detail,
        })
        self._audit_log = self._audit_log[-200:]
        self._save_data()

    async def _log_action(self, embed: discord.Embed) -> None:
        if self._log_channel_id:
            ch = self.get_channel(self._log_channel_id)
            if isinstance(ch, discord.abc.Messageable):
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass

    # ---------- HTTP helpers ----------
    async def _session_(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers={"User-Agent": "RobloxUpdateBot/3.0"})
        return self._session

    async def _json(self, url: str) -> typing.Any:
        s = await self._session_()
        try:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
        except Exception as e:
            log.warning("fetch_json %s: %s", url, e)
        return None

    async def _text(self, url: str) -> str | None:
        s = await self._session_()
        try:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return await r.text()
        except Exception as e:
            log.warning("fetch_text %s: %s", url, e)
        return None

    # ---------- Data fetchers ----------
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

    # ---------- Loops ----------
    @tasks.loop(minutes=5)
    async def rotate_presence(self) -> None:
        cv = self._last_client_version or "unknown"
        label, atype = PRESENCE_ACTIVITIES[self._presence_index % len(PRESENCE_ACTIVITIES)]
        await self.change_presence(activity=discord.Activity(type=atype, name=label.replace("{client}", cv)))
        self._presence_index += 1

    @rotate_presence.before_loop
    async def before_presence(self): await self.wait_until_ready()

    @tasks.loop(minutes=30)
    async def poll_ugc_prices(self) -> None:
        if not self._watched_items:
            return
        channel = self.get_channel(self.update_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
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
            em.add_field(name="Change", value=f"{'+' if change>0 else ''}{change:,} ({pct:+.1f}%)", inline=True)
            em.set_footer(text="Roblox Economy Tracker")
            ping_content = ""
            if PING_EVERYONE:
                guild = channel.guild if isinstance(channel, discord.TextChannel) else None
                if guild and self._ping_role_id:
                    role = guild.get_role(self._ping_role_id)
                    ping_content = f"{role.mention}\n" if role else "@everyone\n"
                else:
                    ping_content = "@everyone\n"
            await channel.send(content=ping_content, embed=em)
            self._watched_items[asset_id]["price"] = new_price

    @poll_ugc_prices.before_loop
    async def before_ugc(self): await self.wait_until_ready()

    @tasks.loop(seconds=30)
    async def check_scheduled(self) -> None:
        now = time.time()
        remaining = []
        for item in self._scheduled:
            if now >= item["send_at"]:
                ch = self.get_channel(item["channel_id"])
                if isinstance(ch, discord.abc.Messageable):
                    em = discord.Embed(
                        title=item.get("title", "📢 Announcement"),
                        description=item["message"],
                        colour=0x4cc9f0, timestamp=datetime.now(timezone.utc),
                    )
                    em.set_footer(text=f"Scheduled by {item['author']}")
                    try: await ch.send(embed=em)
                    except Exception as e: log.warning("Scheduled announcement failed: %s", e)
            else:
                remaining.append(item)
        if len(remaining) != len(self._scheduled):
            self._scheduled = remaining
            self._save_data()
        self._cleanup_banned_users()

    @check_scheduled.before_loop
    async def before_scheduled(self): await self.wait_until_ready()

    # ---------- Events ----------
    async def on_member_join(self, member: discord.Member) -> None:
        now = time.time()
        self._join_times.append(now)
        while self._join_times and self._join_times[0] < now - self._antiraid_window:
            self._join_times.popleft()
        if (self._antiraid_auto and not self._antiraid_enabled
                and len(self._join_times) >= self._antiraid_threshold):
            self._antiraid_enabled = True
            log.warning("Anti-raid triggered! %d joins in %ds", len(self._join_times), self._antiraid_window)
            alert_em = discord.Embed(
                title="🚨 ANTI-RAID LOCKDOWN TRIGGERED",
                description=f"**{len(self._join_times)} members** joined in **{self._antiraid_window}s** – lockdown activated!\nAction: **{self._antiraid_action.upper()}**\nUse `/antiraid_off` to disable.",
                colour=0xe63946, timestamp=datetime.now(timezone.utc),
            )
            await self._log_action(alert_em)
            if self._log_channel_id:
                ch = self.get_channel(self._log_channel_id)
                if isinstance(ch, discord.abc.Messageable):
                    try: await ch.send("@here", embed=alert_em)
                    except Exception: pass
        if self._antiraid_enabled:
            try:
                reason = "Anti-raid lockdown — bot-enforced"
                if self._antiraid_action == "ban":
                    await member.ban(reason=reason, delete_message_days=0)
                else:
                    await member.kick(reason=reason)
                action_em = discord.Embed(
                    title=f"🛡️ Anti-Raid: Member {'Banned' if self._antiraid_action == 'ban' else 'Kicked'}",
                    colour=0xe63946, timestamp=datetime.now(timezone.utc),
                )
                action_em.add_field(name="Member", value=f"{member} ({member.id})", inline=True)
                action_em.add_field(name="Action", value=self._antiraid_action.title(), inline=True)
                await self._log_action(action_em)
            except Exception as e: log.warning("Anti-raid action failed for %s: %s", member, e)
            return
        if self._autorole_id:
            role = member.guild.get_role(self._autorole_id)
            if role:
                try:
                    await member.add_roles(role, reason="Auto-role on join")
                    em = discord.Embed(title="👋 Member Joined — Auto-role Applied", colour=0x06d6a0, timestamp=datetime.now(timezone.utc))
                    em.add_field(name="Member", value=f"{member.mention} ({member})", inline=True)
                    em.add_field(name="Role", value=role.mention, inline=True)
                    await self._log_action(em)
                except Exception as e: log.warning("Auto-role failed for %s: %s", member, e)
        if self._welcome_channel_id and self._welcome_message:
            ch = member.guild.get_channel(self._welcome_channel_id)
            if isinstance(ch, discord.TextChannel):
                msg = self._welcome_message.format(mention=member.mention, server=member.guild.name, user=member.display_name)
                try: await ch.send(msg)
                except discord.Forbidden: pass

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if str(payload.message_id) in self._reaction_roles:
            guild = self.get_guild(payload.guild_id) if payload.guild_id else None
            if not guild: return
            member = payload.member
            if not member or member.bot: return
            emoji = str(payload.emoji)
            roles = self._reaction_roles[str(payload.message_id)]
            if emoji in roles:
                role = guild.get_role(roles[emoji])
                if role:
                    try: await member.add_roles(role)
                    except discord.Forbidden: pass

    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if str(payload.message_id) in self._reaction_roles:
            guild = self.get_guild(payload.guild_id) if payload.guild_id else None
            if not guild: return
            member = guild.get_member(payload.user_id)
            if not member or member.bot: return
            emoji = str(payload.emoji)
            roles = self._reaction_roles[str(payload.message_id)]
            if emoji in roles:
                role = guild.get_role(roles[emoji])
                if role:
                    try: await member.remove_roles(role)
                    except discord.Forbidden: pass

    # ---------- Core message handler (auto-mod + prefix) ----------
    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return

        # DM handling
        if message.guild is None:
            content = message.content.strip().lower()
            if content == "!ticket" or content == "/ticket" or content.startswith("!ticket ") or content.startswith("/ticket "):
                reason = "No reason provided"
                if content.startswith("!ticket "): reason = message.content[len("!ticket "):].strip()
                elif content.startswith("/ticket "): reason = message.content[len("/ticket "):].strip()
                user = message.author
                mutual_guilds = [g for g in self.guilds if g.get_member(user.id)]
                if not mutual_guilds:
                    await message.channel.send("❌ You don't share any server with me.")
                    return
                guild = mutual_guilds[0]
                self._ticket_counter += 1
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                    guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                }
                if self._mod_role_id:
                    mod_role = guild.get_role(self._mod_role_id)
                    if mod_role: overwrites[mod_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                if self._admin_role_id:
                    admin_role = guild.get_role(self._admin_role_id)
                    if admin_role: overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                category = discord.utils.get(guild.categories, name="Tickets")
                if not category:
                    try: category = await guild.create_category("Tickets")
                    except discord.Forbidden:
                        await message.channel.send("❌ I can't create a category.")
                        return
                try:
                    ticket_ch = await guild.create_text_channel(
                        name=f"ticket-{self._ticket_counter}", category=category, overwrites=overwrites
                    )
                except discord.Forbidden:
                    await message.channel.send("❌ I can't create a channel.")
                    return
                em = discord.Embed(title="📩 Ticket Created", description=f"Hello {user.mention}, your ticket has been created.\nReason: {reason}\nUse `/close` to close.", colour=0x4cc9f0)
                await ticket_ch.send(embed=em)
                self._save_data()
                await message.channel.send(f"✅ Ticket created in **{guild.name}**! Channel: {ticket_ch.mention}")
                return
            else:
                response = await self._chat_with_llm(message.content)
                if response is None:
                    response = self._get_chat_response(message.content)
                await message.channel.send(response)
                return

        # Guild messages
        if not message.guild or message.author.bot:
            return

        # Auto-mod
        if self._automod_enabled and isinstance(message.author, discord.Member):
            content = message.content
            if content:
                normalized = _normalize(content)
                triggered_word = next((w for w in self._automod_words if w in normalized), None)
                if triggered_word:
                    try: await message.delete()
                    except Exception: pass
                    uid = str(message.author.id)
                    self._automod_strikes[uid] = self._automod_strikes.get(uid, 0) + 1
                    strikes = self._automod_strikes[uid]
                    import datetime as dt
                    member = message.author
                    try:
                        if strikes >= 3:
                            if self._automod_penalty == "kick":
                                await member.kick(reason=f"Auto-mod: repeated profanity ({strikes} strikes)")
                                action_text = "**Kicked** from the server"
                                self._automod_strikes[uid] = 0
                            else:
                                until = discord.utils.utcnow() + dt.timedelta(days=7)
                                await member.timeout(until, reason=f"Auto-mod: repeated profanity ({strikes} strikes)")
                                action_text = "**Timed out for 7 days**"
                            color = 0xe63946
                        else:
                            until = discord.utils.utcnow() + dt.timedelta(minutes=10)
                            await member.timeout(until, reason=f"Auto-mod: profanity (strike {strikes}/3)")
                            action_text = "**Timed out for 10 minutes**"
                            color = 0xffd166
                    except discord.Forbidden:
                        action_text = "⚠️ Could not punish (missing permissions)"
                        color = 0xaaaaaa
                    warn_em = discord.Embed(
                        title="🤬 Language Warning",
                        description=f"{member.mention} your message was removed.\nStrike **{strikes}/3** — {action_text}.",
                        colour=color, timestamp=datetime.now(timezone.utc),
                    )
                    warn_em.set_footer(text="3 strikes = kick or 7-day timeout")
                    try: await message.channel.send(embed=warn_em, delete_after=15)
                    except Exception: pass
                    log_em = discord.Embed(title="🤬 Auto-mod: Profanity Detected", colour=color, timestamp=datetime.now(timezone.utc))
                    log_em.add_field(name="Member", value=f"{member} ({member.id})", inline=True)
                    log_em.add_field(name="Strikes", value=f"{strikes}/3", inline=True)
                    log_em.add_field(name="Action", value=action_text, inline=True)
                    log_em.add_field(name="Channel", value=message.channel.mention, inline=True)
                    await self._log_action(log_em)
                    self._automod_log.append({
                        "ts": datetime.now(timezone.utc).isoformat(), "user": f"{member} ({member.id})",
                        "uid": str(member.id), "word": triggered_word, "strikes": strikes,
                        "action": action_text, "channel": str(message.channel),
                    })
                    self._automod_log = self._automod_log[-100:]
                    self._save_data()
                    return

        # Prefix commands
        if not message.content.startswith(self._prefix):
            return
        cmd, *args = message.content[len(self._prefix):].split()
        cmd = cmd.lower()
        channel = message.channel
        author = message.author
        guild = message.guild

        async def send_embed(title, description, color=0x4cc9f0):
            em = discord.Embed(title=title, description=description, colour=color)
            await channel.send(embed=em)

        def is_mod():
            return (author.guild_permissions.administrator or
                    (self._mod_role_id and guild.get_role(self._mod_role_id) in author.roles) or
                    (self._admin_role_id and guild.get_role(self._admin_role_id) in author.roles) or
                    author.guild_permissions.manage_messages or author.guild_permissions.kick_members or
                    author.guild_permissions.ban_members or author.guild_permissions.moderate_members)

        def is_admin():
            return (author.guild_permissions.administrator or
                    (self._admin_role_id and guild.get_role(self._admin_role_id) in author.roles))

        # ---- Moderation ----
        if cmd == "kick":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}kick @member [reason]")
            member = await self._get_member_from_mention(guild, args[0])
            if not member: return await send_embed("❌ Error", "Member not found.")
            reason = " ".join(args[1:]) if len(args) > 1 else "No reason provided"
            anon = "-a" in args or "--anonymous" in args
            if anon: reason = reason.replace("-a", "").replace("--anonymous", "").strip()
            try:
                dm_content = f"You have been **kicked** from **{guild.name}**.\nReason: {reason}" if anon else f"You have been **kicked** from **{guild.name}** by {author.mention}.\nReason: {reason}"
                try: await member.send(dm_content)
                except discord.Forbidden: pass
                await member.kick(reason=reason)
                await send_embed("👢 Member Kicked", f"{member} kicked.\nReason: {reason}")
            except discord.Forbidden: await send_embed("❌ Error", "I don't have permission to kick that member.", 0xe63946)

        elif cmd == "ban":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}ban @member [reason]")
            member = await self._get_member_from_mention(guild, args[0])
            if not member: return await send_embed("❌ Error", "Member not found.")
            reason = " ".join(args[1:]) if len(args) > 1 else "No reason provided"
            anon = "-a" in args or "--anonymous" in args
            if anon: reason = reason.replace("-a", "").replace("--anonymous", "").strip()
            try:
                dm_content = f"You have been **banned** from **{guild.name}**.\nReason: {reason}" if anon else f"You have been **banned** from **{guild.name}** by {author.mention}.\nReason: {reason}"
                try: await member.send(dm_content)
                except discord.Forbidden: pass
                await member.ban(reason=reason, delete_message_days=0)
                self._banned_users[str(member.id)] = {
                    "user": str(member), "reason": reason,
                    "banned_by": "Anonymous" if anon else str(author), "timestamp": time.time()
                }
                self._save_data()
                await send_embed("🔨 Member Banned", f"{member} banned.\nReason: {reason}")
            except discord.Forbidden: await send_embed("❌ Error", "I don't have permission to ban that member.", 0xe63946)

        elif cmd == "unban":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}unban <user_id>")
            user_id = args[0]
            try:
                user = await self.fetch_user(int(user_id))
                await guild.unban(user, reason=f"Unbanned by {author}")
                if user_id in self._banned_users:
                    del self._banned_users[user_id]
                    self._save_data()
                await send_embed("🔓 Unbanned", f"Unbanned {user}")
            except discord.NotFound: await send_embed("❌ Error", "User not found in ban list.", 0xe63946)
            except discord.Forbidden: await send_embed("❌ Error", "I don't have permission to unban.", 0xe63946)

        elif cmd == "timeout":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            if len(args) < 2: return await send_embed("Usage", f"{self._prefix}timeout @member <minutes> [reason]")
            member = await self._get_member_from_mention(guild, args[0])
            if not member: return await send_embed("❌ Error", "Member not found.")
            try: minutes = int(args[1])
            except ValueError: return await send_embed("❌ Error", "Minutes must be a number.")
            reason = " ".join(args[2:]) if len(args) > 2 else "No reason provided"
            until = discord.utils.utcnow() + __import__("datetime").timedelta(minutes=minutes)
            try:
                await member.timeout(until, reason=reason)
                await send_embed("⏱️ Timed Out", f"{member} timed out for {minutes} min.\nReason: {reason}")
            except discord.Forbidden: await send_embed("❌ Error", "I don't have permission to timeout that member.", 0xe63946)

        elif cmd == "warn":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            if len(args) < 2: return await send_embed("Usage", f"{self._prefix}warn @member <reason>")
            member = await self._get_member_from_mention(guild, args[0])
            if not member: return await send_embed("❌ Error", "Member not found.")
            reason = " ".join(args[1:])
            uid = str(member.id)
            entry = {"reason": reason, "by": str(author), "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
            self._warnings.setdefault(uid, []).append(entry)
            self._save_data()
            await send_embed("⚠️ Warned", f"{member} warned: {reason}")

        elif cmd == "warnings":
            if len(args) < 1: member = author
            else: member = await self._get_member_from_mention(guild, args[0])
            if not member: return await send_embed("❌ Error", "Member not found.")
            uid = str(member.id)
            warns = self._warnings.get(uid, [])
            if not warns: return await send_embed("✅ No warnings", f"{member} has no warnings.")
            em = discord.Embed(title=f"Warnings for {member}", colour=0xffd166)
            for i, w in enumerate(warns, 1):
                em.add_field(name=f"#{i} - {w['time']}", value=f"Reason: {w['reason']}\nBy: {w['by']}", inline=False)
            await channel.send(embed=em)

        elif cmd == "clearwarnings":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}clearwarnings @member")
            member = await self._get_member_from_mention(guild, args[0])
            if not member: return await send_embed("❌ Error", "Member not found.")
            uid = str(member.id)
            count = len(self._warnings.pop(uid, []))
            self._save_data()
            await send_embed("✅ Warnings Cleared", f"Cleared {count} warnings for {member}")

        elif cmd == "bannedlist":
            self._cleanup_banned_users()
            if not self._banned_users: return await send_embed("📜 Banned List", "No users banned recently.")
            entries = sorted(self._banned_users.values(), key=lambda x: x["timestamp"], reverse=True)
            em = discord.Embed(title="Recently Banned Users", colour=0xff6b35)
            for entry in entries[:10]:
                ts = int(entry["timestamp"])
                em.add_field(name=entry["user"], value=f"Reason: {entry['reason']}\nBanned by: {entry['banned_by']}\nWhen: <t:{ts}:R>", inline=False)
            await channel.send(embed=em)

        # ---- Utility ----
        elif cmd == "purge":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}purge <amount>")
            try: amount = int(args[0])
            except ValueError: return await send_embed("❌ Error", "Amount must be a number.")
            if not 1 <= amount <= 100: return await send_embed("❌ Error", "Amount must be between 1 and 100.")
            await message.delete()
            deleted = await channel.purge(limit=amount)
            await channel.send(f"🗑️ Deleted {len(deleted)} messages.", delete_after=5)

        elif cmd == "announce":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            try:
                parts = message.content[len(self._prefix)+len("announce "):].split("|", 1)
                title = parts[0].strip()
                message_body = parts[1].strip() if len(parts) > 1 else ""
            except Exception: return await send_embed("Usage", f"{self._prefix}announce Title | Message")
            em = discord.Embed(title=title, description=message_body, colour=0x4cc9f0)
            await channel.send(embed=em)
            await message.delete()

        elif cmd == "poll":
            try:
                regex = re.findall(r'"([^"]*)"', message.content)
                if len(regex) < 3: return await send_embed("Usage", f'{self._prefix}poll "Question" "Option A" "Option B"')
                question, opt_a, opt_b = regex[0], regex[1], regex[2]
                em = discord.Embed(title=f"📊 {question}", colour=0x4cc9f0)
                em.add_field(name="🅰️", value=opt_a, inline=True)
                em.add_field(name="🅱️", value=opt_b, inline=True)
                msg = await channel.send(embed=em)
                await msg.add_reaction("🅰️")
                await msg.add_reaction("🅱️")
                await message.delete()
            except Exception as e: await send_embed("Error", str(e))

        # ---- Server Management ----
        elif cmd == "setwelcome":
            if not is_admin(): return await send_embed("❌ Permission Denied", "You need admin permissions.", 0xe63946)
            try:
                params = " ".join(args)
                if "|" in params:
                    ch_str, msg_part = params.split("|", 1)
                    ch = await self._get_channel_from_mention(guild, ch_str.strip())
                    if ch: self._welcome_channel_id = ch.id
                    else: return await send_embed("❌ Error", "Invalid channel.")
                    self._welcome_message = msg_part.strip()
                else:
                    self._welcome_message = params
                self._save_data()
                await send_embed("✅ Welcome Message Set", f"Channel: {f'<#{self._welcome_channel_id}>' if self._welcome_channel_id else 'current'}\nMessage: {self._welcome_message}")
            except Exception as e: await send_embed("Error", str(e))

        elif cmd == "setverifiedrole":
            if not is_admin(): return await send_embed("❌ Permission Denied", "You need admin permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}setverifiedrole @role")
            role = await self._get_role_from_mention(guild, args[0])
            if not role: return await send_embed("❌ Error", "Role not found.")
            self._verified_role_id = role.id
            self._save_data()
            await send_embed("✅ Verified Role Set", f"Verified role: {role.mention}")

        elif cmd == "setsuggest":
            if not is_admin(): return await send_embed("❌ Permission Denied", "You need admin permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}setsuggest #channel")
            ch = await self._get_channel_from_mention(guild, args[0])
            if not ch: return await send_embed("❌ Error", "Channel not found.")
            self._suggestion_channel_id = ch.id
            self._save_data()
            await send_embed("✅ Suggestion Channel Set", f"Suggestions will go to {ch.mention}")

        elif cmd == "suggest":
            if not self._suggestion_channel_id: return await send_embed("❌ Error", "Suggestion channel not configured.")
            suggestion_ch = guild.get_channel(self._suggestion_channel_id)
            if not suggestion_ch or not isinstance(suggestion_ch, discord.TextChannel):
                return await send_embed("❌ Error", "Suggestion channel not found.")
            text = " ".join(args)
            if not text: return await send_embed("Usage", f"{self._prefix}suggest <your suggestion>")
            em = discord.Embed(description=text, colour=0x9b5de5, timestamp=datetime.now(timezone.utc))
            em.set_author(name=f"Suggestion by {author.display_name}", icon_url=author.display_avatar.url)
            msg = await suggestion_ch.send(embed=em)
            await msg.add_reaction("👍")
            await msg.add_reaction("👎")
            await send_embed("✅ Suggestion Sent", f"Your suggestion has been posted in {suggestion_ch.mention}")
            try: await message.delete()
            except Exception: pass

        elif cmd == "verify":
            if not self._verified_role_id: return await send_embed("❌ Error", "Verified role not set. Admins use `!setverifiedrole`.")
            role = guild.get_role(self._verified_role_id)
            if not role: return await send_embed("❌ Error", "Verified role not found.")
            view = discord.ui.View()
            btn = discord.ui.Button(label="Verify", style=discord.ButtonStyle.green)
            async def verify_callback(interaction: discord.Interaction):
                if role in interaction.user.roles:
                    await interaction.response.send_message("You are already verified.", ephemeral=True)
                    return
                try:
                    await interaction.user.add_roles(role)
                    await interaction.response.send_message("✅ You are now verified!", ephemeral=True)
                except discord.Forbidden:
                    await interaction.response.send_message("❌ I can't assign roles.", ephemeral=True)
            btn.callback = verify_callback
            view.add_item(btn)
            em = discord.Embed(title="Verification", description="Click the button below to verify yourself.", colour=0x06d6a0)
            await channel.send(embed=em, view=view)
            await message.delete()

        elif cmd == "reactionrole":
            if not is_admin(): return await send_embed("❌ Permission Denied", "You need admin permissions.", 0xe63946)
            if len(args) < 2: return await send_embed("Usage", f"{self._prefix}reactionrole add <channel> <message_id> <emoji> <role>\n{self._prefix}reactionrole remove <message_id> <emoji>")
            action = args[0].lower()
            if action == "add":
                if len(args) < 5: return await send_embed("Usage", f"{self._prefix}reactionrole add <channel> <message_id> <emoji> <role>")
                ch = await self._get_channel_from_mention(guild, args[1])
                if not ch: return await send_embed("❌ Error", "Invalid channel.")
                try: msg_id = int(args[2])
                except ValueError: return await send_embed("❌ Error", "Message ID must be a number.")
                emoji = args[3]
                role = await self._get_role_from_mention(guild, args[4])
                if not role: return await send_embed("❌ Error", "Role not found.")
                msg = await ch.fetch_message(msg_id)
                try: await msg.add_reaction(emoji)
                except Exception: return await send_embed("❌ Error", "Cannot add that emoji.")
                self._reaction_roles.setdefault(str(msg_id), {})[emoji] = role.id
                self._save_data()
                await send_embed("✅ Reaction Role Added", f"React with {emoji} to get {role.mention}")
            elif action == "remove":
                if len(args) < 3: return await send_embed("Usage", f"{self._prefix}reactionrole remove <message_id> <emoji>")
                try: msg_id = int(args[1])
                except ValueError: return await send_embed("❌ Error", "Message ID must be a number.")
                emoji = args[2]
                if str(msg_id) in self._reaction_roles and emoji in self._reaction_roles[str(msg_id)]:
                    del self._reaction_roles[str(msg_id)][emoji]
                    if not self._reaction_roles[str(msg_id)]:
                        del self._reaction_roles[str(msg_id)]
                    self._save_data()
                    await send_embed("✅ Removed", f"Reaction role removed for emoji {emoji}")
                else: await send_embed("❌ Error", "That reaction role does not exist.")
            else: await send_embed("❌ Error", "Unknown action. Use `add` or `remove`.")

        elif cmd == "ticket":
            reason = " ".join(args) if args else "No reason specified"
            self._ticket_counter += 1
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                author: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            if self._mod_role_id:
                mod_role = guild.get_role(self._mod_role_id)
                if mod_role: overwrites[mod_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            if self._admin_role_id:
                admin_role = guild.get_role(self._admin_role_id)
                if admin_role: overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            category = discord.utils.get(guild.categories, name="Tickets")
            if not category:
                try: category = await guild.create_category("Tickets")
                except discord.Forbidden: return await send_embed("❌ Error", "I can't create a category.")
            try:
                ticket_ch = await guild.create_text_channel(
                    name=f"ticket-{self._ticket_counter}", category=category, overwrites=overwrites
                )
            except discord.Forbidden: return await send_embed("❌ Error", "I can't create channels.")
            em = discord.Embed(title="📩 Ticket Created", description=f"Hello {author.mention}, your ticket has been created.\nReason: {reason}\nStaff will assist you soon.\nType `{self._prefix}close` to close.", colour=0x4cc9f0)
            await ticket_ch.send(embed=em)
            self._save_data()
            await send_embed("✅ Ticket Created", f"Your ticket channel: {ticket_ch.mention}")

        elif cmd == "close":
            if not isinstance(channel, discord.TextChannel) or not channel.name.startswith("ticket-"):
                return await send_embed("❌ Error", "This is not a ticket channel.")
            try: await channel.delete(reason="Ticket closed.")
            except discord.Forbidden: await send_embed("❌ Error", "I don't have permission to delete this channel.")

        elif cmd == "giveaway":
            if not is_mod(): return await send_embed("❌ Permission Denied", "You need moderator permissions.", 0xe63946)
            try:
                full = " ".join(args)
                parts = full.split("|")
                prize = parts[0].strip()
                duration_min = int(parts[1].strip())
                winners = int(parts[2].strip())
            except Exception: return await send_embed("Usage", f"{self._prefix}giveaway Prize | DurationMinutes | Winners")
            if duration_min < 1: return await send_embed("❌ Error", "Duration must be at least 1 minute.")
            end_time = time.time() + duration_min * 60
            em = discord.Embed(title="🎉 Giveaway!", description=f"**Prize:** {prize}\nReact with 🎉 to enter!\nEnds: <t:{int(end_time)}:R>", colour=0xf72585)
            msg = await channel.send(embed=em)
            await msg.add_reaction("🎉")
            self._giveaways[msg.id] = {"prize": prize, "end_time": end_time, "winners": winners, "channel_id": channel.id}
            self._save_data()

        elif cmd == "tempvc":
            if not is_admin(): return await send_embed("❌ Permission Denied", "You need admin permissions.", 0xe63946)
            if len(args) < 2: return await send_embed("Usage", f"{self._prefix}tempvc create <name> <duration_minutes>")
            action = args[0].lower()
            if action != "create": return await send_embed("Usage", f"{self._prefix}tempvc create <name> <duration_minutes>")
            try:
                name = " ".join(args[1:-1])
                minutes = int(args[-1])
            except ValueError: return await send_embed("❌ Error", "Duration must be a number.")
            if minutes < 1: return await send_embed("❌ Error", "Duration must be at least 1 minute.")
            try:
                vc = await guild.create_voice_channel(name)
                self._temp_vcs[vc.id] = {"expires": time.time() + minutes * 60, "creator_id": author.id}
                self._save_data()
                await send_embed("🎤 Temporary VC Created", f"{vc.mention} will be deleted in {minutes} min.")
            except discord.Forbidden: await send_embed("❌ Error", "I can't create voice channels.")

        elif cmd == "help":
            em = discord.Embed(title="Bot Help", description=f"Prefix: `{self._prefix}`\nUse slash commands for more features.", colour=0x4cc9f0)
            em.add_field(name="Moderation", value="kick, ban, unban, timeout, warn, warnings, clearwarnings, bannedlist, purge", inline=False)
            em.add_field(name="Server Management", value="setwelcome, verify, suggest, reactionrole, ticket, giveaway, tempvc", inline=False)
            em.add_field(name="Other", value="announce, poll, setprefix, stats, ask", inline=False)
            await channel.send(embed=em)

        elif cmd == "setprefix":
            if not is_admin(): return await send_embed("❌ Permission Denied", "You need admin permissions.", 0xe63946)
            if len(args) < 1: return await send_embed("Usage", f"{self._prefix}setprefix <new_prefix>")
            new_prefix = args[0]
            if len(new_prefix) > 5: return await send_embed("❌ Error", "Prefix must be 5 characters or fewer.")
            self._prefix = new_prefix
            self._save_data()
            await send_embed("✅ Prefix Changed", f"Prefix set to `{self._prefix}`")

        elif cmd == "stats":
            em = discord.Embed(title="Bot Stats", colour=0x4cc9f0)
            em.add_field(name="Commands Used", value=str(self._command_uses))
            em.add_field(name="Prefix", value=self._prefix)
            await channel.send(embed=em)

        elif cmd == "ask":
            question = " ".join(args)
            async with channel.typing():
                response = await self._chat_with_llm(question)
                if response is None: response = self._get_chat_response(question)
                await channel.send(response)

        else:
            # unknown command → LLM
            async with channel.typing():
                response = await self._chat_with_llm(message.content[len(self._prefix):])
                if response is None: response = self._get_chat_response(message.content[len(self._prefix):])
                await channel.send(response)

    # ---------- LLM integration ----------
    async def _chat_with_llm(self, user_message: str) -> str | None:
        if not GROQ_API_KEY:
            return None
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": "You are a friendly Discord bot. Be concise, fun, and helpful."},
                {"role": "user", "content": user_message}
            ],
            "max_tokens": 150,
            "temperature": 0.7
        }
        try:
            s = await self._session_()
            async with s.post(url, json=payload, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    log.warning("Groq API error: %s", resp.status)
                    return None
        except Exception as e:
            log.warning("Groq API call failed: %s", e)
            return None

    def _get_chat_response(self, message: str) -> str:
        msg = message.lower().strip()
        for keyword, responses in CHAT_RESPONSES.items():
            if keyword in msg:
                return random.choice(responses)
        return random.choice(FALLBACK_RESPONSES)

    async def _get_member_from_mention(self, guild: discord.Guild, mention: str) -> discord.Member | None:
        if mention.startswith("<@") and mention.endswith(">"):
            try:
                member_id = int(mention.strip("<@!>"))
                return guild.get_member(member_id) or await guild.fetch_member(member_id)
            except Exception: pass
        return None

    async def _get_role_from_mention(self, guild: discord.Guild, mention: str) -> discord.Role | None:
        if mention.startswith("<@&") and mention.endswith(">"):
            try:
                role_id = int(mention.strip("<@&>"))
                return guild.get_role(role_id)
            except Exception: pass
        return None

    async def _get_channel_from_mention(self, guild: discord.Guild, mention: str) -> discord.TextChannel | None:
        if mention.startswith("<#") and mention.endswith(">"):
            try:
                channel_id = int(mention.strip("<#>"))
                ch = guild.get_channel(channel_id)
                if isinstance(ch, discord.TextChannel): return ch
            except Exception: pass
        return None

    # ---------- Background tasks ----------
    @tasks.loop(seconds=15)
    async def check_giveaways(self) -> None:
        now = time.time()
        expired = []
        for msg_id, gdata in list(self._giveaways.items()):
            if now >= gdata["end_time"]:
                expired.append(msg_id)
                channel = self.get_channel(gdata["channel_id"])
                if not isinstance(channel, discord.TextChannel): continue
                try: message = await channel.fetch_message(msg_id)
                except discord.NotFound: continue
                reaction = discord.utils.get(message.reactions, emoji="🎉")
                users = []
                if reaction:
                    async for user in reaction.users():
                        if not user.bot: users.append(user)
                winners_needed = min(gdata["winners"], len(users))
                winners = random.sample(users, winners_needed) if winners_needed > 0 else []
                winner_mentions = ", ".join(w.mention for w in winners) if winners else "No one"
                em = discord.Embed(title="🎉 Giveaway Ended!", description=f"**Prize:** {gdata['prize']}\n**Winners:** {winner_mentions}", colour=0x06d6a0)
                await channel.send(embed=em)
                del self._giveaways[msg_id]
        if expired: self._save_data()

    @tasks.loop(seconds=30)
    async def check_tempvcs(self) -> None:
        now = time.time()
        to_delete = [cid for cid, vcdata in self._temp_vcs.items() if now >= vcdata["expires"]]
        for cid in to_delete:
            vc = self.get_channel(cid)
            if vc and isinstance(vc, discord.VoiceChannel):
                try: await vc.delete()
                except discord.Forbidden: pass
            del self._temp_vcs[cid]
        if to_delete: self._save_data()

    @check_giveaways.before_loop
    async def before_giveaways(self): await self.wait_until_ready()

    @check_tempvcs.before_loop
    async def before_tempvcs(self): await self.wait_until_ready()

    # ---------- Main update polling ----------
    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def poll_updates(self) -> None:
        self._last_check_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if time.time() < self._muted_until: return
        channel = self.get_channel(self.update_channel_id)
        if not isinstance(channel, discord.abc.Messageable): return
        ping_content = ""
        if PING_EVERYONE:
            guild = channel.guild if isinstance(channel, discord.TextChannel) else None
            if guild and self._ping_role_id:
                role = guild.get_role(self._ping_role_id)
                ping_content = f"{role.mention}\n" if role else "@everyone\n"
            else: ping_content = "@everyone\n"
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
                        title="🚨 Roblox Update Detected!", description="This is a live update, Roblox is **patched**.",
                        colour=0xe63946, timestamp=now,
                    )
                    em.add_field(name="Platform", value="Windows", inline=False)
                    em.add_field(name="Version Hash", value=f"`{cv}`", inline=False)
                    em.add_field(name="Date", value=ts, inline=False)
                    em.set_footer(text=date_str)
                    await channel.send(content=ping_content, embed=em)
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
                        await channel.send(content=ping_content, embed=em)
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
                        await channel.send(content=ping_content, embed=em)
                    self._last_incident_id = latest_inc["id"]

    @poll_updates.before_loop
    async def before_poll(self): await self.wait_until_ready()

    # ---------- Setup & Ready ----------
    async def setup_hook(self) -> None:
        self.poll_updates.start()
        self.rotate_presence.start()
        self.poll_ugc_prices.start()
        self.check_scheduled.start()
        self.check_giveaways.start()
        self.check_tempvcs.start()

    async def on_ready(self) -> None:
        if not self.user: return
        self._start_time = time.time()
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                log.info("Synced commands to guild %s (%s)", guild.name, guild.id)
            except Exception as e:
                log.warning("Failed to sync to guild %s: %s", guild.id, e)
        channel = self.get_channel(self.update_channel_id)
        if isinstance(channel, discord.abc.Messageable):
            cv = await self.get_client_version()
            em = discord.Embed(
                title="🚀 Roblox Update Tracker — Online",
                description="Bot is online and monitoring for updates!",
                colour=0x4cc9f0, timestamp=datetime.now(timezone.utc),
            )
            em.add_field(name="🎮 Client", value=f"`{cv or 'N/A'}`", inline=True)
            em.set_footer(text=f"Polling every {CHECK_INTERVAL_MINUTES} min")
            await channel.send(embed=em)


# ============================================================================
# Instantiate bot
# ============================================================================
bot = RobloxBot()

# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------
def mod_check() -> typing.Callable:
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not interaction.guild:
            raise app_commands.CheckFailure("Not in a guild or not a Member")
        m = interaction.user
        if m.guild_permissions.administrator: return True
        if bot._admin_role_id:
            r = interaction.guild.get_role(bot._admin_role_id)
            if r and r in m.roles: return True
        if bot._mod_role_id:
            r = interaction.guild.get_role(bot._mod_role_id)
            if r and r in m.roles: return True
        if m.guild_permissions.manage_messages or m.guild_permissions.kick_members \
                or m.guild_permissions.ban_members or m.guild_permissions.moderate_members:
            return True
        raise app_commands.MissingPermissions(["manage_messages"])
    return app_commands.check(predicate)

def admin_check() -> typing.Callable:
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not interaction.guild:
            raise app_commands.CheckFailure("Not in a guild or not a Member")
        m = interaction.user
        if m.guild_permissions.administrator: return True
        if bot._admin_role_id:
            r = interaction.guild.get_role(bot._admin_role_id)
            if r and r in m.roles: return True
        raise app_commands.MissingPermissions(["administrator"])
    return app_commands.check(predicate)

@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
    else:
        log.error("Unhandled command error: %s", error)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred.", ephemeral=True)

# ============================================================================
# SLASH COMMANDS (unchanged, all here)
# ============================================================================
@bot.tree.command(name="roblox_version", description="Current live Roblox client version")
async def cmd_roblox_version(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    v = await bot.get_client_version()
    now = datetime.now(timezone.utc)
    em = discord.Embed(title="🚨 Roblox Update Info", description="Current live version from Roblox CDN.", colour=0xe63946, timestamp=now)
    em.add_field(name="Platform", value="Windows", inline=False)
    em.add_field(name="Version Hash", value=f"`{v or 'N/A'}`", inline=False)
    em.add_field(name="Date", value=now.strftime("%B %d, %Y %I:%M %p"), inline=False)
    em.set_footer(text=now.strftime("%m/%d/%Y %I:%M %p"))
    await interaction.followup.send(embed=em)

@bot.tree.command(name="latest_updates", description="Latest DevForum announcements")
async def cmd_latest_updates(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    posts = await bot.get_devforum_posts(DEVFORUM_ANNOUNCEMENTS_URL, limit=5)
    em = discord.Embed(title="📢 Latest DevForum Announcements", colour=0xffd166)
    if posts:
        for p in posts: em.add_field(name=p["title"], value=f"[Read more]({p['url']}) • {p['posts_count']} replies", inline=False)
    else: em.description = "Could not retrieve announcements right now."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="release_notes", description="Official Roblox release notes")
async def cmd_release_notes(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    posts = await bot.get_devforum_posts(DEVFORUM_RELEASES_URL, limit=5)
    em = discord.Embed(title="📋 Roblox Release Notes", colour=0x06d6a0)
    if posts:
        for p in posts: em.add_field(name=p["title"], value=f"[Read more]({p['url']}) • {p['posts_count']} replies", inline=False)
    else: em.description = "Could not retrieve release notes right now."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="upcoming_features", description="Beta & upcoming Roblox features")
async def cmd_upcoming_features(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    posts = await bot.get_devforum_posts(DEVFORUM_BETA_URL, limit=5)
    em = discord.Embed(title="🔭 Upcoming & Beta Features", colour=0x9b5de5)
    if posts:
        for p in posts: em.add_field(name=p["title"], value=f"[Read more]({p['url']}) • {p['posts_count']} replies", inline=False)
    else: em.description = "No upcoming features found right now."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="security_updates", description="Recent Roblox security patches and incidents")
async def cmd_security_updates(interaction: discord.Interaction) -> None:
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
    else: em.add_field(name="✅ No Active Incidents", value="Roblox is clean.", inline=False)
    if sec:
        em.add_field(name="━━━━━━━━━━━━━━", value="**Security DevForum Posts**", inline=False)
        for p in sec[:3]: em.add_field(name=p["title"], value=f"[Read more]({p['url']})", inline=False)
    em.set_footer(text="status.roblox.com + DevForum")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="status", description="Full Roblox platform status")
async def cmd_status(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    data = await bot.get_status_summary()
    if not data: await interaction.followup.send("❌ Could not reach status page."); return
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
async def cmd_stats(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    uptime = int(time.time() - bot._start_time)
    h, rem = divmod(uptime, 3600)
    m, s = divmod(rem, 60)
    muted = f"<t:{int(bot._muted_until)}:R>" if time.time() < bot._muted_until else "Not muted"
    em = discord.Embed(title="📊 Bot Stats", colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="⏱️ Uptime", value=f"{h}h {m}m {s}s", inline=True)
    em.add_field(name="🕐 Last Check", value=bot._last_check_time, inline=True)
    em.add_field(name="🔄 Interval", value=f"Every {CHECK_INTERVAL_MINUTES} min", inline=True)
    em.add_field(name="🎮 Client Version", value=f"`{bot._last_client_version or 'N/A'}`", inline=True)
    em.add_field(name="🔔 @everyone", value="Enabled" if PING_EVERYONE else "Disabled", inline=True)
    em.add_field(name="🔕 Muted", value=muted, inline=True)
    em.add_field(name="📋 Changelog", value=f"{len(bot._client_changelog)} entries", inline=True)
    em.add_field(name="👁️ Watched Items", value=str(len(bot._watched_items)), inline=True)
    em.add_field(name="💬 Commands Used", value=str(bot._command_uses), inline=True)
    em.add_field(name="🔍 Active Filters", value=", ".join(k for k,v in bot._filters.items() if v) or "None", inline=False)
    em.set_footer(text="Roblox Update Tracker")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="changelog", description="Last 10 detected version changes")
async def cmd_changelog(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    em = discord.Embed(title="📅 Version Changelog", colour=0xffd166, timestamp=datetime.now(timezone.utc))
    if bot._client_changelog:
        em.add_field(name="🎮 Client Updates",
                     value="\n".join([f"`{e['version']}` — {e['time']}" for e in reversed(bot._client_changelog)]),
                     inline=False)
    else: em.add_field(name="🎮 Client Updates", value="No updates detected this session.", inline=False)
    em.set_footer(text="Resets on restart")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="compare_versions", description="Compare two Roblox version strings")
@app_commands.describe(version1="First version string", version2="Second version string")
async def cmd_compare_versions(interaction: discord.Interaction, version1: str, version2: str) -> None:
    bot._command_uses += 1
    def parse(v: str): return [int(x) for x in v.replace("version-","").split(".") if x.isdigit()]
    try:
        v1, v2 = parse(version1), parse(version2)
        if v1 == v2: result, color = "🟰 **Identical** — same version", 0xaaaaaa
        elif v1 > v2: result, color = f"⬆️ **`{version1}` is newer** than `{version2}`", 0x06d6a0
        else: result, color = f"⬆️ **`{version2}` is newer** than `{version1}`", 0x4cc9f0
    except Exception: result, color = "❌ Could not parse one or both versions.", 0xe63946
    em = discord.Embed(title="🔀 Version Comparison", description=result, colour=color)
    em.add_field(name="Version A", value=f"`{version1}`", inline=True)
    em.add_field(name="Version B", value=f"`{version2}`", inline=True)
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="game_status", description="Check status of a Roblox game by Place ID")
@app_commands.describe(place_id="The Roblox Place ID")
async def cmd_game_status(interaction: discord.Interaction, place_id: str) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    try: pid = int(place_id)
    except ValueError: await interaction.followup.send("❌ Invalid Place ID."); return
    uid = await bot.get_universe_id(pid)
    if not uid: await interaction.followup.send("❌ Could not find that game."); return
    game = await bot.get_game_info(uid)
    if not game: await interaction.followup.send("❌ Could not fetch game info."); return
    active = game.get("isActive", False)
    em = discord.Embed(title=f"🎮 {game.get('name','Unknown')}", url=f"https://www.roblox.com/games/{pid}",
                       colour=0x06d6a0 if active else 0xe63946, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Status", value="🟢 Active" if active else "🔴 Inactive", inline=True)
    em.add_field(name="Playing", value=f"{game.get('playing',0):,}", inline=True)
    em.add_field(name="Visits", value=f"{game.get('visits',0):,}", inline=True)
    em.add_field(name="Creator", value=game.get("creator",{}).get("name","?"), inline=True)
    em.add_field(name="Updated", value=game.get("updated","?")[:10], inline=True)
    em.set_footer(text="Roblox Games API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="random_game", description="Get a random popular Roblox game")
async def cmd_random_game(interaction: discord.Interaction) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    d = await bot._json(ROBLOX_GAMES_LIST_URL)
    if not d or not d.get("games"): await interaction.followup.send("❌ Could not fetch games list."); return
    games = d["games"]
    game = random.choice(games)
    em = discord.Embed(title=f"🎲 Random Game: {game.get('name','?')}",
                       url=f"https://www.roblox.com/games/{game.get('placeId',0)}",
                       colour=0x9b5de5, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Playing", value=f"{game.get('playerCount',0):,}", inline=True)
    em.add_field(name="Visits", value=f"{game.get('totalUpVotes',0):,} 👍", inline=True)
    em.set_footer(text="Roblox Games API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="player_lookup", description="Look up a Roblox player by username")
@app_commands.describe(username="Roblox username to look up")
async def cmd_player_lookup(interaction: discord.Interaction, username: str) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    user = await bot.lookup_user(username)
    if not user: await interaction.followup.send("❌ Could not find that user."); return
    uid = user.get("id")
    if not uid: await interaction.followup.send("❌ User ID missing."); return
    friends = await bot.get_friend_count(uid)
    badges = await bot.get_user_badges(uid)
    created = user.get("created","")[:10]
    em = discord.Embed(title=f"👤 {user.get('displayName','?')} (@{user.get('name','?')})",
                       url=f"https://www.roblox.com/users/{uid}/profile",
                       colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="User ID", value=str(uid), inline=True)
    em.add_field(name="Joined", value=created, inline=True)
    em.add_field(name="Friends", value=str(friends), inline=True)
    em.add_field(name="Badges", value=f"{len(badges)}+", inline=True)
    em.add_field(name="Banned", value="✅ No" if not user.get("isBanned") else "❌ Yes", inline=True)
    if user.get("description"): em.add_field(name="Bio", value=user["description"][:200], inline=False)
    em.set_footer(text="Roblox Users API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="group_info", description="Look up a Roblox group by ID")
@app_commands.describe(group_id="Roblox group ID")
async def cmd_group_info(interaction: discord.Interaction, group_id: str) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    try: gid = int(group_id)
    except ValueError: await interaction.followup.send("❌ Invalid group ID."); return
    group = await bot.get_group(gid)
    if not group: await interaction.followup.send("❌ Could not find that group."); return
    em = discord.Embed(title=f"👥 {group.get('name','?')}",
                       url=f"https://www.roblox.com/groups/{gid}",
                       colour=0xffd166, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Members", value=f"{group.get('memberCount',0):,}", inline=True)
    em.add_field(name="Owner", value=group.get("owner",{}).get("username","?"), inline=True)
    em.add_field(name="Public", value="✅ Yes" if group.get("publicEntryAllowed") else "🔒 No", inline=True)
    if group.get("description"): em.add_field(name="Description", value=group["description"][:300], inline=False)
    em.set_footer(text="Roblox Groups API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="badge_check", description="Check if a user has a specific badge")
@app_commands.describe(username="Roblox username", badge_id="Badge ID to check")
async def cmd_badge_check(interaction: discord.Interaction, username: str, badge_id: str) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    try: bid = int(badge_id)
    except ValueError: await interaction.followup.send("❌ Invalid badge ID."); return
    user = await bot.lookup_user(username)
    if not user or not user.get("id"): await interaction.followup.send("❌ User not found."); return
    badge = await bot.get_badge(bid)
    has_it = await bot.user_has_badge(user["id"], bid)
    em = discord.Embed(title="🏅 Badge Check", colour=0x06d6a0 if has_it else 0xe63946)
    em.add_field(name="Player", value=f"@{user.get('name','?')}", inline=True)
    em.add_field(name="Badge", value=badge.get("name","?") if badge else str(bid), inline=True)
    em.add_field(name="Result", value="✅ Has this badge!" if has_it else "❌ Does not have this badge", inline=False)
    await interaction.followup.send(embed=em)

@bot.tree.command(name="robux_rates", description="Current Robux to USD exchange and DevEx rates")
async def cmd_robux_rates(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    em = discord.Embed(title="💰 Robux Exchange Rates", colour=0x06d6a0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Buy Rate", value="$0.0035 per Robux\n(~286 R$ per $1)", inline=False)
    em.add_field(name="DevEx Rate", value="$0.0035 per Robux earned\n(Min 30,000 R$)", inline=False)
    em.add_field(name="Roblox Premium", value="$4.99 → 450 R$\n$9.99 → 1,000 R$\n$19.99 → 2,200 R$", inline=False)
    em.add_field(name="Gift Card", value="$10 → 800 R$\n$25 → 2,000 R$\n$50 → 4,500 R$", inline=False)
    em.set_footer(text="Rates as of 2026 — check roblox.com for latest")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="trade_calculator", description="Calculate if a Roblox trade is worth it based on RAP")
@app_commands.describe(your_rap="Your items total RAP", their_rap="Their items total RAP")
async def cmd_trade_calculator(interaction: discord.Interaction, your_rap: int, their_rap: int) -> None:
    bot._command_uses += 1
    diff = their_rap - your_rap
    pct = (diff / your_rap * 100) if your_rap else 0
    if diff > 0: verdict = f"✅ **Good trade!** You gain R${diff:,} RAP ({pct:+.1f}%)"; color = 0x06d6a0
    elif diff < 0: verdict = f"❌ **Bad trade!** You lose R${abs(diff):,} RAP ({pct:+.1f}%)"; color = 0xe63946
    else: verdict = "🟰 **Even trade** — equal RAP value"; color = 0xaaaaaa
    em = discord.Embed(title="⚖️ Trade Calculator", description=verdict, colour=color)
    em.add_field(name="Your RAP", value=f"R${your_rap:,}", inline=True)
    em.add_field(name="Their RAP", value=f"R${their_rap:,}", inline=True)
    em.add_field(name="Difference", value=f"R${diff:+,}", inline=True)
    em.set_footer(text="RAP = Recent Average Price")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="limited_tracker", description="Check resale data for a Roblox limited item")
@app_commands.describe(asset_id="Asset ID of the limited item")
async def cmd_limited_tracker(interaction: discord.Interaction, asset_id: str) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    try: aid = int(asset_id)
    except ValueError: await interaction.followup.send("❌ Invalid asset ID."); return
    resale = await bot.get_item_resale(aid)
    details = await bot.get_item_details(aid)
    if not resale: await interaction.followup.send("❌ Could not fetch item. Is it a limited?"); return
    name = details.get("name", f"Item {aid}") if details else f"Item {aid}"
    rap  = resale.get("recentAveragePrice", 0)
    orig = resale.get("originalPrice", 0)
    vol  = resale.get("volume", 0)
    em = discord.Embed(title=f"📈 Limited: {name}", url=f"https://www.roblox.com/catalog/{aid}",
                       colour=0xffd166, timestamp=datetime.now(timezone.utc))
    em.add_field(name="RAP (Avg)", value=f"R${rap:,}", inline=True)
    em.add_field(name="Original Price", value=f"R${orig:,}", inline=True)
    em.add_field(name="Total Volume", value=f"{vol:,}", inline=True)
    if orig and rap:
        roi = ((rap - orig) / orig * 100)
        em.add_field(name="ROI vs Original", value=f"{roi:+.1f}%", inline=True)
    em.set_footer(text="Roblox Economy API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="ugc_trending", description="Trending UGC items on the Roblox catalog")
async def cmd_ugc_trending(interaction: discord.Interaction) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    items = await bot.get_catalog_items(8)
    em = discord.Embed(title="🛍️ Trending UGC Items", colour=0xf72585, timestamp=datetime.now(timezone.utc))
    if items:
        for item in items:
            price_str = f"R${item['price']:,}" if item["price"] else "Free"
            em.add_field(name=item["name"][:50], value=f"💰 {price_str} | 👤 {item['creator']}\n[View](https://www.roblox.com/catalog/{item['id']})", inline=True)
    else: em.description = "Could not fetch catalog right now."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="ugc_price", description="Check resale price of a UGC item")
@app_commands.describe(asset_id="Roblox asset ID")
async def cmd_ugc_price(interaction: discord.Interaction, asset_id: str) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    try: aid = int(asset_id)
    except ValueError: await interaction.followup.send("❌ Invalid asset ID."); return
    resale = await bot.get_item_resale(aid)
    details = await bot.get_item_details(aid)
    if not resale: await interaction.followup.send("❌ Could not fetch item."); return
    name = details.get("name", f"Item {aid}") if details else f"Item {aid}"
    em = discord.Embed(title=f"💰 {name}", url=f"https://www.roblox.com/catalog/{aid}",
                       colour=0xffd166, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Original Price", value=f"R${resale.get('originalPrice',0):,}", inline=True)
    em.add_field(name="Recent Avg Price", value=f"R${resale.get('recentAveragePrice',0):,}", inline=True)
    em.add_field(name="Total Volume", value=f"{resale.get('volume',0):,} sales", inline=True)
    em.set_footer(text="Roblox Economy API")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="ugc_watch", description="Watch a UGC item for price change alerts")
@app_commands.describe(asset_id="Roblox asset ID to watch")
async def cmd_ugc_watch(interaction: discord.Interaction, asset_id: str) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    try: aid = int(asset_id)
    except ValueError: await interaction.followup.send("❌ Invalid asset ID."); return
    if len(bot._watched_items) >= 20: await interaction.followup.send("❌ Already watching 20 items max."); return
    resale = await bot.get_item_resale(aid)
    details = await bot.get_item_details(aid)
    if not resale: await interaction.followup.send("❌ Could not find that item."); return
    name = details.get("name", f"Item {aid}") if details else f"Item {aid}"
    price = resale.get("recentAveragePrice") or resale.get("originalPrice") or 0
    bot._watched_items[aid] = {"name": name, "price": price}
    em = discord.Embed(title="👁️ Now Watching", description=f"**[{name}](https://www.roblox.com/catalog/{aid})**",
                       colour=0x06d6a0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Current Price", value=f"R${price:,}", inline=True)
    em.add_field(name="Watching", value=f"{len(bot._watched_items)}/20 items", inline=True)
    em.set_footer(text="Checks every 30 min for price changes")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="ugc_unwatch", description="Stop watching a UGC item")
@app_commands.describe(asset_id="Asset ID to stop watching")
async def cmd_ugc_unwatch(interaction: discord.Interaction, asset_id: str) -> None:
    bot._command_uses += 1
    try: aid = int(asset_id)
    except ValueError: await interaction.response.send_message("❌ Invalid asset ID."); return
    if aid in bot._watched_items:
        name = bot._watched_items.pop(aid).get("name", str(aid))
        await interaction.response.send_message(f"✅ Stopped watching **{name}**.")
    else: await interaction.response.send_message("❌ That item is not being watched.")

@bot.tree.command(name="ugc_watchlist", description="Show all watched UGC items")
async def cmd_ugc_watchlist(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    em = discord.Embed(title="👁️ UGC Watchlist", colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    if bot._watched_items:
        for aid, info in bot._watched_items.items():
            em.add_field(name=info.get("name", str(aid)), value=f"💰 R${info.get('price',0):,} | [View](https://www.roblox.com/catalog/{aid})", inline=True)
    else: em.description = "No items watched. Use `/ugc_watch <asset_id>` to add one!"
    em.set_footer(text=f"{len(bot._watched_items)}/20 items • checks every 30 min")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="alert_threshold", description="Only alert on UGC price changes above X percent")
@app_commands.describe(percent="Minimum % change to trigger an alert (0 = any change)")
async def cmd_alert_threshold(interaction: discord.Interaction, percent: float) -> None:
    bot._command_uses += 1
    bot._alert_threshold = max(0.0, percent)
    await interaction.response.send_message(f"✅ UGC price alerts will only fire when price changes by **{bot._alert_threshold:.1f}%** or more.")

@bot.tree.command(name="mute_updates", description="Pause auto-alerts for X hours")
@app_commands.describe(hours="Number of hours to mute alerts (0 to unmute)")
@admin_check()
async def cmd_mute_updates(interaction: discord.Interaction, hours: float) -> None:
    bot._command_uses += 1
    if hours <= 0:
        bot._muted_until = 0
        await interaction.response.send_message("🔔 Alerts have been **unmuted**.")
    else:
        bot._muted_until = time.time() + hours * 3600
        await interaction.response.send_message(f"🔕 Alerts muted for **{hours}h**. Resumes <t:{int(bot._muted_until)}:R>.")

@bot.tree.command(name="filter_updates", description="Choose which update types to receive alerts for")
@app_commands.describe(client="Alert on Roblox client updates",
                       devforum="Alert on new DevForum announcements",
                       incident="Alert on Roblox status incidents")
@admin_check()
async def cmd_filter_updates(interaction: discord.Interaction,
                              client: bool = True, devforum: bool = True, incident: bool = True) -> None:
    bot._command_uses += 1
    bot._filters = {"client": client, "devforum": devforum, "incident": incident}
    em = discord.Embed(title="🔍 Update Filters Set", colour=0x4cc9f0)
    em.add_field(name="🎮 Client Updates", value="✅ On" if client else "❌ Off", inline=True)
    em.add_field(name="📢 DevForum Alerts", value="✅ On" if devforum else "❌ Off", inline=True)
    em.add_field(name="🚨 Incident Alerts", value="✅ On" if incident else "❌ Off", inline=True)
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="server_stats", description="Show bot usage stats for this server")
async def cmd_server_stats(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    uptime = int(time.time() - bot._start_time)
    h, rem = divmod(uptime, 3600)
    m, _ = divmod(rem, 60)
    em = discord.Embed(title="📈 Server Stats", colour=0x9b5de5, timestamp=datetime.now(timezone.utc))
    em.add_field(name="💬 Total Commands Used", value=str(bot._command_uses), inline=True)
    em.add_field(name="⏱️ Bot Uptime", value=f"{h}h {m}m", inline=True)
    em.add_field(name="🔔 Alert Channel", value=f"<#{bot.update_channel_id}>" if bot.update_channel_id else "Not set", inline=True)
    em.add_field(name="👁️ Watched UGC Items", value=str(len(bot._watched_items)), inline=True)
    em.add_field(name="📋 Version Changes", value=str(len(bot._client_changelog)), inline=True)
    em.add_field(name="🔕 Muted", value="Yes" if time.time() < bot._muted_until else "No", inline=True)
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="poll", description="Create a quick Roblox poll")
@app_commands.describe(question="Poll question", option_a="First option", option_b="Second option")
async def cmd_poll(interaction: discord.Interaction, question: str, option_a: str, option_b: str) -> None:
    bot._command_uses += 1
    em = discord.Embed(title=f"📊 {question}", colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="🅰️ Option A", value=option_a, inline=True)
    em.add_field(name="🅱️ Option B", value=option_b, inline=True)
    em.set_footer(text=f"Poll by {interaction.user.display_name}")
    await interaction.response.send_message(embed=em)
    message = await interaction.original_response()
    await message.add_reaction("🅰️")
    await message.add_reaction("🅱️")

@bot.tree.command(name="uptime_history", description="Roblox incident history for the last 30 days")
async def cmd_uptime_history(interaction: discord.Interaction) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    incidents = await bot.get_incident_history(10)
    em = discord.Embed(title="📅 Roblox Incident History (Last 30 Days)", colour=0xff6b35, timestamp=datetime.now(timezone.utc))
    if incidents:
        for inc in incidents:
            icon = {"none":"🟢","minor":"🟡","major":"🟠","critical":"🔴"}.get(inc["impact"],"⚪")
            em.add_field(name=f"{icon} {inc['name']}",
                         value=f"Status: `{inc['status'].replace('_',' ').title()}` | {inc['created_at']}\n[View]({inc['url']})",
                         inline=False)
    else: em.description = "✅ No incidents found in the last 30 days!"
    em.set_footer(text="status.roblox.com")
    await interaction.followup.send(embed=em)

@bot.tree.command(name="deploy_history", description="Last 15 CDN deploy log entries")
async def cmd_deploy_history(interaction: discord.Interaction) -> None:
    bot._command_uses += 1; await interaction.response.defer()
    entries = await bot.get_deploy_history(15)
    em = discord.Embed(title="📦 CDN Deploy History", colour=0x4cc9f0)
    if entries: em.description = f"```\n{chr(10).join(entries)[-3900:]}\n```"
    else: em.description = "Could not retrieve deploy history."
    await interaction.followup.send(embed=em)

@bot.tree.command(name="set_update_channel", description="Set the alert channel (Admin only)")
@admin_check()
@app_commands.describe(channel="Channel to post alerts in")
async def cmd_set_update_channel(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
    bot.update_channel_id = channel.id
    await interaction.response.send_message(f"✅ Alerts will now post in {channel.mention}.")

@bot.tree.command(name="help_roblox", description="Show all commands")
async def cmd_help(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    em = discord.Embed(title="🤖 Roblox Update Tracker — All Commands", colour=0x4cc9f0)
    categories = {
        "📡 Updates & Versions": [
            ("/roblox_version", "Current live Roblox version"),
            ("/latest_updates", "Latest DevForum announcements"),
            ("/release_notes", "Official release notes"),
            ("/upcoming_features", "Beta & upcoming features"),
            ("/changelog", "Last 10 version changes"),
            ("/compare_versions", "Compare two version strings"),
            ("/deploy_history", "CDN deploy log"),
        ],
        "🔒 Security & Status": [
            ("/security_updates", "Security patches and incidents"),
            ("/status", "Full platform status"),
            ("/uptime_history", "Incident history last 30 days"),
        ],
        "🎮 Games & Players": [
            ("/game_status", "Check a game by Place ID"),
            ("/random_game", "Get a random popular game"),
            ("/player_lookup", "Look up a Roblox player"),
            ("/group_info", "Look up a Roblox group"),
            ("/badge_check", "Check if a user has a badge"),
        ],
        "💰 Economy & UGC": [
            ("/robux_rates", "Robux to USD exchange rates"),
            ("/trade_calculator", "Calculate if a trade is worth it"),
            ("/limited_tracker", "Track a limited item's RAP"),
            ("/ugc_trending", "Trending UGC items"),
            ("/ugc_price", "Check UGC item resale price"),
            ("/ugc_watch", "Watch item for price alerts"),
            ("/ugc_unwatch", "Stop watching an item"),
            ("/ugc_watchlist", "Show watched items"),
            ("/alert_threshold", "Set min % for price alerts"),
        ],
        "⚙️ Bot Management": [
            ("/stats", "Bot stats and uptime"),
            ("/server_stats", "Server usage stats"),
            ("/poll", "Create a quick poll"),
            ("/mute_updates", "Pause alerts for X hours (Admin)"),
            ("/filter_updates", "Choose alert types (Admin)"),
            ("/set_update_channel", "Set alert channel (Admin)"),
        ],
        "🔨 Moderation": [
            ("/warn", "Warn a user and log it"),
            ("/warnings", "See all warnings for a user"),
            ("/clearwarnings", "Clear a user's warnings"),
            ("/kick", "Kick a user (optionally anonymous)"),
            ("/ban", "Ban a user (optionally anonymous)"),
            ("/unban", "Unban a user by ID"),
            ("/banned_list", "Show recently banned users"),
            ("/timeout", "Timeout a user for X minutes"),
        ],
        "📢 Announcements": [
            ("/announce", "Post a formatted embed to any channel"),
            ("/dm_blast", "DM all members with a message (Admin)"),
            ("/schedule_announcement", "Schedule a message to post later"),
        ],
        "📊 Logging": [
            ("/set_log_channel", "Log all bot actions to a channel (Admin)"),
            ("/audit", "Show recent bot actions and who triggered them"),
        ],
        "🎭 Roles": [
            ("/set_ping_role", "Ping a role instead of @everyone (Admin)"),
            ("/autorole", "Auto-assign a role to new members (Admin)"),
            ("/role_info", "Show info about a role"),
        ],
        "⚙️ Configuration": [
            ("/set_prefix", "Change the bot prefix (Admin)"),
            ("/bot_info", "Show full bot configuration"),
            ("/reset_settings", "Reset all settings to default (Admin)"),
            ("/backup_settings", "Export all settings as JSON (Admin)"),
        ],
        "🧹 Purge": [
            ("/purge", "Bulk-delete up to 100 messages in a channel"),
        ],
        "🛡️ Anti-Raid": [
            ("/antiraid_on", "Manually enable lockdown (Admin)"),
            ("/antiraid_off", "Disable lockdown (Admin)"),
            ("/antiraid_config", "Set detection thresholds & action (Admin)"),
            ("/antiraid_status", "Show current anti-raid status"),
        ],
        "🤬 Auto-Mod": [
            ("/automod_enable", "Enable profanity filter (Admin)"),
            ("/automod_disable", "Disable profanity filter (Admin)"),
            ("/automod_addword", "Add a word to the filter (Admin)"),
            ("/automod_removeword", "Remove a word from the filter (Admin)"),
            ("/automod_status", "Show filter config and word list"),
            ("/automod_logs", "Recent violations log (Mod+)"),
            ("/strike_leaderboard", "Top users by total strikes (Mod+)"),
            ("/automod_clearstrikes", "Clear a user's strike count (Admin)"),
        ],
        "🚨 Reports": [
            ("/user_report", "Anonymously report a member with screenshot evidence"),
            ("/view_reports", "Browse reports, filter by member or status (Mod+)"),
            ("/resolve_report", "Mark a report as resolved (Mod+)"),
            ("/dismiss_report", "Dismiss a report with a reason (Mod+)"),
        ],
        "🔑 Permissions": [
            ("/set_mod_role", "Set role that can use mod commands (Admin)"),
            ("/set_admin_role", "Set role that can use admin commands (Admin)"),
            ("/sync", "Force re-sync all commands to this server (Admin)"),
        ],
        "✨ Server Management": [
            ("/setwelcome", "Set welcome channel & message (Admin)"),
            ("/verify", "Send a verification panel"),
            ("/setverifiedrole", "Set the role given by verification (Admin)"),
            ("/suggest", "Submit a suggestion"),
            ("/setsuggestchannel", "Set suggestion channel (Admin)"),
            ("/reactionrole", "Add/remove reaction roles (Admin)"),
            ("/ticket", "Create a ticket channel"),
            ("/close", "Close a ticket channel"),
            ("/giveaway", "Start a giveaway (Mod)"),
            ("/tempvc", "Create a temporary voice channel (Admin)"),
            ("/ask", "Ask the AI anything"),
# ---------------------------------------------------------------------------
# 🔨 Moderation (Slash)
# ---------------------------------------------------------------------------
@bot.tree.command(name="warn", description="Warn a user and log the reason")
@app_commands.describe(member="Member to warn", reason="Reason for the warning")
@mod_check()
async def cmd_warn(interaction: discord.Interaction, member: discord.Member, reason: str) -> None:
    bot._command_uses += 1
    uid = str(member.id)
    entry = {
        "reason": reason,
        "by": str(interaction.user),
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    bot._warnings.setdefault(uid, []).append(entry)
    bot._save_data()
    count = len(bot._warnings[uid])
    em = discord.Embed(title="⚠️ User Warned", colour=0xffd166, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Member",       value=f"{member.mention} ({member})", inline=False)
    em.add_field(name="Reason",       value=reason,                          inline=False)
    em.add_field(name="Total Warns",  value=str(count),                      inline=True)
    em.add_field(name="Warned by",    value=str(interaction.user),           inline=True)
    em.set_footer(text=f"User ID: {member.id}")
    await interaction.response.send_message(embed=em)
    bot._add_audit("warn", interaction.user, f"Warned {member} ({member.id}): {reason}")
    await bot._log_action(em)

@bot.tree.command(name="warnings", description="Show all warnings for a user")
@app_commands.describe(member="Member to check")
async def cmd_warnings(interaction: discord.Interaction, member: discord.Member) -> None:
    bot._command_uses += 1
    uid = str(member.id)
    warns = bot._warnings.get(uid, [])
    em = discord.Embed(title=f"⚠️ Warnings — {member.display_name}", colour=0xffd166,
                       timestamp=datetime.now(timezone.utc))
    if warns:
        for i, w in enumerate(warns, 1):
            em.add_field(name=f"#{i} — {w['time']}", value=f"**Reason:** {w['reason']}\n**By:** {w['by']}",
                         inline=False)
    else:
        em.description = "✅ This user has no warnings."
    em.set_footer(text=f"Total: {len(warns)} warning(s) • ID: {member.id}")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="clearwarnings", description="Clear all warnings for a user")
@app_commands.describe(member="Member to clear warnings for")
@mod_check()
async def cmd_clearwarnings(interaction: discord.Interaction, member: discord.Member) -> None:
    bot._command_uses += 1
    uid = str(member.id)
    count = len(bot._warnings.pop(uid, []))
    bot._save_data()
    em = discord.Embed(title="🗑️ Warnings Cleared", colour=0x06d6a0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Member",          value=f"{member.mention} ({member})", inline=False)
    em.add_field(name="Warnings Removed",value=str(count),                     inline=True)
    em.add_field(name="Cleared by",      value=str(interaction.user),          inline=True)
    await interaction.response.send_message(embed=em)
    bot._add_audit("clearwarnings", interaction.user, f"Cleared {count} warnings for {member} ({member.id})")
    await bot._log_action(em)

@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="Member to kick", reason="Reason for the kick",
                       anonymous="Hide your identity from the kicked user (default: False)")
@mod_check()
async def cmd_kick(interaction: discord.Interaction, member: discord.Member,
                   reason: str = "No reason provided", anonymous: bool = False) -> None:
    bot._command_uses += 1
    dm_sent = False
    if anonymous:
        dm_content = f"You have been **kicked** from **{interaction.guild.name}**.\nReason: {reason}"
    else:
        dm_content = f"You have been **kicked** from **{interaction.guild.name}** by {interaction.user.mention}.\nReason: {reason}"
    try:
        await member.send(dm_content)
        dm_sent = True
    except discord.Forbidden:
        pass
    try:
        await member.kick(reason=reason)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to kick that member.", ephemeral=True)
        return
    em = discord.Embed(title="👢 Member Kicked", colour=0xff6b35, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Member",   value=f"{member} ({member.id})", inline=False)
    em.add_field(name="Reason",   value=reason,                    inline=False)
    em.add_field(name="Kicked by", value="Anonymous" if anonymous else str(interaction.user), inline=True)
    if dm_sent:
        em.set_footer(text="User was notified via DM.")
    else:
        em.set_footer(text="Could not DM the user (DMs closed).")
    await interaction.response.send_message(embed=em)
    bot._add_audit("kick", interaction.user, f"Kicked {member} ({member.id}): {reason} (anonymous={anonymous})")
    await bot._log_action(em)

@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="Member to ban", reason="Reason for the ban",
                       anonymous="Hide your identity from the banned user (default: False)")
@mod_check()
async def cmd_ban(interaction: discord.Interaction, member: discord.Member,
                  reason: str = "No reason provided", anonymous: bool = False) -> None:
    bot._command_uses += 1
    dm_sent = False
    if anonymous:
        dm_content = f"You have been **banned** from **{interaction.guild.name}**.\nReason: {reason}"
    else:
        dm_content = f"You have been **banned** from **{interaction.guild.name}** by {interaction.user.mention}.\nReason: {reason}"
    try:
        await member.send(dm_content)
        dm_sent = True
    except discord.Forbidden:
        pass
    try:
        await member.ban(reason=reason, delete_message_days=0)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to ban that member.", ephemeral=True)
        return
    bot._banned_users[str(member.id)] = {
        "user": str(member), "reason": reason,
        "banned_by": "Anonymous" if anonymous else str(interaction.user), "timestamp": time.time()
    }
    bot._cleanup_banned_users()
    bot._save_data()
    em = discord.Embed(title="🔨 Member Banned", colour=0xe63946, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Member",  value=f"{member} ({member.id})", inline=False)
    em.add_field(name="Reason",  value=reason,                    inline=False)
    em.add_field(name="Banned by", value="Anonymous" if anonymous else str(interaction.user), inline=True)
    if dm_sent:
        em.set_footer(text="User was notified via DM.")
    else:
        em.set_footer(text="Could not DM the user (DMs closed).")
    await interaction.response.send_message(embed=em)
    bot._add_audit("ban", interaction.user, f"Banned {member} ({member.id}): {reason} (anonymous={anonymous})")
    await bot._log_action(em)

@bot.tree.command(name="unban", description="Unban a user by ID")
@app_commands.describe(user_id="The Discord ID of the banned user")
@mod_check()
async def cmd_unban(interaction: discord.Interaction, user_id: str) -> None:
    bot._command_uses += 1
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)
        return
    try:
        user = await bot.fetch_user(int(user_id))
        await guild.unban(user, reason=f"Unbanned by {interaction.user}")
        if user_id in bot._banned_users:
            del bot._banned_users[user_id]
            bot._save_data()
        await interaction.response.send_message(f"✅ Unbanned {user}.")
    except discord.NotFound:
        await interaction.response.send_message("❌ User not found.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to unban.", ephemeral=True)

@bot.tree.command(name="banned_list", description="Show users banned in the last 7 days")
@mod_check()
async def cmd_banned_list(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    bot._cleanup_banned_users()
    em = discord.Embed(title="📜 Recently Banned Users (Last 7 Days)", colour=0xff6b35,
                       timestamp=datetime.now(timezone.utc))
    if not bot._banned_users:
        em.description = "✅ No users have been banned recently."
        await interaction.response.send_message(embed=em)
        return
    entries = sorted(bot._banned_users.values(), key=lambda x: x["timestamp"], reverse=True)
    for entry in entries[:20]:
        ts = int(entry["timestamp"])
        em.add_field(
            name=f"{entry.get('user', 'Unknown')}",
            value=(
                f"**Reason:** {entry.get('reason', 'N/A')}\n"
                f"**Banned by:** {entry.get('banned_by', 'Unknown')}\n"
                f"**When:** <t:{ts}:R>"
            ),
            inline=False,
        )
    em.set_footer(text=f"{len(bot._banned_users)} total banned user(s) in the list")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="timeout", description="Timeout a member for X minutes")
@app_commands.describe(member="Member to timeout", minutes="Duration in minutes", reason="Reason")
@mod_check()
async def cmd_timeout(interaction: discord.Interaction, member: discord.Member,
                      minutes: int, reason: str = "No reason provided") -> None:
    bot._command_uses += 1
    import datetime as dt
    until = discord.utils.utcnow() + dt.timedelta(minutes=minutes)
    try:
        await member.timeout(until, reason=reason)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to timeout that member.", ephemeral=True)
        return
    em = discord.Embed(title="⏱️ Member Timed Out", colour=0xffd166, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Member",     value=f"{member.mention} ({member})", inline=False)
    em.add_field(name="Duration",   value=f"{minutes} minute(s)",         inline=True)
    em.add_field(name="Expires",    value=f"<t:{int(until.timestamp())}:R>", inline=True)
    em.add_field(name="Reason",     value=reason,                          inline=False)
    em.add_field(name="By",         value=str(interaction.user),           inline=True)
    await interaction.response.send_message(embed=em)
    bot._add_audit("timeout", interaction.user, f"Timed out {member} ({member.id}) for {minutes}m: {reason}")
    await bot._log_action(em)

# ---------------------------------------------------------------------------
# 📢 Announcements
# ---------------------------------------------------------------------------
@bot.tree.command(name="announce", description="Post a formatted announcement embed to any channel")
@app_commands.describe(channel="Channel to post in", title="Announcement title", message="Announcement message",
                        color="Embed color hex (e.g. ff0000) — optional")
@mod_check()
async def cmd_announce(interaction: discord.Interaction, channel: discord.TextChannel,
                        title: str, message: str, color: str = "4cc9f0") -> None:
    bot._command_uses += 1
    try:
        clr = int(color.lstrip("#"), 16)
    except ValueError:
        clr = 0x4cc9f0
    em = discord.Embed(title=title, description=message, colour=clr, timestamp=datetime.now(timezone.utc))
    em.set_footer(text=f"Announced by {interaction.user.display_name}")
    try:
        await channel.send(embed=em)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I can't send messages in that channel.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ Announcement posted in {channel.mention}.", ephemeral=True)
    bot._add_audit("announce", interaction.user, f"Announced to #{channel.name}: {title}")
    await bot._log_action(discord.Embed(
        title="📢 Announcement Sent", colour=0x4cc9f0,
        description=f"**Channel:** {channel.mention}\n**Title:** {title}\n**By:** {interaction.user}"
    ))

@bot.tree.command(name="dm_blast", description="DM all members with a message (Admin only)")
@app_commands.describe(message="Message to DM to all members")
@admin_check()
async def cmd_dm_blast(interaction: discord.Interaction, message: str) -> None:
    bot._command_uses += 1
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if not guild:
        await interaction.followup.send("❌ Must be used in a server.", ephemeral=True)
        return
    em = discord.Embed(title=f"📣 Message from {guild.name}", description=message,
                       colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.set_footer(text=f"Sent by {interaction.user.display_name}")
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
    await interaction.followup.send(
        f"✅ DM blast complete — **{sent}** sent, **{failed}** failed.", ephemeral=True
    )
    bot._add_audit("dm_blast", interaction.user, f"DM blast to {sent} members: {message[:80]}")

@bot.tree.command(name="schedule_announcement", description="Schedule a message to post at a specific time")
@app_commands.describe(channel="Channel to post in", title="Announcement title", message="Message content",
                        minutes_from_now="Minutes from now to send (e.g. 60 = 1 hour)")
@mod_check()
async def cmd_schedule(interaction: discord.Interaction, channel: discord.TextChannel,
                        title: str, message: str, minutes_from_now: int) -> None:
    bot._command_uses += 1
    if minutes_from_now < 1:
        await interaction.response.send_message("❌ Must be at least 1 minute from now.", ephemeral=True)
        return
    send_at = time.time() + minutes_from_now * 60
    bot._scheduled.append({
        "channel_id": channel.id,
        "title":      title,
        "message":    message,
        "send_at":    send_at,
        "author":     str(interaction.user),
    })
    bot._save_data()
    ts = int(send_at)
    em = discord.Embed(title="🕐 Announcement Scheduled", colour=0x9b5de5, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Channel",   value=channel.mention,          inline=True)
    em.add_field(name="Sends",     value=f"<t:{ts}:R> (<t:{ts}:f>)", inline=True)
    em.add_field(name="Title",     value=title,                    inline=False)
    em.add_field(name="Message",   value=message[:200],            inline=False)
    await interaction.response.send_message(embed=em)
    bot._add_audit("schedule_announcement", interaction.user, f"Scheduled to #{channel.name} in {minutes_from_now}m")

# ---------------------------------------------------------------------------
# 📊 Logging
# ---------------------------------------------------------------------------
@bot.tree.command(name="set_log_channel", description="Set the channel for bot action logs (Admin only)")
@app_commands.describe(channel="Channel to log bot actions to")
@admin_check()
async def cmd_set_log_channel(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
    bot._command_uses += 1
    bot._log_channel_id = channel.id
    bot._save_data()
    await interaction.response.send_message(f"✅ Bot actions will now be logged in {channel.mention}.")
    bot._add_audit("set_log_channel", interaction.user, f"Log channel set to #{channel.name}")

@bot.tree.command(name="audit", description="Show the last 15 bot actions and who triggered them")
@mod_check()
async def cmd_audit(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    entries = bot._audit_log[-15:]
    em = discord.Embed(title="📋 Bot Audit Log (Last 15 Actions)", colour=0x4cc9f0,
                       timestamp=datetime.now(timezone.utc))
    if entries:
        for e in reversed(entries):
            detail = f" — {e['detail']}" if e.get("detail") else ""
            em.add_field(name=f"`{e['action']}` • {e['time']}",
                         value=f"By: **{e['by']}**{detail}"[:1024], inline=False)
    else:
        em.description = "No audit log entries yet."
    await interaction.response.send_message(embed=em)

# ---------------------------------------------------------------------------
# 🎭 Roles
# ---------------------------------------------------------------------------
@bot.tree.command(name="set_ping_role", description="Ping a specific role instead of @everyone for updates (Admin only)")
@app_commands.describe(role="Role to ping for updates (leave blank to use @everyone)")
@admin_check()
async def cmd_set_ping_role(interaction: discord.Interaction, role: discord.Role | None = None) -> None:
    bot._command_uses += 1
    bot._ping_role_id = role.id if role else None
    bot._save_data()
    if role:
        await interaction.response.send_message(f"✅ Updates will now ping {role.mention} instead of @everyone.")
    else:
        await interaction.response.send_message("✅ Reverted to @everyone pings.")
    bot._add_audit("set_ping_role", interaction.user, f"Ping role set to {role} ({role.id})" if role else "Ping role cleared")

@bot.tree.command(name="autorole", description="Automatically give new members a role when they join (Admin only)")
@app_commands.describe(role="Role to assign on join (leave blank to disable)")
@admin_check()
async def cmd_autorole(interaction: discord.Interaction, role: discord.Role | None = None) -> None:
    bot._command_uses += 1
    bot._autorole_id = role.id if role else None
    bot._save_data()
    if role:
        await interaction.response.send_message(f"✅ New members will automatically receive {role.mention}.")
    else:
        await interaction.response.send_message("✅ Auto-role has been disabled.")
    bot._add_audit("autorole", interaction.user, f"Auto-role set to {role}" if role else "Auto-role disabled")

@bot.tree.command(name="role_info", description="Show info about a role")
@app_commands.describe(role="The role to inspect")
async def cmd_role_info(interaction: discord.Interaction, role: discord.Role) -> None:
    bot._command_uses += 1
    perms = [p.replace("_", " ").title() for p, v in role.permissions if v]
    em = discord.Embed(title=f"🎭 Role: {role.name}", colour=role.colour,
                       timestamp=datetime.now(timezone.utc))
    em.add_field(name="ID",          value=str(role.id),                             inline=True)
    em.add_field(name="Members",     value=str(len(role.members)),                   inline=True)
    em.add_field(name="Position",    value=str(role.position),                       inline=True)
    em.add_field(name="Mentionable", value="✅ Yes" if role.mentionable else "❌ No", inline=True)
    em.add_field(name="Hoisted",     value="✅ Yes" if role.hoist else "❌ No",       inline=True)
    em.add_field(name="Color",       value=str(role.colour),                         inline=True)
    em.add_field(name="Created",     value=role.created_at.strftime("%Y-%m-%d"),     inline=True)
    if perms:
        em.add_field(name="Key Permissions", value=", ".join(perms[:15]) + ("…" if len(perms) > 15 else ""),
                     inline=False)
    em.set_footer(text=f"Managed: {'Yes' if role.managed else 'No'}")
    await interaction.response.send_message(embed=em)

# ---------------------------------------------------------------------------
# ⚙️ Configuration
# ---------------------------------------------------------------------------
@bot.tree.command(name="set_prefix", description="Change the bot prefix (Admin only)")
@app_commands.describe(prefix="New prefix (e.g. ! or . or $)")
@admin_check()
async def cmd_set_prefix(interaction: discord.Interaction, prefix: str) -> None:
    bot._command_uses += 1
    if len(prefix) > 5:
        await interaction.response.send_message("❌ Prefix must be 5 characters or fewer.", ephemeral=True)
        return
    bot._prefix = prefix
    bot._save_data()
    await interaction.response.send_message(f"✅ Prefix set to `{prefix}`.")
    bot._add_audit("set_prefix", interaction.user, f"Prefix changed to '{prefix}'")

@bot.tree.command(name="bot_info", description="Show full bot configuration")
async def cmd_bot_info(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    uptime = int(time.time() - bot._start_time)
    h, rem = divmod(uptime, 3600)
    m, s = divmod(rem, 60)
    guild = interaction.guild
    def fmt_channel(cid: int | None) -> str:
        return f"<#{cid}>" if cid else "Not set"
    def fmt_role(rid: int | None) -> str:
        if not rid or not guild: return "Not set"
        r = guild.get_role(rid)
        return r.mention if r else f"Unknown ({rid})"
    em = discord.Embed(title="⚙️ Full Bot Configuration", colour=0x4cc9f0,
                       timestamp=datetime.now(timezone.utc))
    em.add_field(name="🤖 Bot",             value=str(bot.user),                                     inline=True)
    em.add_field(name="⏱️ Uptime",          value=f"{h}h {m}m {s}s",                                inline=True)
    em.add_field(name="💬 Prefix",          value=f"`{bot._prefix}`",                               inline=True)
    em.add_field(name="📣 Alert Channel",   value=fmt_channel(bot.update_channel_id),               inline=True)
    em.add_field(name="📋 Log Channel",     value=fmt_channel(bot._log_channel_id),                 inline=True)
    em.add_field(name="🔔 Ping Role",       value=fmt_role(bot._ping_role_id),                      inline=True)
    em.add_field(name="🎭 Auto-role",       value=fmt_role(bot._autorole_id),                       inline=True)
    em.add_field(name="🔍 Active Filters",  value=", ".join(k for k,v in bot._filters.items() if v) or "None", inline=True)
    em.add_field(name="🔕 Muted",           value="Yes" if time.time() < bot._muted_until else "No",inline=True)
    em.add_field(name="📊 Poll Interval",   value=f"Every {CHECK_INTERVAL_MINUTES} min",            inline=True)
    em.add_field(name="👁️ Watched Items",  value=str(len(bot._watched_items)),                     inline=True)
    em.add_field(name="🕐 Scheduled",       value=str(len(bot._scheduled)),                         inline=True)
    em.set_footer(text="Roblox Update Tracker")
    await interaction.response.send_message(embed=em)

@bot.tree.command(name="reset_settings", description="Reset all bot settings to defaults (Admin only)")
@admin_check()
async def cmd_reset_settings(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    bot._warnings        = {}
    bot._log_channel_id  = None
    bot._audit_log       = []
    bot._ping_role_id    = None
    bot._autorole_id     = None
    bot._scheduled       = []
    bot._prefix          = "!"
    bot._filters         = {"client": True, "devforum": True, "incident": True}
    bot._alert_threshold = 0.0
    bot._watched_items   = {}
    bot._muted_until     = 0
    bot._automod_enabled = True
    bot._automod_words   = list(DEFAULT_BAD_WORDS)
    bot._automod_penalty = "timeout_week"
    bot._automod_strikes = {}
    bot._automod_log     = []
    bot._banned_users    = {}
    bot._welcome_channel_id = None
    bot._welcome_message = "Welcome {mention} to **{server}**! Enjoy your stay."
    bot._verified_role_id = None
    bot._suggestion_channel_id = None
    bot._reaction_roles = {}
    bot._giveaways = {}
    bot._temp_vcs = {}
    bot._ticket_counter = 0
    bot._save_data()
    em = discord.Embed(title="🔄 Settings Reset", description="All bot settings have been reset to defaults.",
                       colour=0xe63946, timestamp=datetime.now(timezone.utc))
    em.set_footer(text=f"Reset by {interaction.user}")
    await interaction.response.send_message(embed=em)
    bot._add_audit("reset_settings", interaction.user, "All settings reset to defaults")

@bot.tree.command(name="backup_settings", description="Export all current bot settings as a JSON backup")
@admin_check()
async def cmd_backup_settings(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    await interaction.response.defer(ephemeral=True)
    data = {
        "exported_at":     datetime.now(timezone.utc).isoformat(),
        "prefix":          bot._prefix,
        "log_channel_id":  bot._log_channel_id,
        "ping_role_id":    bot._ping_role_id,
        "autorole_id":     bot._autorole_id,
        "filters":         bot._filters,
        "alert_threshold": bot._alert_threshold,
        "warnings_count":  {uid: len(w) for uid, w in bot._warnings.items()},
        "watched_items":   {str(k): v for k, v in bot._watched_items.items()},
        "scheduled_count": len(bot._scheduled),
        "audit_entries":   len(bot._audit_log),
        "automod_enabled": bot._automod_enabled,
        "automod_words":   bot._automod_words,
        "automod_penalty": bot._automod_penalty,
        "banned_users":    bot._banned_users,
    }
    import io
    buf = io.BytesIO(json.dumps(data, indent=2).encode())
    buf.seek(0)
    fname = f"bot_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    await interaction.followup.send(
        content="✅ Here is your settings backup:",
        file=discord.File(buf, filename=fname),
        ephemeral=True,
    )
    bot._add_audit("backup_settings", interaction.user, "Settings backup exported")

# ---------------------------------------------------------------------------
# 🧹 Purge
# ---------------------------------------------------------------------------
@bot.tree.command(name="purge", description="Bulk-delete up to 100 messages in a channel")
@app_commands.describe(amount="Number of messages to delete (1–100)",
                        channel="Channel to purge (defaults to current)")
@mod_check()
async def cmd_purge(interaction: discord.Interaction,
                    amount: int,
                    channel: discord.TextChannel | None = None) -> None:
    bot._command_uses += 1
    ch: discord.TextChannel | None = channel or interaction.channel
    if not ch or not isinstance(ch, discord.TextChannel):
        await interaction.response.send_message("❌ Invalid channel.", ephemeral=True)
        return
    if not 1 <= amount <= 100:
        await interaction.response.send_message("❌ Amount must be between 1 and 100.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        deleted = await ch.purge(limit=amount)
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to delete messages there.", ephemeral=True)
        return
    except discord.HTTPException as e:
        await interaction.followup.send(f"❌ Failed to purge: {e}", ephemeral=True)
        return
    await interaction.followup.send(
        f"🗑️ Deleted **{len(deleted)}** message(s) from {ch.mention}.", ephemeral=True
    )
    em = discord.Embed(title="🗑️ Channel Purged", colour=0xff6b35,
                       timestamp=datetime.now(timezone.utc))
    em.add_field(name="Channel",  value=ch.mention,              inline=True)
    em.add_field(name="Deleted",  value=str(len(deleted)),        inline=True)
    em.add_field(name="By",       value=str(interaction.user),    inline=True)
    bot._add_audit("purge", interaction.user, f"Purged {len(deleted)} messages in #{ch.name}")
    await bot._log_action(em)

# ---------------------------------------------------------------------------
# 🛡️ Anti-raid
# ---------------------------------------------------------------------------
@bot.tree.command(name="antiraid_on", description="Manually enable anti-raid lockdown (Admin only)")
@app_commands.describe(action="What to do with new joiners: kick or ban")
@admin_check()
async def cmd_antiraid_on(interaction: discord.Interaction,
                           action: str | None = None) -> None:
    bot._command_uses += 1
    if action and action.lower() in ("kick", "ban"):
        bot._antiraid_action = action.lower()
    bot._antiraid_enabled = True
    bot._save_data()
    em = discord.Embed(title="🚨 Anti-Raid Lockdown ENABLED", colour=0xe63946,
                       timestamp=datetime.now(timezone.utc))
    em.add_field(name="Action",   value=bot._antiraid_action.upper(), inline=True)
    em.add_field(name="Enabled by", value=str(interaction.user),      inline=True)
    em.set_footer(text="Use /antiraid_off to disable")
    await interaction.response.send_message(embed=em)
    bot._add_audit("antiraid_on", interaction.user, f"Lockdown enabled, action={bot._antiraid_action}")
    await bot._log_action(em)

@bot.tree.command(name="antiraid_off", description="Disable anti-raid lockdown (Admin only)")
@admin_check()
async def cmd_antiraid_off(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    bot._antiraid_enabled = False
    bot._join_times.clear()
    bot._save_data()
    em = discord.Embed(title="✅ Anti-Raid Lockdown DISABLED", colour=0x06d6a0,
                       timestamp=datetime.now(timezone.utc))
    em.add_field(name="Disabled by", value=str(interaction.user), inline=True)
    em.set_footer(text="New members will no longer be auto-kicked/banned")
    await interaction.response.send_message(embed=em)
    bot._add_audit("antiraid_off", interaction.user, "Lockdown disabled")
    await bot._log_action(em)

@bot.tree.command(name="antiraid_config", description="Configure auto-raid detection thresholds (Admin only)")
@app_commands.describe(threshold="Number of joins to trigger lockdown (default 10)",
                        window="Time window in seconds (default 10)",
                        action="Action on new joiners during lockdown: kick or ban (default kick)",
                        auto="Enable automatic detection (default true)")
@admin_check()
async def cmd_antiraid_config(interaction: discord.Interaction,
                               threshold: int | None = None,
                               window: int | None = None,
                               action: str | None = None,
                               auto: bool | None = None) -> None:
    bot._command_uses += 1
    if threshold is not None and threshold >= 2:
        bot._antiraid_threshold = threshold
    if window is not None and window >= 3:
        bot._antiraid_window = window
    if action and action.lower() in ("kick", "ban"):
        bot._antiraid_action = action.lower()
    if auto is not None:
        bot._antiraid_auto = auto
    bot._save_data()
    em = discord.Embed(title="⚙️ Anti-Raid Config Updated", colour=0x9b5de5,
                       timestamp=datetime.now(timezone.utc))
    em.add_field(name="Auto-detect",  value="✅ On" if bot._antiraid_auto else "❌ Off", inline=True)
    em.add_field(name="Threshold",    value=f"{bot._antiraid_threshold} joins",           inline=True)
    em.add_field(name="Window",       value=f"{bot._antiraid_window}s",                   inline=True)
    em.add_field(name="Action",       value=bot._antiraid_action.upper(),                 inline=True)
    em.add_field(name="Lockdown Now", value="🔴 ACTIVE" if bot._antiraid_enabled else "🟢 Off", inline=True)
    await interaction.response.send_message(embed=em)
    bot._add_audit("antiraid_config", interaction.user,
                   f"threshold={bot._antiraid_threshold} window={bot._antiraid_window}s "
                   f"action={bot._antiraid_action} auto={bot._antiraid_auto}")

@bot.tree.command(name="antiraid_status", description="Show current anti-raid configuration and status")
async def cmd_antiraid_status(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    now = time.time()
    recent = sum(1 for t in bot._join_times if t >= now - bot._antiraid_window)
    em = discord.Embed(
        title="🛡️ Anti-Raid Status",
        colour=0xe63946 if bot._antiraid_enabled else 0x06d6a0,
        timestamp=datetime.now(timezone.utc),
    )
    em.add_field(name="Lockdown",      value="🔴 **ACTIVE**" if bot._antiraid_enabled else "🟢 Inactive", inline=True)
    em.add_field(name="Auto-detect",   value="✅ On" if bot._antiraid_auto else "❌ Off",                 inline=True)
    em.add_field(name="Threshold",     value=f"{bot._antiraid_threshold} joins / {bot._antiraid_window}s", inline=True)
    em.add_field(name="Action",        value=bot._antiraid_action.upper(),                                  inline=True)
    em.add_field(name="Recent Joins",  value=f"{recent} in last {bot._antiraid_window}s",                  inline=True)
    em.set_footer(text="Use /antiraid_config to change thresholds • /antiraid_on|off to toggle")
    await interaction.response.send_message(embed=em)

# ---------------------------------------------------------------------------
# 🔑 Role-based permissions setup
# ---------------------------------------------------------------------------
@bot.tree.command(name="set_mod_role", description="Set which role can use moderation commands (Admin only)")
@app_commands.describe(role="Role to grant mod permissions (leave blank to clear)")
@admin_check()
async def cmd_set_mod_role(interaction: discord.Interaction, role: discord.Role | None = None) -> None:
    bot._command_uses += 1
    bot._mod_role_id = role.id if role else None
    bot._save_data()
    if role:
        await interaction.response.send_message(f"✅ **{role.name}** can now use moderation commands.")
    else:
        await interaction.response.send_message("✅ Mod role cleared — only Discord permissions apply.")
    bot._add_audit("set_mod_role", interaction.user, f"Mod role → {role}" if role else "Mod role cleared")

@bot.tree.command(name="set_admin_role", description="Set which role can use admin commands (Admin only)")
@app_commands.describe(role="Role to grant admin permissions (leave blank to clear)")
@admin_check()
async def cmd_set_admin_role(interaction: discord.Interaction, role: discord.Role | None = None) -> None:
    bot._command_uses += 1
    bot._admin_role_id = role.id if role else None
    bot._save_data()
    if role:
        await interaction.response.send_message(f"✅ **{role.name}** can now use admin commands.")
    else:
        await interaction.response.send_message("✅ Admin role cleared — only Administrator permission applies.")
    bot._add_audit("set_admin_role", interaction.user, f"Admin role → {role}" if role else "Admin role cleared")

# ---------------------------------------------------------------------------
# 🤬 Auto-mod commands
# ---------------------------------------------------------------------------
@bot.tree.command(name="automod_enable", description="Enable automatic profanity moderation (Admin only)")
@app_commands.describe(penalty="Punishment at strike 3+: timeout_week or kick (default: timeout_week)")
@admin_check()
async def cmd_automod_enable(interaction: discord.Interaction, penalty: str | None = None) -> None:
    bot._command_uses += 1
    if penalty and penalty.lower() in ("kick", "timeout_week"):
        bot._automod_penalty = penalty.lower()
    bot._automod_enabled = True
    bot._save_data()
    em = discord.Embed(title="✅ Auto-Mod ENABLED", colour=0x06d6a0,
                       timestamp=datetime.now(timezone.utc))
    em.add_field(name="Strike 1–2",  value="10-minute timeout + message deleted", inline=False)
    em.add_field(name="Strike 3+",   value="Kicked from server" if bot._automod_penalty == "kick"
                                     else "7-day timeout",                        inline=False)
    em.add_field(name="Penalty",     value=bot._automod_penalty,                  inline=True)
    em.add_field(name="Words watched", value=str(len(bot._automod_words)),        inline=True)
    em.set_footer(text="Message Content Intent must be enabled in Discord Dev Portal")
    await interaction.response.send_message(embed=em)
    bot._add_audit("automod_enable", interaction.user, f"penalty={bot._automod_penalty}")

@bot.tree.command(name="automod_disable", description="Disable automatic profanity moderation (Admin only)")
@admin_check()
async def cmd_automod_disable(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    bot._automod_enabled = False
    bot._save_data()
    await interaction.response.send_message("✅ Auto-mod disabled.")
    bot._add_audit("automod_disable", interaction.user)

@bot.tree.command(name="automod_addword", description="Add a word to the profanity filter (Admin only)")
@app_commands.describe(word="Word to block (case-insensitive, leet-speak resistant)")
@admin_check()
async def cmd_automod_addword(interaction: discord.Interaction, word: str) -> None:
    bot._command_uses += 1
    w = word.lower().strip()
    if w in bot._automod_words:
        await interaction.response.send_message(f"⚠️ `{w}` is already in the filter.", ephemeral=True)
        return
    bot._automod_words.append(w)
    bot._save_data()
    await interaction.response.send_message(f"✅ Added `{w}` to the filter. ({len(bot._automod_words)} words total)")
    bot._add_audit("automod_addword", interaction.user, f"Added: {w}")

@bot.tree.command(name="automod_removeword", description="Remove a word from the profanity filter (Admin only)")
@app_commands.describe(word="Word to remove")
@admin_check()
async def cmd_automod_removeword(interaction: discord.Interaction, word: str) -> None:
    bot._command_uses += 1
    w = word.lower().strip()
    if w not in bot._automod_words:
        await interaction.response.send_message(f"⚠️ `{w}` is not in the filter.", ephemeral=True)
        return
    bot._automod_words.remove(w)
    bot._save_data()
    await interaction.response.send_message(f"✅ Removed `{w}` from the filter. ({len(bot._automod_words)} words total)")
    bot._add_audit("automod_removeword", interaction.user, f"Removed: {w}")

@bot.tree.command(name="automod_status", description="Show auto-mod configuration and word list")
@mod_check()
async def cmd_automod_status(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    em = discord.Embed(title="🤬 Auto-Mod Status",
                       colour=0x06d6a0 if bot._automod_enabled else 0xe63946,
                       timestamp=datetime.now(timezone.utc))
    em.add_field(name="Status",    value="✅ Enabled" if bot._automod_enabled else "❌ Disabled", inline=True)
    em.add_field(name="Penalty",   value=bot._automod_penalty,                                    inline=True)
    em.add_field(name="Words",     value=str(len(bot._automod_words)),                             inline=True)
    em.add_field(name="Strike 1–2", value="10-min timeout + message deleted",                     inline=False)
    em.add_field(name="Strike 3+",  value="Kicked" if bot._automod_penalty == "kick"
                                    else "7-day timeout",                                          inline=False)
    words_display = ", ".join(f"`{w}`" for w in sorted(bot._automod_words))
    if len(words_display) > 900:
        words_display = words_display[:900] + "…"
    em.add_field(name="Blocked Words", value=words_display or "None", inline=False)
    em.set_footer(text="Use /automod_addword and /automod_removeword to edit the list")
    await interaction.response.send_message(embed=em, ephemeral=True)

@bot.tree.command(name="automod_logs", description="Show recent auto-mod violations (last 20)")
@app_commands.describe(member="Filter to a specific member (optional)", page="Page number (default 1)")
@mod_check()
async def cmd_automod_logs(interaction: discord.Interaction,
                           member: discord.Member | None = None,
                           page: int = 1) -> None:
    bot._command_uses += 1
    entries = list(reversed(bot._automod_log))
    if member:
        entries = [e for e in entries if e["uid"] == str(member.id)]
    per_page = 10
    total_pages = max(1, (len(entries) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    slice_ = entries[(page - 1) * per_page : page * per_page]
    em = discord.Embed(title="🤬 Auto-Mod Violation Log", colour=0xe63946,
                       timestamp=datetime.now(timezone.utc))
    if not slice_:
        em.description = "No violations recorded yet."
    else:
        lines = []
        for e in slice_:
            try:
                ts = datetime.fromisoformat(e["ts"])
                ts_str = discord.utils.format_dt(ts, style="R")
            except Exception:
                ts_str = e["ts"][:16]
            lines.append(
                f"**{e['user']}** — `{e['word']}` | Strike **{e['strikes']}** | {e['action']} | #{e['channel']} | {ts_str}"
            )
        em.description = "\n".join(lines)
    em.set_footer(text=f"Page {page}/{total_pages} • {len(entries)} total violation(s)")
    if member:
        em.set_author(name=str(member), icon_url=member.display_avatar.url)
    await interaction.response.send_message(embed=em, ephemeral=True)

@bot.tree.command(name="automod_clearstrikes", description="Clear strike count for a user (Admin only)")
@app_commands.describe(member="Member to clear strikes for")
@admin_check()
async def cmd_automod_clearstrikes(interaction: discord.Interaction, member: discord.Member) -> None:
    bot._command_uses += 1
    uid = str(member.id)
    old = bot._automod_strikes.pop(uid, 0)
    await interaction.response.send_message(
        f"✅ Cleared **{old}** strike(s) for {member.mention}.", ephemeral=True
    )
    bot._add_audit("automod_clearstrikes", interaction.user, f"Cleared {old} strikes for {member} ({member.id})")

@bot.tree.command(name="strike_leaderboard", description="Show the top users by total auto-mod strikes")
@mod_check()
async def cmd_strike_leaderboard(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    totals: dict[str, int] = {}
    user_names: dict[str, str] = {}
    for entry in bot._automod_log:
        uid = entry["uid"]
        totals[uid] = totals.get(uid, 0) + 1
        user_names[uid] = entry["user"]
    for uid, count in bot._automod_strikes.items():
        totals[uid] = max(totals.get(uid, 0), count)
    if not totals:
        await interaction.response.send_message(
            "📊 No strikes recorded yet — the server is clean!", ephemeral=True
        )
        return
    ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:15]
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, count) in enumerate(ranked):
        prefix = medals[i] if i < 3 else f"**{i+1}.**"
        name = user_names.get(uid, f"<@{uid}>")
        current = bot._automod_strikes.get(uid, 0)
        lines.append(f"{prefix} {name} — **{count}** violation(s)  *(active strikes: {current})*")
    em = discord.Embed(
        title="📊 Strike Leaderboard — Repeat Offenders",
        description="\n".join(lines),
        colour=0xe63946,
        timestamp=datetime.now(timezone.utc),
    )
    em.set_footer(text="Based on all recorded violations • /automod_clearstrikes to reset a user")
    await interaction.response.send_message(embed=em, ephemeral=True)

# ---------------------------------------------------------------------------
# 🚨 User reports
# ---------------------------------------------------------------------------
@bot.tree.command(name="user_report", description="Anonymously report a member to the moderation team")
@app_commands.describe(
    reported="The member you are reporting",
    reason="Describe what happened",
    attachment="Screenshot or evidence (required)",
    attachment2="Second screenshot (optional)",
    attachment3="Third screenshot (optional)",
)
async def cmd_user_report(
    interaction: discord.Interaction,
    reported: discord.Member,
    reason: str,
    attachment: discord.Attachment,
    attachment2: discord.Attachment | None = None,
    attachment3: discord.Attachment | None = None,
) -> None:
    bot._command_uses += 1
    if reported.id == interaction.user.id:
        await interaction.response.send_message("❌ You can't report yourself.", ephemeral=True)
        return
    if reported.bot:
        await interaction.response.send_message("❌ You can't report a bot.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    attachments = [a for a in [attachment, attachment2, attachment3] if a is not None]
    ts = datetime.now(timezone.utc)
    report_id = f"RPT-{int(ts.timestamp())}"
    bot._reports.append({
        "id":         report_id,
        "ts":         ts.isoformat(),
        "reporter_id": str(interaction.user.id),
        "reported":   f"{reported} ({reported.id})",
        "reported_id": str(reported.id),
        "reason":     reason,
        "attachments": [a.url for a in attachments],
        "guild":      str(interaction.guild.id) if interaction.guild else "unknown",
    })
    bot._reports = bot._reports[-200:]
    bot._save_data()
    def make_embed(show_reporter: bool) -> discord.Embed:
        em = discord.Embed(title=f"🚨 Member Report  •  {report_id}", colour=0xff6b6b, timestamp=ts)
        em.add_field(name="Reported User", value=f"{reported.mention} (`{reported}` · {reported.id})", inline=False)
        em.add_field(name="Reason",        value=reason,                                                 inline=False)
        if show_reporter:
            em.add_field(name="Reporter", value=f"{interaction.user.mention} (`{interaction.user}`)",   inline=True)
        else:
            em.add_field(name="Reporter", value="*Anonymous*",                                           inline=True)
        em.add_field(name="Channel",       value=interaction.channel.mention,                            inline=True)
        em.add_field(name="Evidence",      value=f"{len(attachments)} attachment(s) below",              inline=True)
        em.set_thumbnail(url=reported.display_avatar.url)
        em.set_footer(text=f"Server: {interaction.guild.name if interaction.guild else 'DM'}  •  {report_id}")
        return em
    log_em = make_embed(show_reporter=True)
    log_posted = False
    if bot._log_channel_id:
        ch = bot.get_channel(bot._log_channel_id)
        if isinstance(ch, discord.abc.Messageable):
            try:
                files = []
                for att in attachments:
                    import io
                    data = await att.read()
                    files.append(discord.File(io.BytesIO(data), filename=att.filename))
                await ch.send(content="@here **New member report received**", embed=log_em, files=files)
                log_posted = True
            except Exception as e:
                log.warning("Could not post report to log channel: %s", e)
    dm_count = 0
    guild = interaction.guild
    if guild and (bot._mod_role_id or bot._admin_role_id):
        target_role_ids = [r for r in [bot._mod_role_id, bot._admin_role_id] if r]
        notified_ids: set[int] = set()
        for role_id in target_role_ids:
            role = guild.get_role(role_id)
            if not role: continue
            for member in role.members:
                if member.bot or member.id in notified_ids: continue
                notified_ids.add(member.id)
                try:
                    dm_em = make_embed(show_reporter=True)
                    dm_files = []
                    for att in attachments:
                        import io
                        data = await att.read()
                        dm_files.append(discord.File(io.BytesIO(data), filename=att.filename))
                    await member.send(
                        content=f"🚨 **New report in {guild.name}** — {report_id}",
                        embed=dm_em,
                        files=dm_files,
                    )
                    dm_count += 1
                except Exception:
                    pass
    confirm_em = discord.Embed(
        title="✅ Report Submitted",
        description=(
            f"Your report against **{reported}** has been received.\n"
            f"**Report ID:** `{report_id}`\n\n"
            f"{'Moderators have been notified via DM.' if dm_count else ''}"
            f"{'Report also posted in the mod log channel.' if log_posted else ''}"
        ),
        colour=0x06d6a0,
        timestamp=ts,
    )
    confirm_em.set_footer(text="Your identity is kept anonymous from other members.")
    await interaction.followup.send(embed=confirm_em, ephemeral=True)
    bot._add_audit("user_report", interaction.user, f"Reported {reported} ({reported.id}) — {report_id}")

@bot.tree.command(name="view_reports", description="Browse member reports (Mod only)")
@app_commands.describe(
    member="Filter to reports about a specific member (optional)",
    status="Filter by status: all, open, resolved, dismissed (default: open)",
    page="Page number (default 1)",
)
@mod_check()
async def cmd_view_reports(
    interaction: discord.Interaction,
    member: discord.Member | None = None,
    status: str = "open",
    page: int = 1,
) -> None:
    bot._command_uses += 1
    status = status.lower()
    valid_statuses = ("all", "open", "resolved", "dismissed")
    if status not in valid_statuses:
        await interaction.response.send_message(f"❌ Invalid status. Choose from: {', '.join(valid_statuses)}", ephemeral=True)
        return
    entries = list(reversed(bot._reports))
    if member:
        entries = [e for e in entries if e["reported_id"] == str(member.id)]
    if status != "all":
        entries = [e for e in entries if e.get("status", "open") == status]
    per_page = 5
    total_pages = max(1, (len(entries) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    slice_ = entries[(page - 1) * per_page : page * per_page]
    em = discord.Embed(title="📋 Member Reports", colour=0xff6b6b,
                       timestamp=datetime.now(timezone.utc))
    if not slice_:
        em.description = "No reports found matching those filters."
    else:
        for e in slice_:
            s = e.get("status", "open")
            icon = {"open": "🔴", "resolved": "✅", "dismissed": "🔕"}.get(s, "🔴")
            try:
                ts = datetime.fromisoformat(e["ts"])
                ts_str = discord.utils.format_dt(ts, style="R")
            except Exception: ts_str = e["ts"][:16]
            n_att = len(e.get("attachments", []))
            em.add_field(
                name=f"{icon} `{e['id']}` — {e['reported']}",
                value=(
                    f"**Reason:** {e['reason'][:120]}{'…' if len(e['reason']) > 120 else ''}\n"
                    f"**Status:** {s}  •  **Evidence:** {n_att} file(s)  •  {ts_str}\n"
                    f"**Attachments:** " + (
                        " ".join(f"[{i+1}]({u})" for i, u in enumerate(e.get("attachments", [])))
                        or "none"
                    )
                ),
                inline=False,
            )
    em.set_footer(text=f"Page {page}/{total_pages} • {len(entries)} report(s) • "
                       f"Use /resolve_report or /dismiss_report to act")
    if member:
        em.set_author(name=str(member), icon_url=member.display_avatar.url)
    await interaction.response.send_message(embed=em, ephemeral=True)

@bot.tree.command(name="resolve_report", description="Mark a report as resolved (Mod only)")
@app_commands.describe(report_id="The report ID e.g. RPT-1749602405", note="Optional closing note")
@mod_check()
async def cmd_resolve_report(interaction: discord.Interaction, report_id: str, note: str = "") -> None:
    bot._command_uses += 1
    rid = report_id.upper().strip()
    for e in bot._reports:
        if e["id"] == rid:
            e["status"] = "resolved"
            e["closed_by"] = str(interaction.user)
            e["close_note"] = note
            bot._save_data()
            await interaction.response.send_message(
                f"✅ Report `{rid}` marked as **resolved**." + (f"\nNote: {note}" if note else ""),
                ephemeral=True,
            )
            bot._add_audit("resolve_report", interaction.user, f"{rid}" + (f" — {note}" if note else ""))
            return
    await interaction.response.send_message(f"❌ Report `{rid}` not found.", ephemeral=True)

@bot.tree.command(name="dismiss_report", description="Dismiss a report (Mod only)")
@app_commands.describe(report_id="The report ID e.g. RPT-1749602405", reason="Reason for dismissal")
@mod_check()
async def cmd_dismiss_report(interaction: discord.Interaction, report_id: str, reason: str = "") -> None:
    bot._command_uses += 1
    rid = report_id.upper().strip()
    for e in bot._reports:
        if e["id"] == rid:
            e["status"] = "dismissed"
            e["closed_by"] = str(interaction.user)
            e["close_note"] = reason
            bot._save_data()
            await interaction.response.send_message(
                f"🔕 Report `{rid}` **dismissed**." + (f"\nReason: {reason}" if reason else ""),
                ephemeral=True,
            )
            bot._add_audit("dismiss_report", interaction.user, f"{rid}" + (f" — {reason}" if reason else ""))
            return
    await interaction.response.send_message(f"❌ Report `{rid}` not found.", ephemeral=True)

# ---------------------------------------------------------------------------
# 🔄 Force sync (owner/admin utility)
# ---------------------------------------------------------------------------
@bot.tree.command(name="sync", description="Force re-sync all slash commands to this server (Admin only)")
@admin_check()
async def cmd_sync(interaction: discord.Interaction) -> None:
    bot._command_uses += 1
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if not guild:
        await interaction.followup.send("❌ This command must be used in a server.", ephemeral=True)
        return
    try:
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        await interaction.followup.send(
            f"✅ Synced **{len(synced)}** command(s) to **{guild.name}**.", ephemeral=True
        )
        log.info("Manual sync: %d commands to guild %s", len(synced), guild.id)
    except Exception as e:
        await interaction.followup.send(f"❌ Sync failed: {e}", ephemeral=True)

# ---------------------------------------------------------------------------
# ✨ Server Management Slash Commands
# ---------------------------------------------------------------------------
@bot.tree.command(name="setwelcome", description="Set the welcome channel and message (Admin)")
@app_commands.describe(channel="Welcome channel", message="Welcome message (use {mention}, {server}, {user})")
@admin_check()
async def cmd_setwelcome_slash(interaction: discord.Interaction, channel: discord.TextChannel, message: str) -> None:
    bot._welcome_channel_id = channel.id
    bot._welcome_message = message
    bot._save_data()
    await interaction.response.send_message(f"✅ Welcome channel set to {channel.mention} with message:\n{message}")

@bot.tree.command(name="verify", description="Send a verification panel")
@mod_check()
async def cmd_verify_slash(interaction: discord.Interaction) -> None:
    if not bot._verified_role_id:
        await interaction.response.send_message("❌ Verified role not set. Admins use `/setverifiedrole`.", ephemeral=True)
        return
    role = interaction.guild.get_role(bot._verified_role_id)
    if not role:
        await interaction.response.send_message("❌ Verified role not found.", ephemeral=True)
        return
    view = discord.ui.View()
    btn = discord.ui.Button(label="Verify", style=discord.ButtonStyle.green)
    async def callback(inter: discord.Interaction):
        if role in inter.user.roles:
            await inter.response.send_message("You are already verified.", ephemeral=True)
            return
        try:
            await inter.user.add_roles(role)
            await inter.response.send_message("✅ You are now verified!", ephemeral=True)
        except discord.Forbidden:
            await inter.response.send_message("❌ I can't assign roles.", ephemeral=True)
    btn.callback = callback
    view.add_item(btn)
    em = discord.Embed(title="Verification", description="Click the button below to verify yourself.", colour=0x06d6a0)
    await interaction.channel.send(embed=em, view=view)
    await interaction.response.send_message("Verification panel sent.", ephemeral=True)

@bot.tree.command(name="setverifiedrole", description="Set the role assigned on verification (Admin)")
@app_commands.describe(role="Role to assign")
@admin_check()
async def cmd_setverifiedrole_slash(interaction: discord.Interaction, role: discord.Role) -> None:
    bot._verified_role_id = role.id
    bot._save_data()
    await interaction.response.send_message(f"✅ Verified role set to {role.mention}.")

@bot.tree.command(name="suggest", description="Submit a suggestion")
@app_commands.describe(suggestion="Your suggestion")
async def cmd_suggest_slash(interaction: discord.Interaction, suggestion: str) -> None:
    if not bot._suggestion_channel_id:
        await interaction.response.send_message("❌ Suggestion channel not configured.", ephemeral=True)
        return
    ch = interaction.guild.get_channel(bot._suggestion_channel_id)
    if not isinstance(ch, discord.TextChannel):
        await interaction.response.send_message("❌ Suggestion channel not found.", ephemeral=True)
        return
    em = discord.Embed(description=suggestion, colour=0x9b5de5, timestamp=datetime.now(timezone.utc))
    em.set_author(name=f"Suggestion by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
    msg = await ch.send(embed=em)
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")
    await interaction.response.send_message("✅ Suggestion posted!", ephemeral=True)

@bot.tree.command(name="setsuggestchannel", description="Set the channel for suggestions (Admin)")
@app_commands.describe(channel="Channel for suggestions")
@admin_check()
async def cmd_setsuggestchannel_slash(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
    bot._suggestion_channel_id = channel.id
    bot._save_data()
    await interaction.response.send_message(f"✅ Suggestion channel set to {channel.mention}.")

@bot.tree.command(name="reactionrole", description="Add/Remove a reaction role (Admin)")
@app_commands.describe(action="add or remove", channel="Channel of the message", message_id="Message ID",
                        emoji="Emoji", role="Role (for add)")
@admin_check()
async def cmd_reactionrole_slash(interaction: discord.Interaction, action: str,
                                  channel: discord.TextChannel, message_id: str,
                                  emoji: str, role: discord.Role | None = None) -> None:
    try:
        msg_id = int(message_id)
    except ValueError:
        await interaction.response.send_message("❌ Invalid message ID.", ephemeral=True)
        return
    if action.lower() == "add":
        if not role:
            await interaction.response.send_message("❌ Role is required for add.", ephemeral=True)
            return
        msg = await channel.fetch_message(msg_id)
        try: await msg.add_reaction(emoji)
        except Exception:
            await interaction.response.send_message("❌ Cannot add that emoji.", ephemeral=True)
            return
        bot._reaction_roles.setdefault(str(msg_id), {})[emoji] = role.id
        bot._save_data()
        await interaction.response.send_message(f"✅ Reaction role added: {emoji} → {role.mention}")
    elif action.lower() == "remove":
        if str(msg_id) in bot._reaction_roles and emoji in bot._reaction_roles[str(msg_id)]:
            del bot._reaction_roles[str(msg_id)][emoji]
            if not bot._reaction_roles[str(msg_id)]:
                del bot._reaction_roles[str(msg_id)]
            bot._save_data()
            await interaction.response.send_message(f"✅ Reaction role removed for {emoji}.")
        else:
            await interaction.response.send_message("❌ Not found.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Action must be 'add' or 'remove'.", ephemeral=True)

@bot.tree.command(name="ticket", description="Create a ticket channel")
@app_commands.describe(reason="Reason for ticket")
async def cmd_ticket_slash(interaction: discord.Interaction, reason: str = "No reason") -> None:
    guild = interaction.guild
    bot._ticket_counter += 1
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    if bot._mod_role_id:
        mr = guild.get_role(bot._mod_role_id)
        if mr: overwrites[mr] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    if bot._admin_role_id:
        ar = guild.get_role(bot._admin_role_id)
        if ar: overwrites[ar] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    category = discord.utils.get(guild.categories, name="Tickets")
    if not category:
        try: category = await guild.create_category("Tickets")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Cannot create category.", ephemeral=True)
            return
    try:
        ch = await guild.create_text_channel(name=f"ticket-{bot._ticket_counter}", category=category, overwrites=overwrites)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Cannot create channel.", ephemeral=True)
        return
    em = discord.Embed(title="📩 Ticket Created", description=f"Hello {interaction.user.mention}, your ticket is ready.\nReason: {reason}\nUse `/close` to close.", colour=0x4cc9f0)
    await ch.send(embed=em)
    bot._save_data()
    await interaction.response.send_message(f"✅ Ticket created: {ch.mention}", ephemeral=True)

@bot.tree.command(name="close", description="Close this ticket channel")
async def cmd_close_slash(interaction: discord.Interaction) -> None:
    ch = interaction.channel
    if not isinstance(ch, discord.TextChannel) or not ch.name.startswith("ticket-"):
        await interaction.response.send_message("❌ Not a ticket channel.", ephemeral=True)
        return
    try: await ch.delete(reason="Ticket closed.")
    except discord.Forbidden: await interaction.response.send_message("❌ Cannot delete channel.", ephemeral=True)

@bot.tree.command(name="giveaway", description="Start a giveaway (Mod)")
@app_commands.describe(prize="Prize", duration_minutes="Duration in minutes", winners="Number of winners")
@mod_check()
async def cmd_giveaway_slash(interaction: discord.Interaction, prize: str, duration_minutes: int, winners: int) -> None:
    if duration_minutes < 1:
        await interaction.response.send_message("❌ Duration must be at least 1 minute.", ephemeral=True)
        return
    end_time = time.time() + duration_minutes * 60
    em = discord.Embed(title="🎉 Giveaway!", description=f"**Prize:** {prize}\nReact with 🎉 to enter!\nEnds: <t:{int(end_time)}:R>", colour=0xf72585)
    await interaction.response.send_message(embed=em)
    msg = await interaction.original_response()
    await msg.add_reaction("🎉")
    bot._giveaways[msg.id] = {"prize": prize, "end_time": end_time, "winners": winners, "channel_id": interaction.channel_id}
    bot._save_data()

@bot.tree.command(name="tempvc", description="Create a temporary voice channel (Admin)")
@app_commands.describe(name="Channel name", duration_minutes="Minutes until deletion")
@admin_check()
async def cmd_tempvc_slash(interaction: discord.Interaction, name: str, duration_minutes: int) -> None:
    if duration_minutes < 1:
        await interaction.response.send_message("❌ Duration must be at least 1 minute.", ephemeral=True)
        return
    try:
        vc = await interaction.guild.create_voice_channel(name)
        bot._temp_vcs[vc.id] = {"expires": time.time() + duration_minutes * 60, "creator_id": interaction.user.id}
        bot._save_data()
        await interaction.response.send_message(f"🎤 Temporary VC {vc.mention} created. Deletes in {duration_minutes} min.")
    except discord.Forbidden:
        await interaction.response.send_message("❌ Cannot create voice channel.", ephemeral=True)

@bot.tree.command(name="ask", description="Ask the AI anything")
@app_commands.describe(question="Your question")
async def cmd_ask(interaction: discord.Interaction, question: str) -> None:
    await interaction.response.defer()
    answer = await bot._chat_with_llm(question)
    if answer is None:
        answer = bot._get_chat_response(question)
    await interaction.followup.send(answer)

# ---------------------------------------------------------------------------
# ENTRY POINT – THIS MAKES THE BOT ACTUALLY RUN
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        bot.run(BOT_TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        print("\n" + "="*60)
        print("❌  PRIVILEGED INTENTS REQUIRED")
        print("="*60)
        print("Enable these in Discord Developer Portal → Bot → Privileged Gateway Intents:")
        print("  • Message Content Intent  (required for auto-mod)")
        print("  • Server Members Intent   (required for autorole, antiraid, dm_blast)")
        print("URL: https://discord.com/developers/applications/")
        print("="*60 + "\n")
