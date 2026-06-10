       """
Roblox Update Tracker Bot — Ultimate Edition
"""

import asyncio
import logging
import os
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

    async def setup_hook(self):
        await self.tree.sync()
        self.poll_updates.start()
        self.rotate_presence.start()
        self.poll_ugc_prices.start()

    async def on_ready(self):
        self._start_time = time.time()
        log.info("Logged in as %s (%s)", self.user, self.user.id)
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
    em.add_field(name="Members",   value=f"{group.get('memberCount',0):,}", inline=True)
    em.add_field(name="Owner",     value=group.get("owner",{}).get("username","?"), inline=True)
    em.add_field(name="Public",    value="✅ Yes" if group.get("publicEntryAllowed") else "🔒 No", inline=True)
    if group.get("description"):
        em.add_field(name="Description", value=group["description"][:300], inline=False)
    em.set_footer(text="Roblox Groups API")
    await interaction.followup.send(embed=em)


@bot.tree.command(name="badge_check", description="Check if a user has a specific badge")
@app_commands.describe(username="Roblox username", badge_id="Badge ID to check")
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
    em.add_field(name="Result", value="✅ Has this badge!" if has_it else "❌ Does not have this badge", inline=False)
    await interaction.followup.send(embed=em)


@bot.tree.command(name="robux_rates", description="Current Robux to USD exchange and DevEx rates")
async def cmd_robux_rates(interaction: discord.Interaction):
    bot._command_uses += 1
    em = discord.Embed(title="💰 Robux Exchange Rates", colour=0x06d6a0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Buy Rate",          value="$0.0035 per Robux\n(~286 R$ per $1)",  inline=False)
    em.add_field(name="DevEx Rate",        value="$0.0035 per Robux earned\n(Min 30,000 R$)", inline=False)
    em.add_field(name="Roblox Premium",    value="$4.99 → 450 R$\n$9.99 → 1,000 R$\n$19.99 → 2,200 R$", inline=False)
    em.add_field(name="Gift Card",         value="$10 → 800 R$\n$25 → 2,000 R$\n$50 → 4,500 R$", inline=False)
    em.set_footer(text="Rates as of 2026 — check roblox.com for latest")
    await interaction.response.send_message(embed=em)


@bot.tree.command(name="trade_calculator", description="Calculate if a Roblox trade is worth it based on RAP")
@app_commands.describe(your_rap="Your items total RAP", their_rap="Their items total RAP")
async def cmd_trade_calculator(interaction: discord.Interaction, your_rap: int, their_rap: int):
    bot._command_uses += 1
    diff = their_rap - your_rap
    pct = (diff / your_rap * 100) if your_rap else 0
    if diff > 0:
        verdict = f"✅ **Good trade!** You gain R${diff:,} RAP ({pct:+.1f}%)"
        color = 0x06d6a0
    elif diff < 0:
        verdict = f"❌ **Bad trade!** You lose R${abs(diff):,} RAP ({pct:+.1f}%)"
        color = 0xe63946
    else:
        verdict = "🟰 **Even trade** — equal RAP value"
        color = 0xaaaaaa
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
        await interaction.followup.send("❌ Could not fetch item. Is it a limited?")
        return
    name = details.get("name", f"Item {aid}") if details else f"Item {aid}"
    rap  = resale.get("recentAveragePrice", 0)
    orig = resale.get("originalPrice", 0)
    vol  = resale.get("volume", 0)
    em = discord.Embed(title=f"📈 Limited: {name}", url=f"https://www.roblox.com/catalog/{aid}",
                       colour=0xffd166, timestamp=datetime.now(timezone.utc))
    em.add_field(name="RAP (Avg)",      value=f"R${rap:,}",  inline=True)
    em.add_field(name="Original Price", value=f"R${orig:,}", inline=True)
    em.add_field(name="Total Volume",   value=f"{vol:,}",    inline=True)
    if orig and rap:
        roi = ((rap - orig) / orig * 100)
        em.add_field(name="ROI vs Original", value=f"{roi:+.1f}%", inline=True)
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
        await interaction.followup.send("❌ Already watching 20 items max. Use `/ugc_unwatch` to remove one.")
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
    em.add_field(name="Current Price", value=f"R${price:,}",                       inline=True)
    em.add_field(name="Watching",      value=f"{len(bot._watched_items)}/20 items", inline=True)
    em.set_footer(text="Checks every 30 min for price changes")
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
        em.description = "No items watched. Use `/ugc_watch <asset_id>` to add one!"
    em.set_footer(text=f"{len(bot._watched_items)}/20 items • checks every 30 min")
    await interaction.response.send_message(embed=em)


@bot.tree.command(name="alert_threshold", description="Only alert on UGC price changes above X percent")
@app_commands.describe(percent="Minimum % change to trigger an alert (0 = any change)")
async def cmd_alert_threshold(interaction: discord.Interaction, percent: float):
    bot._command_uses += 1
    bot._alert_threshold = max(0.0, percent)
    await interaction.response.send_message(
        f"✅ UGC price alerts will only fire when price changes by **{bot._alert_threshold:.1f}%** or more."
    )


@bot.tree.command(name="mute_updates", description="Pause auto-alerts for X hours")
@app_commands.describe(hours="Number of hours to mute alerts (0 to unmute)")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_mute_updates(interaction: discord.Interaction, hours: float):
    bot._command_uses += 1
    if hours <= 0:
        bot._muted_until = 0
        await interaction.response.send_message("🔔 Alerts have been **unmuted**.")
    else:
        bot._muted_until = time.time() + hours * 3600
        await interaction.response.send_message(f"🔕 Alerts muted for **{hours}h**. Resumes <t:{int(bot._muted_until)}:R>.")


@bot.tree.command(name="filter_updates", description="Choose which update types to receive alerts for")
@app_commands.describe(
    client="Alert on Roblox client updates",
    devforum="Alert on new DevForum announcements",
    incident="Alert on Roblox status incidents",
)
@app_commands.checks.has_permissions(administrator=True)
async def cmd_filter_updates(interaction: discord.Interaction,
                              client: bool = True, devforum: bool = True, incident: bool = True):
    bot._command_uses += 1
    bot._filters = {"client": client, "devforum": devforum, "incident": incident}
    em = discord.Embed(title="🔍 Update Filters Set", colour=0x4cc9f0)
    em.add_field(name="🎮 Client Updates",      value="✅ On" if client   else "❌ Off", inline=True)
    em.add_field(name="📢 DevForum Alerts",     value="✅ On" if devforum else "❌ Off", inline=True)
    em.add_field(name="🚨 Incident Alerts",     value="✅ On" if incident else "❌ Off", inline=True)
    await interaction.response.send_message(embed=em)


@bot.tree.command(name="server_stats", description="Show bot usage stats for this server")
async def cmd_server_stats(interaction: discord.Interaction):
    bot._command_uses += 1
    uptime = int(time.time() - bot._start_time)
    h, rem = divmod(uptime, 3600)
    m, _ = divmod(rem, 60)
    em = discord.Embed(title="📈 Server Stats", colour=0x9b5de5, timestamp=datetime.now(timezone.utc))
    em.add_field(name="💬 Total Commands Used",  value=str(bot._command_uses),              inline=True)
    em.add_field(name="⏱️ Bot Uptime",           value=f"{h}h {m}m",                        inline=True)
    em.add_field(name="🔔 Alert Channel",        value=f"<#{bot.update_channel_id}>" if bot.update_channel_id else "Not set", inline=True)
    em.add_field(name="👁️ Watched UGC Items",   value=str(len(bot._watched_items)),         inline=True)
    em.add_field(name="📋 Version Changes",      value=str(len(bot._client_changelog)),      inline=True)
    em.add_field(name="🔕 Muted",               value="Yes" if time.time() < bot._muted_until else "No", inline=True)
    await interaction.response.send_message(embed=em)


@bot.tree.command(name="poll", description="Create a quick Roblox poll")
@app_commands.describe(question="Poll question", option_a="First option", option_b="Second option")
async def cmd_poll(interaction: discord.Interaction, question: str, option_a: str, option_b: str):
    bot._command_uses += 1
    em = discord.Embed(title=f"📊 {question}", colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="🅰️ Option A", value=option_a, inline=True)
    em.add_field(name="🅱️ Option B", value=option_b, inline=True)
    em.set_footer(text=f"Poll by {interaction.user.display_name}")
    msg = await interaction.response.send_message(embed=em)
    message = await interaction.original_response()
    await message.add_reaction("🅰️")
    await message.add_reaction("🅱️")


@bot.tree.command(name="uptime_history", description="Roblox incident history for the last 30 days")
async def cmd_uptime_history(interaction: discord.Interaction):
    bot._command_uses += 1
    await interaction.response.defer()
    incidents = await bot.get_incident_history(10)
    em = discord.Embed(title="📅 Roblox Incident History (Last 30 Days)", colour=0xff6b35, timestamp=datetime.now(timezone.utc))
    if incidents:
        for inc in incidents:
            icon = {"none":"🟢","minor":"🟡","major":"🟠","critical":"🔴"}.get(inc["impact"],"⚪")
            em.add_field(name=f"{icon} {inc['name']}",
                         value=f"Status: `{inc['status'].replace('_',' ').title()}` | {inc['created_at']}\n[View]({inc['url']})",
                         inline=False)
    else:
        em.description = "✅ No incidents found in the last 30 days!"
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
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(channel="Channel to post alerts in")
async def cmd_set_update_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    bot.update_channel_id = channel.id
    await interaction.response.send_message(f"✅ Alerts will now post in {channel.mention}.")

@cmd_set_update_channel.error
async def set_channel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You need Administrator permission.", ephemeral=True)


@bot.tree.command(name="help_roblox", description="Show all commands")
async def cmd_help(interaction: discord.Interaction):
    bot._command_uses += 1
    em = discord.Embed(title="🤖 Roblox Update Tracker — All Commands", colour=0x4cc9f0)
    categories = {
        "📡 Updates & Versions": [
            ("/roblox_version",    "Current live Roblox version"),
            ("/latest_updates",    "Latest DevForum announcements"),
            ("/release_notes",     "Official release notes"),
            ("/upcoming_features", "Beta & upcoming features"),
            ("/changelog",         "Last 10 version changes"),
            ("/compare_versions",  "Compare two version strings"),
            ("/deploy_history",    "CDN deploy log"),
        ],
        "🔒 Security & Status": [
            ("/security_updates",  "Security patches and incidents"),
            ("/status",            "Full platform status"),
            ("/uptime_history",    "Incident history last 30 days"),
        ],
        "🎮 Games & Players": [
            ("/game_status",       "Check a game by Place ID"),
            ("/random_game",       "Get a random popular game"),
            ("/player_lookup",     "Look up a Roblox player"),
            ("/group_info",        "Look up a Roblox group"),
            ("/badge_check",       "Check if a user has a badge"),
        ],
        "💰 Economy & UGC": [
            ("/robux_rates",       "Robux to USD exchange rates"),
            ("/trade_calculator",  "Calculate if a trade is worth it"),
            ("/limited_tracker",   "Track a limited item's RAP"),
            ("/ugc_trending",      "Trending UGC items"),
            ("/ugc_price",         "Check UGC item resale price"),
            ("/ugc_watch",         "Watch item for price alerts"),
            ("/ugc_unwatch",       "Stop watching an item"),
            ("/ugc_watchlist",     "Show watched items"),
            ("/alert_threshold",   "Set min % for price alerts"),
        ],
        "⚙️ Bot Management": [
            ("/stats",             "Bot stats and uptime"),
            ("/server_stats",      "Server usage stats"),
            ("/poll",              "Create a quick poll"),
            ("/mute_updates",      "Pause alerts for X hours (Admin)"),
            ("/filter_updates",    "Choose alert types (Admin)"),
            ("/set_update_channel","Set alert channel (Admin)"),
        ],
    }
    for category, cmds in categories.items():
        val = "\n".join([f"`{n}` — {d}" for n,d in cmds])
        em.add_field(name=category, value=val, inline=False)
    em.set_footer(text=f"Polls every {CHECK_INTERVAL_MINUTES} min • @everyone pings {'on' if PING_EVERYONE else 'off'}")
    await interaction.response.send_message(embed=em)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    bot.run(BOT_TOKEN)
