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
    # collapse repeated letters (fuuuck → fuck)
    text = re.sub(r'(.)\1{2,}', r'\1\1', text)
    # collapse spaced-out letters (f u c k → fuck)
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
        # Privileged intents — enable both in Discord Dev Portal → Bot → Privileged Gateway Intents
        # intents.members = True          # needed for autorole, dm_blast, antiraid
        intents.message_content = True    # needed for automod
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

        self.update_channel_id: int = UPDATE_CHANNEL_ID
        self._session: aiohttp.ClientSession | None = None
        self._start_time: float = time.time()
        self._presence_index: int = 0
        self._command_uses: int = 0
        self._muted_until: float = 0

        # Filter: which update types to alert (all on by default)
        self._filters: dict = {"client": True, "devforum": True, "incident": True}

        # Alert threshold for UGC price changes (%)
        self._alert_threshold: float = 0.0  # 0 = any change

        # Version state
        self._last_client_version: str | None = None
        self._last_incident_id:    str | None = None
        self._last_devforum_id:    int | None = None
        self._last_check_time:     str        = "Never"

        # Changelog
        self._client_changelog: list[dict] = []

        # UGC watching
        self._watched_items: dict[int, dict] = {}

        # Moderation
        self._warnings: dict[str, list[dict]] = {}

        # Logging
        self._log_channel_id: int | None = None
        self._audit_log: list[dict] = []

        # Roles
        self._ping_role_id: int | None = None
        self._autorole_id: int | None = None

        # Scheduled announcements
        self._scheduled: list[dict] = []

        # Config
        self._prefix: str = "!"

        # Anti-raid
        self._antiraid_enabled:   bool  = False
        self._antiraid_auto:      bool  = True
        self._antiraid_threshold: int   = 10
        self._antiraid_window:    int   = 10
        self._antiraid_action:    str   = "kick"
        self._join_times: collections.deque = collections.deque()

        # Role-based permissions
        self._mod_role_id:   int | None = None   # can use mod commands
        self._admin_role_id: int | None = None   # can use admin commands

        # Auto-mod
        self._automod_enabled: bool      = False
        self._automod_words:   list[str] = list(DEFAULT_BAD_WORDS)
        self._automod_strikes: dict[str, int] = {}   # uid -> strike count (resets on restart)
        self._automod_penalty: str = "timeout_week"  # "kick" or "timeout_week"
        self._automod_log: list[dict] = []            # recent violations, kept last 100
        self._reports:     list[dict] = []            # member reports, kept last 200

        self._load_data()

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------
    DATA_FILE = "bot_data.json"

    def _load_data(self):
        try:
            with open(self.DATA_FILE, "r") as f:
                d = json.load(f)
            self._warnings      = d.get("warnings", {})
            self._log_channel_id= d.get("log_channel_id")
            self._audit_log     = d.get("audit_log", [])
            self._ping_role_id  = d.get("ping_role_id")
            self._autorole_id   = d.get("autorole_id")
            self._scheduled     = d.get("scheduled", [])
            self._prefix        = d.get("prefix", "!")
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

    def _add_audit(self, action: str, user: discord.User | discord.Member, detail: str = ""):
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
        # Clear any previously-registered global commands so Discord stops showing them
        # (guild-specific commands synced in on_ready replace them with instant propagation)
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        self.poll_updates.start()
        self.rotate_presence.start()
        self.poll_ugc_prices.start()
        self.check_scheduled.start()

    async def on_ready(self):
        self._start_time = time.time()
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        # Sync commands to every guild immediately (instant vs. up-to-1-hour global delay)
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                log.info("Synced commands to guild %s (%s)", guild.name, guild.id)
            except Exception as e:
                log.warning("Failed to sync to guild %s: %s", guild.id, e)
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

    # -----------------------------------------------------------------------
    # HTTP helpers
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # Data fetchers
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # Presence rotation
    # -----------------------------------------------------------------------
    @tasks.loop(minutes=5)
    async def rotate_presence(self):
        cv = self._last_client_version or "unknown"
        label, atype = PRESENCE_ACTIVITIES[self._presence_index % len(PRESENCE_ACTIVITIES)]
        await self.change_presence(activity=discord.Activity(type=atype, name=label.replace("{client}", cv)))
        self._presence_index += 1

    @rotate_presence.before_loop
    async def before_presence(self):
        await self.wait_until_ready()

    # -----------------------------------------------------------------------
    # UGC price polling
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # Scheduled announcements
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # Auto-role + anti-raid on join
    # -----------------------------------------------------------------------
    async def on_member_join(self, member: discord.Member):
        now = time.time()

        # --- Anti-raid: track join rate ---
        self._join_times.append(now)
        # Purge entries outside the window
        while self._join_times and self._join_times[0] < now - self._antiraid_window:
            self._join_times.popleft()

        # Auto-trigger lockdown if threshold breached
        if (self._antiraid_auto
                and not self._antiraid_enabled
                and len(self._join_times) >= self._antiraid_threshold):
            self._antiraid_enabled = True
            log.warning("Anti-raid triggered! %d joins in %ds", len(self._join_times), self._antiraid_window)
            alert_em = discord.Embed(
                title="🚨 ANTI-RAID LOCKDOWN TRIGGERED",
                description=(
                    f"**{len(self._join_times)} members** joined in the last "
                    f"**{self._antiraid_window}s** — lockdown activated!\n"
                    f"Action: **{self._antiraid_action.upper()}** on new joiners.\n"
                    f"Use `/antiraid_off` to disable."
                ),
                colour=0xe63946,
                timestamp=datetime.now(timezone.utc),
            )
            await self._log_action(alert_em)
            if self._log_channel_id:
                ch = self.get_channel(self._log_channel_id)
                if ch:
                    try:
                        await ch.send("@here", embed=alert_em)
                    except Exception:
                        pass

        # --- Anti-raid: enforce lockdown ---
        if self._antiraid_enabled:
            try:
                reason = "Anti-raid lockdown — bot-enforced"
                if self._antiraid_action == "ban":
                    await member.ban(reason=reason, delete_message_days=0)
                else:
                    await member.kick(reason=reason)
                action_em = discord.Embed(
                    title=f"🛡️ Anti-Raid: Member {'Banned' if self._antiraid_action == 'ban' else 'Kicked'}",
                    colour=0xe63946,
                    timestamp=datetime.now(timezone.utc),
                )
                action_em.add_field(name="Member", value=f"{member} ({member.id})", inline=True)
                action_em.add_field(name="Action",  value=self._antiraid_action.title(),   inline=True)
                await self._log_action(action_em)
            except Exception as e:
                log.warning("Anti-raid action failed for %s: %s", member, e)
            return  # skip auto-role during lockdown

        # --- Auto-role ---
        if self._autorole_id:
            role = member.guild.get_role(self._autorole_id)
            if role:
                try:
                    await member.add_roles(role, reason="Auto-role on join")
                    em = discord.Embed(
                        title="👋 Member Joined — Auto-role Applied",
                        colour=0x06d6a0,
                        timestamp=datetime.now(timezone.utc),
                    )
                    em.add_field(name="Member", value=f"{member.mention} ({member})", inline=True)
                    em.add_field(name="Role",   value=role.mention,                   inline=True)
                    await self._log_action(em)
                except Exception as e:
                    log.warning("Auto-role failed for %s: %s", member, e)

    # -----------------------------------------------------------------------
    # Auto-mod
    # -----------------------------------------------------------------------
    async def on_message(self, message: discord.Message):
        if message.author.bot or not self._automod_enabled:
            return
        if not message.guild:
            return
        content = message.content
        if not content:
            return
        normalized = _normalize(content)
        triggered_word = next((w for w in self._automod_words if w in normalized), None)
        if not triggered_word:
            return
        # Delete the message
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
                # Strike 3+: kick or 1-week timeout
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
                # Strike 1-2: 10-minute timeout
                until = discord.utils.utcnow() + dt.timedelta(minutes=10)
                await member.timeout(until, reason=f"Auto-mod: profanity (strike {strikes}/3)")
                action_text = "**Timed out for 10 minutes**"
                color = 0xffd166
        except discord.Forbidden:
            action_text = "⚠️ Could not punish (missing permissions)"
            color = 0xaaaaaa
        # Warn in channel
        warn_em = discord.Embed(
            title="🤬 Language Warning",
            description=(
                f"{member.mention} your message was removed for inappropriate language.\n"
                f"Strike **{strikes}/3** — {action_text}."
            ),
            colour=color,
            timestamp=datetime.now(timezone.utc),
        )
        warn_em.set_footer(text="3 strikes = kick or 7-day timeout")
        try:
            await message.channel.send(embed=warn_em, delete_after=15)
        except Exception:
            pass
        log_em = discord.Embed(title="🤬 Auto-mod: Profanity Detected", colour=color,
                               timestamp=datetime.now(timezone.utc))
        log_em.add_field(name="Member",  value=f"{member} ({member.id})", inline=True)
        log_em.add_field(name="Strikes", value=f"{strikes}/3",            inline=True)
        log_em.add_field(name="Action",  value=action_text,               inline=True)
        log_em.add_field(name="Channel", value=message.channel.mention,   inline=True)
        await self._log_action(log_em)
        # Persist to automod log
        self._automod_log.append({
            "ts":      datetime.now(timezone.utc).isoformat(),
            "user":    f"{member} ({member.id})",
            "uid":     str(member.id),
            "word":    triggered_word,
            "strikes": strikes,
            "action":  action_text,
            "channel": str(message.channel),
        })
        self._automod_log = self._automod_log[-100:]
        self._save_data()

    # -----------------------------------------------------------------------
    # Main polling
    # -----------------------------------------------------------------------
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

        # Client version
        if self._filters.get("client"):
            cv = await self.get_client_version()
            if cv and cv != self._last_client_version:
                if self._last_client_version is not None:
                    self._client_changelog.append({"version": cv, "time": self._last_check_time})
                    self._client_changelog = self._client_changelog[-10:]
                    em = discord.Embed(
                        title="🚨 Roblox Update Detected!",
                        description="This is a live update, Roblox is **patched**.",
                        colour=0xe63946,
                        timestamp=now,
                    )
                    em.add_field(name="Platform",     value="Windows",   inline=False)
                    em.add_field(name="Version Hash", value=f"`{cv}`",   inline=False)
                    em.add_field(name="Date",         value=ts,          inline=False)
                    em.set_footer(text=date_str)
                    await channel.send(content=ping, embed=em)
                self._last_client_version = cv

        # DevForum
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

        # Incidents
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
# Permission check helpers  (role-based OR Discord permission)
# ---------------------------------------------------------------------------
def mod_check():
    """Passes if: server admin, configured mod role, OR Manage Messages perm."""
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
        if m.guild_permissions.manage_messages or m.guild_permissions.kick_members \
                or m.guild_permissions.ban_members or m.guild_permissions.moderate_members:
            return True
        raise app_commands.MissingPermissions(["manage_messages"])
    return app_commands.check(predicate)


def admin_check():
    """Passes if: server admin OR configured admin role."""
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
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
    else:
        log.error("Unhandled command error: %s", error)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred.", ephemeral=True)

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="roblox_version", description="Current live Roblox client version")
async def cmd_roblox_version(interaction: discord.Interaction):
    await interaction.response.defer()
    v = await bot.get_client_version()
    now = datetime.now(timezone.utc)
    em = discord.Embed(title="🚨 Roblox Update Info", description="Current live version from Roblox CDN.", colour=0xe63946, timestamp=now)
    em.add_field(name="Platform",     value="Windows",           inline=False)
    em.add_field(name="Version Hash", value=f"`{v or 'N/A'}`",  inline=False)
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
    em.add_field(name="⏱️ Uptime",           value=f"{h}h {m}m {s}s",                         inline=True)
    em.add_field(name="🕐 Last Check",       value=bot._last_check_time,                       inline=True)
    em.add_field(name="🔄 Interval",         value=f"Every {CHECK_INTERVAL_MINUTES} min",      inline=True)
    em.add_field(name="🎮 Client Version",   value=f"`{bot._last_client_version or 'N/A'}`",   inline=True)
    em.add_field(name="🔔 @everyone",        value="Enabled" if PING_EVERYONE else "Disabled", inline=True)
    em.add_field(name="🔕 Muted",            value=muted,                                      inline=True)
    em.add_field(name="📋 Changelog",        value=f"{len(bot._client_changelog)} entries",    inline=True)
    em.add_field(name="👁️ Watched Items",    value=str(len(bot._watched_items)),               inline=True)
    em.add_field(name="💬 Commands Used",    value=str(bot._command_uses),                     inline=True)
    em.add_field(name="🔍 Active Filters",   value=", ".join(k for k,v in bot._filters.items() if v) or "None", inline=False)
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
    def parse(v: str):
        return [int(x) for x in v.replace("version-","").split(".") if x.isdigit()]
    try:
        v1, v2 = parse(version1), parse(version2)
        if v1 == v2:
            result, color = "🟰 **Identical** — same version", 0xaaaaaa
        elif v1 > v2:
            result, color = f"⬆️ **`{version1}` is newer** than `{version2}`", 0x06d6a0
        else:
            result, color = f"⬆️ **`{version2}` is newer** than `{version1}`", 0x4cc9f0
    except Exception:
        result, color = "❌ Could not parse one or both versions.", 0xe63946
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
    em.add_field(name="Status",  value="🟢 Active" if active else "🔴 Inactive",    inline=True)
    em.add_field(name="Playing", value=f"{game.get('playing',0):,}",                 inline=True)
    em.add_field(name="Visits",  value=f"{game.get('visits',0):,}",                  inline=True)
    em.add_field(name="Creator", value=game.get("creator",{}).get("name","?"),       inline=True)
    em.add_field(name="Updated", value=game.get("updated","?")[:10],                 inline=True)
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
    games = d["games"]
    game = random.choice(games)
    em = discord.Embed(title=f"🎲 Random Game: {game.get('name','?')}",
                       url=f"https://www.roblox.com/games/{game.get('placeId',0)}",
                       colour=0x9b5de5, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Playing", value=f"{game.get('playerCount',0):,}", inline=True)
    em.add_field(name="Visits",  value=f"{game.get('totalUpVotes',0):,} 👍", inline=True)
    em.set_footer(text="Roblox Games API")
    await interaction.followup.send(embed=em)


@bot.tree.command(name="player_lookup", description="Look up a Roblox player by username")
@app_commands.describe(username="Roblox username to look up")
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
    created = user.get("created","")[:10]
    em = discord.Embed(title=f"👤 {user.get('displayName','?')} (@{user.get('name','?')})",
                       url=f"https://www.roblox.com/users/{uid}/profile",
                       colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="User ID",    value=str(uid),          inline=True)
    em.add_field(name="Joined",     value=created,           inline=True)
    em.add_field(name="Friends",    value=str(friends),      inline=True)
    em.add_field(name="Badges",     value=f"{len(badges)}+", inline=True)
    em.add_field(name="Banned",     value="✅ No" if not user.get("isBanned") else "❌ Yes", inline=True)
    if user.get("description"):
        em.add_field(name="Bio", value=user["description"][:200], inline=False)
    em.set_footer(text="Roblox Users API")
    await interaction.followup.send(embed=em)


@bot.tree.command(name="group_info", description="Look up a Roblox group by ID")
@app_commands.describe(group_id="Roblox group ID")
async def cmd_group_info(interaction: discord.Interaction, group_id: str):
    bot._command_uses += 1
