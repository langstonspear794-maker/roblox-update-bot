"""
Roblox Update Tracker Bot
A Discord bot that monitors Roblox and Roblox Studio for new version
deployments, release notes, beta features, and DevForum announcements,
then posts them to your server automatically.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

import aiohttp
import discord
from bs4 import BeautifulSoup
from discord import app_commands
from discord.ext import tasks

# ---------------------------------------------------------------------------
# Configuration — edit these before running
# ---------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "your token here")
UPDATE_CHANNEL_ID = 0          # fallback channel; override with /set_update_channel
CHECK_INTERVAL_MINUTES = 15
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("roblox-bot")

# Roblox public API / feed endpoints
ROBLOX_CLIENT_VERSION_URL = (
    "https://clientsettingscdn.roblox.com/v2/client-version/WindowsPlayer"
)
ROBLOX_STUDIO_VERSION_URL = (
    "https://clientsettingscdn.roblox.com/v2/client-version/WindowsStudio"
)
DEVFORUM_ANNOUNCEMENTS_URL = (
    "https://devforum.roblox.com/c/announcements/official-roblox-staff/191.json"
)
DEVFORUM_RELEASES_URL = (
    "https://devforum.roblox.com/c/updates/releases/36.json"
)
DEVFORUM_BETA_URL = (
    "https://devforum.roblox.com/c/updates/beta-features/22.json"
)
ROBLOX_DEPLOY_LOG_URL = "https://setup.rbxcdn.com/DeployHistory.txt"
ROBLOX_STATUS_URL = "https://status.roblox.com/api/v2/incidents/unresolved.json"


# ---------------------------------------------------------------------------
# Bot client
# ---------------------------------------------------------------------------

class RobloxBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

        # Runtime state
        self.update_channel_id: int = UPDATE_CHANNEL_ID
        self._last_client_version: str | None = None
        self._last_studio_version: str | None = None
        self._last_incident_id: str | None = None
        self._last_devforum_post_id: int | None = None
        self._session: aiohttp.ClientSession | None = None

    async def setup_hook(self) -> None:
        await self.tree.sync()
        self.poll_updates.start()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "RobloxUpdateBot/1.0 (Discord bot)"}
            )
        return self._session

    async def _fetch_json(self, url: str) -> dict | list | None:
        session = await self._get_session()
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
        except Exception as exc:
            log.warning("Failed to fetch %s: %s", url, exc)
        return None

    async def _fetch_text(self, url: str) -> str | None:
        session = await self._get_session()
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.text()
        except Exception as exc:
            log.warning("Failed to fetch %s: %s", url, exc)
        return None

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    async def get_client_version(self) -> str | None:
        data = await self._fetch_json(ROBLOX_CLIENT_VERSION_URL)
        if data:
            return data.get("clientVersionUpload") or data.get("version")
        return None

    async def get_studio_version(self) -> str | None:
        data = await self._fetch_json(ROBLOX_STUDIO_VERSION_URL)
        if data:
            return data.get("clientVersionUpload") or data.get("version")
        return None

    async def get_devforum_posts(self, url: str, limit: int = 5) -> list[dict]:
        data = await self._fetch_json(url)
        if not data:
            return []
        topics = data.get("topic_list", {}).get("topics", [])
        results = []
        for t in topics[:limit]:
            results.append(
                {
                    "id": t.get("id"),
                    "title": t.get("title", "Untitled"),
                    "url": f"https://devforum.roblox.com/t/{t.get('slug', '')}/{t.get('id', '')}",
                    "created_at": t.get("created_at", ""),
                    "posts_count": t.get("posts_count", 0),
                }
            )
        return results

    async def get_deploy_history(self, lines: int = 15) -> list[str]:
        text = await self._fetch_text(ROBLOX_DEPLOY_LOG_URL)
        if not text:
            return []
        all_lines = [l.strip() for l in text.splitlines() if l.strip()]
        return all_lines[-lines:]

    async def get_unresolved_incidents(self) -> list[dict]:
        data = await self._fetch_json(ROBLOX_STATUS_URL)
        if not data:
            return []
        incidents = data.get("incidents", [])
        results = []
        for inc in incidents:
            results.append(
                {
                    "id": inc.get("id"),
                    "name": inc.get("name", "Unknown incident"),
                    "status": inc.get("status", ""),
                    "impact": inc.get("impact", "none"),
                    "url": inc.get("shortlink", "https://status.roblox.com"),
                    "created_at": inc.get("created_at", ""),
                }
            )
        return results

    # ------------------------------------------------------------------
    # Background polling task
    # ------------------------------------------------------------------

    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def poll_updates(self) -> None:
        channel = self.get_channel(self.update_channel_id)
        if channel is None:
            return

        # --- Roblox client version ---
        client_ver = await self.get_client_version()
        if client_ver and client_ver != self._last_client_version:
            if self._last_client_version is not None:
                embed = discord.Embed(
                    title="🎮 New Roblox Client Version Deployed!",
                    description=f"**{client_ver}**",
                    colour=discord.Colour.red(),
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_footer(text="Roblox Update Tracker")
                await channel.send(embed=embed)
            self._last_client_version = client_ver

        # --- Roblox Studio version ---
        studio_ver = await self.get_studio_version()
        if studio_ver and studio_ver != self._last_studio_version:
            if self._last_studio_version is not None:
                embed = discord.Embed(
                    title="🛠️ New Roblox Studio Version Deployed!",
                    description=f"**{studio_ver}**",
                    colour=discord.Colour.blue(),
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_footer(text="Roblox Update Tracker")
                await channel.send(embed=embed)
            self._last_studio_version = studio_ver

        # --- DevForum announcements ---
        posts = await self.get_devforum_posts(DEVFORUM_ANNOUNCEMENTS_URL, limit=1)
        if posts:
            latest = posts[0]
            if latest["id"] != self._last_devforum_post_id:
                if self._last_devforum_post_id is not None:
                    embed = discord.Embed(
                        title="📢 New DevForum Announcement",
                        description=f"[{latest['title']}]({latest['url']})",
                        colour=discord.Colour.gold(),
                        timestamp=datetime.now(timezone.utc),
                    )
                    embed.set_footer(text="Roblox DevForum")
                    await channel.send(embed=embed)
                self._last_devforum_post_id = latest["id"]

        # --- Status incidents ---
        incidents = await self.get_unresolved_incidents()
        if incidents:
            latest_inc = incidents[0]
            if latest_inc["id"] != self._last_incident_id:
                if self._last_incident_id is not None:
                    embed = discord.Embed(
                        title="⚠️ Roblox Status Incident",
                        description=(
                            f"**{latest_inc['name']}**\n"
                            f"Status: `{latest_inc['status']}`  |  Impact: `{latest_inc['impact']}`\n"
                            f"[View incident]({latest_inc['url']})"
                        ),
                        colour=discord.Colour.orange(),
                        timestamp=datetime.now(timezone.utc),
                    )
                    embed.set_footer(text="status.roblox.com")
                    await channel.send(embed=embed)
                self._last_incident_id = latest_inc["id"]

    @poll_updates.before_loop
    async def before_poll(self) -> None:
        await self.wait_until_ready()


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

bot = RobloxBot()


@bot.tree.command(name="roblox_version", description="Current live Roblox client version")
async def cmd_roblox_version(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    version = await bot.get_client_version()
    if version:
        embed = discord.Embed(
            title="🎮 Roblox Client Version",
            description=f"`{version}`",
            colour=discord.Colour.red(),
        )
    else:
        embed = discord.Embed(
            title="🎮 Roblox Client Version",
            description="Could not retrieve version at this time.",
            colour=discord.Colour.red(),
        )
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="studio_version", description="Current live Roblox Studio version")
async def cmd_studio_version(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    version = await bot.get_studio_version()
    if version:
        embed = discord.Embed(
            title="🛠️ Roblox Studio Version",
            description=f"`{version}`",
            colour=discord.Colour.blue(),
        )
    else:
        embed = discord.Embed(
            title="🛠️ Roblox Studio Version",
            description="Could not retrieve version at this time.",
            colour=discord.Colour.blue(),
        )
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="latest_updates", description="Latest DevForum announcements")
async def cmd_latest_updates(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    posts = await bot.get_devforum_posts(DEVFORUM_ANNOUNCEMENTS_URL, limit=5)
    embed = discord.Embed(
        title="📢 Latest DevForum Announcements",
        colour=discord.Colour.gold(),
    )
    if posts:
        for post in posts:
            embed.add_field(
                name=post["title"],
                value=f"[Read more]({post['url']}) • {post['posts_count']} replies",
                inline=False,
            )
    else:
        embed.description = "Could not retrieve announcements at this time."
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="release_notes", description="Official Roblox release notes")
async def cmd_release_notes(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    posts = await bot.get_devforum_posts(DEVFORUM_RELEASES_URL, limit=5)
    embed = discord.Embed(
        title="📋 Roblox Release Notes",
        colour=discord.Colour.green(),
    )
    if posts:
        for post in posts:
            embed.add_field(
                name=post["title"],
                value=f"[Read more]({post['url']}) • {post['posts_count']} replies",
                inline=False,
            )
    else:
        embed.description = "Could not retrieve release notes at this time."
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="upcoming_features", description="Beta & upcoming features from DevForum")
async def cmd_upcoming_features(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    posts = await bot.get_devforum_posts(DEVFORUM_BETA_URL, limit=5)
    embed = discord.Embed(
        title="🔭 Upcoming & Beta Features",
        colour=discord.Colour.purple(),
    )
    if posts:
        for post in posts:
            embed.add_field(
                name=post["title"],
                value=f"[Read more]({post['url']}) • {post['posts_count']} replies",
                inline=False,
            )
    else:
        embed.description = "Could not retrieve upcoming features at this time."
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="deploy_history", description="Last 15 CDN deploy log entries")
async def cmd_deploy_history(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    entries = await bot.get_deploy_history(lines=15)
    embed = discord.Embed(
        title="📦 CDN Deploy History",
        colour=discord.Colour.teal(),
    )
    if entries:
        # Discord embed description limit is 4096 chars
        text = "\n".join(entries)
        if len(text) > 4000:
            text = text[-4000:]
        embed.description = f"```\n{text}\n```"
    else:
        embed.description = "Could not retrieve deploy history at this time."
    await interaction.followup.send(embed=embed)


@bot.tree.command(
    name="set_update_channel",
    description="Set the channel where update alerts are posted (Admin only)",
)
@app_commands.checks.has_permissions(administrator=True)
async def cmd_set_update_channel(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
) -> None:
    bot.update_channel_id = channel.id
    await interaction.response.send_message(
        f"✅ Update alerts will now be posted in {channel.mention}.", ephemeral=True
    )


@cmd_set_update_channel.error
async def set_update_channel_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ You need the **Administrator** permission to use this command.",
            ephemeral=True,
        )


@bot.tree.command(name="help_roblox", description="Show all Roblox Update Tracker commands")
async def cmd_help(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="🤖 Roblox Update Tracker — Help",
        colour=discord.Colour.blurple(),
    )
    commands_info = [
        ("/roblox_version", "Current live Roblox client version"),
        ("/studio_version", "Current live Roblox Studio version"),
        ("/latest_updates", "Latest DevForum announcements"),
        ("/release_notes", "Official Roblox release notes"),
        ("/upcoming_features", "Beta & upcoming features"),
        ("/deploy_history", "Last 15 CDN deploy log entries"),
        ("/set_update_channel", "Set your alert channel (Admin only)"),
        ("/help_roblox", "Show this help message"),
    ]
    for name, desc in commands_info:
        embed.add_field(name=name, value=desc, inline=False)
    embed.set_footer(text=f"Checks for updates every {CHECK_INTERVAL_MINUTES} minutes")
    await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    bot.run(BOT_TOKEN)
