"""
Roblox Update Tracker Bot — Full Edition
Features: version tracking, security updates, status, stats, changelog,
game status, incident alerts, @everyone pings, and rich presence.
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
PING_EVERYONE          = True   # set False to disable @everyone pings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("roblox-bot")

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
ROBLOX_CLIENT_VERSION_URL  = "https://clientsettingscdn.roblox.com/v2/client-version/WindowsPlayer"
ROBLOX_STUDIO_VERSION_URL  = "https://clientsettingscdn.roblox.com/v2/client-version/WindowsStudio"
DEVFORUM_ANNOUNCEMENTS_URL = "https://devforum.roblox.com/c/announcements/official-roblox-staff/191.json"
DEVFORUM_RELEASES_URL      = "https://devforum.roblox.com/c/updates/releases/36.json"
DEVFORUM_BETA_URL          = "https://devforum.roblox.com/c/updates/beta-features/22.json"
ROBLOX_DEPLOY_LOG_URL      = "https://setup.rbxcdn.com/DeployHistory.txt"
ROBLOX_STATUS_SUMMARY_URL  = "https://status.roblox.com/api/v2/summary.json"
ROBLOX_INCIDENTS_URL       = "https://status.roblox.com/api/v2/incidents/unresolved.json"
ROBLOX_GAME_API_URL        = "https://games.roblox.com/v1/games?universeIds={}"
ROBLOX_UNIVERSE_URL        = "https://apis.roblox.com/universes/v1/places/{}/universe"

# Rich presence game activity cycling
PRESENCE_ACTIVITIES = [
    ("Tracking Roblox updates",  discord.ActivityType.watching),
    ("for new Studio builds",    discord.ActivityType.watching),
    ("Roblox v{client}",         discord.ActivityType.playing),
    ("DevForum announcements",   discord.ActivityType.watching),
    ("for security patches",     discord.ActivityType.watching),
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

        # Cached state
        self._last_client_version: str | None = None
        self._last_studio_version: str | None = None
        self._last_incident_id:    str | None = None
        self._last_devforum_id:    int | None = None
        self._last_check_time:     str        = "Never"

        # Changelog history (last 10 versions)
        self._client_changelog: list[dict] = []
        self._studio_changelog: list[dict] = []

    async def setup_hook(self):
        await self.tree.sync()
        self.poll_updates.start()
        self.rotate_presence.start()

    async def on_ready(self):
        self._start_time = time.time()
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        channel = self.get_channel(self.update_channel_id)
        if channel:
            cv, sv = await asyncio.gather(self.get_client_version(), self.get_studio_version())
            em = discord.Embed(
                title="🚀 Roblox Update Tracker — Online",
                description="Bot is online and monitoring for updates!",
                colour=0x4cc9f0,
                timestamp=datetime.now(timezone.utc),
            )
            em.add_field(name="🎮 Client", value=f"`{cv or 'N/A'}`", inline=True)
            em.add_field(name="🛠️ Studio", value=f"`{sv or 'N/A'}`", inline=True)
            em.set_footer(text=f"Polling every {CHECK_INTERVAL_MINUTES} min")
            await channel.send(embed=em)

    # -----------------------------------------------------------------------
    # HTTP helpers
    # -----------------------------------------------------------------------
    async def _session_(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers={"User-Agent": "RobloxUpdateBot/2.0"})
        return self._session

    async def _json(self, url: str):
        s = await self._session_()
        try:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
        except Exception as e:
            log.warning("fetch_json failed %s: %s", url, e)
        return None

    async def _text(self, url: str):
        s = await self._session_()
        try:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return await r.text()
        except Exception as e:
            log.warning("fetch_text failed %s: %s", url, e)
        return None

    # -----------------------------------------------------------------------
    # Data fetchers
    # -----------------------------------------------------------------------
    async def get_client_version(self) -> str | None:
        d = await self._json(ROBLOX_CLIENT_VERSION_URL)
        return d.get("clientVersionUpload") or d.get("version") if d else None

    async def get_studio_version(self) -> str | None:
        d = await self._json(ROBLOX_STUDIO_VERSION_URL)
        return d.get("clientVersionUpload") or d.get("version") if d else None

    async def get_devforum_posts(self, url: str, limit: int = 5) -> list[dict]:
        d = await self._json(url)
        if not d:
            return []
        topics = d.get("topic_list", {}).get("topics", [])
        return [
            {
                "id":    t.get("id"),
                "title": t.get("title", "Untitled"),
                "url":   f"https://devforum.roblox.com/t/{t.get('slug','')}/{t.get('id','')}",
                "posts_count": t.get("posts_count", 0),
                "created_at":  t.get("created_at", ""),
            }
            for t in topics[:limit]
        ]

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
        return [
            {
                "id":     inc.get("id"),
                "name":   inc.get("name", "Unknown"),
                "status": inc.get("status", ""),
                "impact": inc.get("impact", "none"),
                "url":    inc.get("shortlink", "https://status.roblox.com"),
                "created_at": inc.get("created_at", ""),
                "latest_update": (inc.get("incident_updates") or [{}])[0].get("body", "No details")[:300],
            }
            for inc in d.get("incidents", [])
        ]

    async def get_game_info(self, universe_id: int) -> dict | None:
        d = await self._json(ROBLOX_GAME_API_URL.format(universe_id))
        if d and d.get("data"):
            return d["data"][0]
        return None

    async def get_universe_id(self, place_id: int) -> int | None:
        d = await self._json(ROBLOX_UNIVERSE_URL.format(place_id))
        return d.get("universeId") if d else None

    # -----------------------------------------------------------------------
    # Rich presence rotation
    # -----------------------------------------------------------------------
    @tasks.loop(minutes=5)
    async def rotate_presence(self):
        cv = self._last_client_version or "unknown"
        label, atype = PRESENCE_ACTIVITIES[self._presence_index % len(PRESENCE_ACTIVITIES)]
        label = label.replace("{client}", cv)
        await self.change_presence(activity=discord.Activity(type=atype, name=label))
        self._presence_index += 1

    @rotate_presence.before_loop
    async def before_presence(self):
        await self.wait_until_ready()

    # -----------------------------------------------------------------------
    # Background polling
    # -----------------------------------------------------------------------
    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def poll_updates(self):
        self._last_check_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        channel = self.get_channel(self.update_channel_id)
        if not channel:
            return

        ping = "@everyone\n" if PING_EVERYONE else ""

        # --- Client version ---
        cv = await self.get_client_version()
        if cv and cv != self._last_client_version:
            if self._last_client_version is not None:
                self._client_changelog.append({"version": cv, "time": self._last_check_time})
                self._client_changelog = self._client_changelog[-10:]
                em = discord.Embed(
                    title="🎮 New Roblox Client Version Deployed!",
                    description=f"**`{cv}`**",
                    colour=0xff6b35,
                    timestamp=datetime.now(timezone.utc),
                )
                em.set_footer(text="Roblox Update Tracker")
                await channel.send(content=ping, embed=em)
            self._last_client_version = cv

        # --- Studio version ---
        sv = await self.get_studio_version()
        if sv and sv != self._last_studio_version:
            if self._last_studio_version is not None:
                self._studio_changelog.append({"version": sv, "time": self._last_check_time})
                self._studio_changelog = self._studio_changelog[-10:]
                em = discord.Embed(
                    title="🛠️ New Roblox Studio Version Deployed!",
                    description=f"**`{sv}`**",
                    colour=0x4cc9f0,
                    timestamp=datetime.now(timezone.utc),
                )
                em.set_footer(text="Roblox Update Tracker")
                await channel.send(content=ping, embed=em)
            self._last_studio_version = sv

        # --- DevForum announcements ---
        posts = await self.get_devforum_posts(DEVFORUM_ANNOUNCEMENTS_URL, limit=1)
        if posts:
            latest = posts[0]
            if latest["id"] != self._last_devforum_id:
                if self._last_devforum_id is not None:
                    em = discord.Embed(
                        title="📢 New DevForum Announcement",
                        description=f"[{latest['title']}]({latest['url']})",
                        colour=0xffd166,
                        timestamp=datetime.now(timezone.utc),
                    )
                    em.set_footer(text="Roblox DevForum")
                    await channel.send(content=ping, embed=em)
                self._last_devforum_id = latest["id"]

        # --- Incidents ---
        incidents = await self.get_unresolved_incidents()
        if incidents:
            latest_inc = incidents[0]
            if latest_inc["id"] != self._last_incident_id:
                if self._last_incident_id is not None:
                    impact_colors = {"none": 0x06d6a0, "minor": 0xffd166, "major": 0xff6b35, "critical": 0xe63946}
                    color = impact_colors.get(latest_inc["impact"], 0xaaaaaa)
                    em = discord.Embed(
                        title=f"🚨 Roblox Incident: {latest_inc['name']}",
                        description=latest_inc["latest_update"],
                        colour=color,
                        timestamp=datetime.now(timezone.utc),
                    )
                    em.add_field(name="Status", value=latest_inc["status"].replace("_", " ").title(), inline=True)
                    em.add_field(name="Impact", value=latest_inc["impact"].title(), inline=True)
                    em.add_field(name="Details", value=f"[View incident]({latest_inc['url']})", inline=False)
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
# Slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="roblox_version", description="Current live Roblox client version")
async def cmd_roblox_version(interaction: discord.Interaction):
    await interaction.response.defer()
    v = await bot.get_client_version()
    em = discord.Embed(title="🎮 Roblox Client Version", colour=0xff6b35, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Version", value=f"`{v}`" if v else "Unavailable")
    em.set_footer(text="Live from Roblox CDN")
    await interaction.followup.send(embed=em)


@bot.tree.command(name="studio_version", description="Current live Roblox Studio version")
async def cmd_studio_version(interaction: discord.Interaction):
    await interaction.response.defer()
    v = await bot.get_studio_version()
    em = discord.Embed(title="🛠️ Roblox Studio Version", colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Version", value=f"`{v}`" if v else "Unavailable")
    em.set_footer(text="Live from Roblox CDN")
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
    sec_keywords = ["security", "patch", "hotfix", "vulnerability", "exploit", "critical", "fix"]
    sec_posts = [p for p in posts if any(k in p["title"].lower() for k in sec_keywords)]

    em = discord.Embed(title="🔒 Security Updates & Patches", colour=0xe63946, timestamp=datetime.now(timezone.utc))

    if incidents:
        for inc in incidents[:3]:
            impact_map = {"none": "🟢", "minor": "🟡", "major": "🟠", "critical": "🔴"}
            icon = impact_map.get(inc["impact"], "⚪")
            em.add_field(
                name=f"{icon} {inc['name']}",
                value=f"Status: `{inc['status'].replace('_',' ').title()}`\n{inc['latest_update'][:150]}\n[View]({inc['url']})",
                inline=False,
            )
    else:
        em.add_field(name="✅ No Active Incidents", value="Roblox status is currently clean.", inline=False)

    if sec_posts:
        em.add_field(name="━━━━━━━━━━━━━━━━━━", value="**Security DevForum Posts**", inline=False)
        for p in sec_posts[:3]:
            em.add_field(name=p["title"], value=f"[Read more]({p['url']})", inline=False)

    em.set_footer(text="status.roblox.com + DevForum")
    await interaction.followup.send(embed=em)


@bot.tree.command(name="status", description="Full Roblox platform status")
async def cmd_status(interaction: discord.Interaction):
    await interaction.response.defer()
    data = await bot.get_status_summary()
    if not data:
        await interaction.followup.send("❌ Could not reach Roblox status page.")
        return
    page = data.get("status", {})
    indicator = page.get("indicator", "none")
    description = page.get("description", "Unknown")
    color_map = {"none": 0x06d6a0, "minor": 0xffd166, "major": 0xff6b35, "critical": 0xe63946}
    color = color_map.get(indicator, 0xaaaaaa)
    icon_map = {"none": "🟢", "minor": "🟡", "major": "🟠", "critical": "🔴"}
    icon = icon_map.get(indicator, "⚪")
    em = discord.Embed(
        title=f"{icon} Roblox Platform Status",
        description=f"**{description}**",
        colour=color,
        timestamp=datetime.now(timezone.utc),
    )
    for comp in data.get("components", [])[:10]:
        status_val = comp.get("status", "unknown").replace("_", " ").title()
        status_icon = "🟢" if comp.get("status") == "operational" else "🔴"
        em.add_field(name=comp.get("name", "?"), value=f"{status_icon} {status_val}", inline=True)
    em.set_footer(text="status.roblox.com")
    await interaction.followup.send(embed=em)


@bot.tree.command(name="stats", description="Bot stats — uptime, last check, versions cached")
async def cmd_stats(interaction: discord.Interaction):
    uptime_secs = int(time.time() - bot._start_time)
    hours, rem = divmod(uptime_secs, 3600)
    minutes, secs = divmod(rem, 60)
    uptime_str = f"{hours}h {minutes}m {secs}s"
    em = discord.Embed(title="📊 Bot Stats", colour=0x4cc9f0, timestamp=datetime.now(timezone.utc))
    em.add_field(name="⏱️ Uptime",             value=uptime_str,                                    inline=True)
    em.add_field(name="🕐 Last Check",         value=bot._last_check_time,                          inline=True)
    em.add_field(name="🔄 Check Interval",     value=f"Every {CHECK_INTERVAL_MINUTES} minutes",     inline=True)
    em.add_field(name="🎮 Client Version",     value=f"`{bot._last_client_version or 'N/A'}`",      inline=True)
    em.add_field(name="🛠️ Studio Version",     value=f"`{bot._last_studio_version or 'N/A'}`",      inline=True)
    em.add_field(name="📢 Last Incident ID",   value=f"`{bot._last_incident_id or 'None'}`",        inline=True)
    em.add_field(name="🔔 @everyone Pings",    value="Enabled" if PING_EVERYONE else "Disabled",    inline=True)
    em.add_field(name="📋 Client Updates Logged", value=str(len(bot._client_changelog)),            inline=True)
    em.add_field(name="📋 Studio Updates Logged", value=str(len(bot._studio_changelog)),            inline=True)
    em.set_footer(text="Roblox Update Tracker")
    await interaction.response.send_message(embed=em)


@bot.tree.command(name="changelog", description="Last 10 detected version changes")
async def cmd_changelog(interaction: discord.Interaction):
    em = discord.Embed(title="📅 Version Changelog", colour=0xffd166, timestamp=datetime.now(timezone.utc))

    if bot._client_changelog:
        val = "\n".join([f"`{e['version']}` — {e['time']}" for e in reversed(bot._client_changelog)])
        em.add_field(name="🎮 Client Updates", value=val, inline=False)
    else:
        em.add_field(name="🎮 Client Updates", value="No updates detected this session yet.", inline=False)

    if bot._studio_changelog:
        val = "\n".join([f"`{e['version']}` — {e['time']}" for e in reversed(bot._studio_changelog)])
        em.add_field(name="🛠️ Studio Updates", value=val, inline=False)
    else:
        em.add_field(name="🛠️ Studio Updates", value="No updates detected this session yet.", inline=False)

    em.set_footer(text="Changelog resets when bot restarts — use Railway for persistence")
    await interaction.response.send_message(embed=em)


@bot.tree.command(name="game_status", description="Check status of a Roblox game by Place ID")
@app_commands.describe(place_id="The Roblox Place ID of the game")
async def cmd_game_status(interaction: discord.Interaction, place_id: str):
    await interaction.response.defer()
    try:
        pid = int(place_id)
    except ValueError:
        await interaction.followup.send("❌ Please enter a valid numeric Place ID.")
        return

    universe_id = await bot.get_universe_id(pid)
    if not universe_id:
        await interaction.followup.send("❌ Could not find that game. Check the Place ID.")
        return

    game = await bot.get_game_info(universe_id)
    if not game:
        await interaction.followup.send("❌ Could not fetch game info.")
        return

    playing = game.get("playing", 0)
    visits  = game.get("visits", 0)
    name    = game.get("name", "Unknown")
    creator = game.get("creator", {}).get("name", "Unknown")
    active  = game.get("isActive", False)
    updated = game.get("updated", "")[:10]

    em = discord.Embed(
        title=f"🎮 {name}",
        url=f"https://www.roblox.com/games/{pid}",
        colour=0x06d6a0 if active else 0xe63946,
        timestamp=datetime.now(timezone.utc),
    )
    em.add_field(name="Status",    value="🟢 Active" if active else "🔴 Inactive", inline=True)
    em.add_field(name="Playing",   value=f"{playing:,}",                           inline=True)
    em.add_field(name="Visits",    value=f"{visits:,}",                            inline=True)
    em.add_field(name="Creator",   value=creator,                                  inline=True)
    em.add_field(name="Updated",   value=updated,                                  inline=True)
    em.set_footer(text="Roblox Games API")
    await interaction.followup.send(embed=em)


@bot.tree.command(name="deploy_history", description="Last 15 CDN deploy log entries")
async def cmd_deploy_history(interaction: discord.Interaction):
    await interaction.response.defer()
    entries = await bot.get_deploy_history(15)
    em = discord.Embed(title="📦 CDN Deploy History", colour=0x4cc9f0)
    if entries:
        text = "\n".join(entries)
        em.description = f"```\n{text[-3900:]}\n```"
    else:
        em.description = "Could not retrieve deploy history."
    await interaction.followup.send(embed=em)


@bot.tree.command(name="set_update_channel", description="Set the alert channel (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(channel="The channel to post update alerts in")
async def cmd_set_update_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    bot.update_channel_id = channel.id
    await interaction.response.send_message(
        f"✅ Update alerts will now be posted in {channel.mention}.", ephemeral=True
    )

@cmd_set_update_channel.error
async def set_channel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You need Administrator permission.", ephemeral=True)


@bot.tree.command(name="help_roblox", description="Show all commands")
async def cmd_help(interaction: discord.Interaction):
    em = discord.Embed(title="🤖 Roblox Update Tracker — Commands", colour=0x4cc9f0)
    cmds = [
        ("/roblox_version",    "Current live Roblox client version"),
        ("/studio_version",    "Current live Roblox Studio version"),
        ("/latest_updates",    "Latest DevForum announcements"),
        ("/release_notes",     "Official Roblox release notes"),
        ("/upcoming_features", "Beta & upcoming features"),
        ("/security_updates",  "Security patches and incidents"),
        ("/status",            "Full Roblox platform status"),
        ("/stats",             "Bot uptime, last check, cached versions"),
        ("/changelog",         "Last 10 detected version changes"),
        ("/game_status",       "Check a Roblox game by Place ID"),
        ("/deploy_history",    "Last 15 CDN deploy log entries"),
        ("/set_update_channel","Set alert channel (Admin only)"),
    ]
    for name, desc in cmds:
        em.add_field(name=name, value=desc, inline=False)
    em.set_footer(text=f"Polls every {CHECK_INTERVAL_MINUTES} min • @everyone pings {'on' if PING_EVERYONE else 'off'}")
    await interaction.response.send_message(embed=em)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    bot.run(BOT_TOKEN)
