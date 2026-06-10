                self._ping_role_id = role.id
                return role

        if not create_if_missing:
            return None

        try:
            role = await guild.create_role(
                name="Roblox Updates",
                mentionable=True,
                reason="Roblox update tracker alert role",
            )
        except (discord.Forbidden, discord.HTTPException):
            return None

        self._ping_role_id = role.id
        return role

    @tasks.loop(minutes=5)
    async def rotate_presence(self):
        version = self._last_client_version or "unknown"
        label, activity_type = PRESENCE_ACTIVITIES[self._position() % len(PRESENCE_ACTIVITIES)]
        await self.change_presence(activity=discord.Activity(type=activity_type, name=label.replace("{client}", version)))

    def _position(self) -> int:
        self._presence_index = getattr(self, "_presence_index", 0) + 1
        return self._presence_index

    @rotate_presence.before_loop
    async def before_rotate_presence(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=UGC_CHECK_INTERVAL_MINUTES)
    async def poll_ugc_prices(self):
        if not self._watched_items:
            return
        channel = await self.resolve_update_channel()
        if not channel:
            return
        mention = await self.alert_content(channel)
        for asset_id, info in list(self._watched_items.items()):
            resale = await self.get_item_resale(asset_id)
            if not resale:
                continue
            new_price = resale.get("recentAveragePrice") or resale.get("originalPrice") or 0
            old_price = int(info.get("price", 0))
            if not old_price or not new_price or new_price == old_price:
                self._watched_items[asset_id]["price"] = new_price
                continue
            change = new_price - old_price
            pct = abs(change / old_price * 100)
            if pct < self._alert_threshold:
                continue
            direction = "UP" if change > 0 else "DOWN"
            colour = 0x06D6A0 if change > 0 else 0xE63946
            embed = discord.Embed(
                title=f"{direction} - UGC Price Change",
                colour=colour,
                timestamp=datetime.now(timezone.utc),
            )
            embed.description = f"**[{info.get('name', 'Item')}](https://www.roblox.com/catalog/{asset_id})**"
            embed.add_field(name="Old Price", value=f"R${old_price:,}", inline=True)
            embed.add_field(name="New Price", value=f"R${new_price:,}", inline=True)
            embed.add_field(name="Change", value=f"{change:+,} ({pct:+.1f}%)", inline=True)
            embed.set_footer(text="Roblox Economy Tracker")
            await channel.send(content=mention, embed=embed, allowed_mentions=ALERT_ALLOWED_MENTIONS)
            self._watched_items[asset_id]["price"] = new_price

    @poll_ugc_prices.before_loop
    async def before_poll_ugc_prices(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def poll_updates(self):
        self._last_check_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if time.time() < self._muted_until:
            return
        channel = await self.resolve_update_channel()
        if not channel:
            return
        mention = await self.alert_content(channel)
        now = datetime.now(timezone.utc)
        date_text = now.strftime("%B %d, %Y %I:%M %p")

        if self._filters.get("client"):
            current_version = await self.get_client_version()
            if current_version and current_version != self._last_client_version:
                if self._last_client_version is not None:
                    self._client_changelog.append({"version": current_version, "time": self._last_check_time})
                    self._client_changelog = self._client_changelog[-10:]
                    embed = discord.Embed(
                        title="Roblox Update Detected",
                        description="Roblox client update detected and the live build changed.",
                        colour=0xE63946,
                        timestamp=now,
                    )
                    embed.add_field(name="Platform", value="Windows", inline=True)
                    embed.add_field(name="Version Hash", value=f"`{current_version}`", inline=False)
                    embed.add_field(name="Date", value=date_text, inline=False)
                    embed.set_footer(text=date_text)
                    await channel.send(content=mention, embed=embed, allowed_mentions=ALERT_ALLOWED_MENTIONS)
                self._last_client_version = current_version

        if self._filters.get("devforum"):
            posts = await self.get_devforum_posts(DEVFORUM_ANNOUNCEMENTS_URL, limit=1)
            if posts:
                latest = posts[0]
                if latest["id"] != self._last_devforum_id:
                    if self._last_devforum_id is not None:
                        embed = discord.Embed(
                            title="New DevForum Announcement",
                            description=f"[{latest['title']}]({latest['url']})",
                            colour=0xFFD166,
                            timestamp=now,
                        )
                        embed.set_footer(text="Roblox DevForum")
                        await channel.send(content=mention, embed=embed, allowed_mentions=ALERT_ALLOWED_MENTIONS)
                    self._last_devforum_id = latest["id"]

        if self._filters.get("incident"):
            incidents = await self.get_unresolved_incidents()
            if incidents:
                latest = incidents[0]
                if latest["id"] != self._last_incident_id:
                    if self._last_incident_id is not None:
                        colors = {"none": 0x06D6A0, "minor": 0xFFD166, "major": 0xFF6B35, "critical": 0xE63946}
                        embed = discord.Embed(
                            title=f"Roblox Incident: {latest['name']}",
                            description=latest["latest_update"],
                            colour=colors.get(latest["impact"], 0xAAAAAA),
                            timestamp=now,
                        )
                        embed.add_field(name="Status", value=latest["status"].replace("_", " ").title(), inline=True)
                        embed.add_field(name="Impact", value=latest["impact"].title(), inline=True)
                        embed.add_field(name="Details", value=f"[View]({latest['url']})", inline=False)
                        embed.set_footer(text="status.roblox.com")
                        await channel.send(content=mention, embed=embed, allowed_mentions=ALERT_ALLOWED_MENTIONS)
                    self._last_incident_id = latest["id"]

    @poll_updates.before_loop
    async def before_poll_updates(self):
        await self.wait_until_ready()


bot = RobloxBot()


def base_embed(title: str, colour: int = 0x4CC9F0) -> discord.Embed:
    return discord.Embed(title=title, colour=colour, timestamp=datetime.now(timezone.utc))


def server_stats_embed(guild: discord.Guild | None = None) -> discord.Embed:
    uptime = int(time.time() - bot._start_time)
    hours, rem = divmod(uptime, 3600)
    minutes, _ = divmod(rem, 60)
    muted = "Yes" if time.time() < bot._muted_until else "No"
    ping_role = "Not set"
    if bot._ping_role_id:
        if guild is not None:
            role = guild.get_role(bot._ping_role_id)
            ping_role = role.mention if role is not None else "Configured role missing"
        else:
            ping_role = "Configured role missing"
    embed = base_embed("Server Stats", 0x9B5DE5)
    embed.add_field(name="Command Count", value=str(bot._command_uses), inline=True)
    embed.add_field(name="Bot Uptime", value=f"{hours}h {minutes}m", inline=True)
    embed.add_field(name="Alert Channel", value=f"<#{bot.update_channel_id}>" if bot.update_channel_id else "Not set", inline=True)
    embed.add_field(name="Ping Role", value=ping_role if ping_role != "Not set" else "Not set", inline=True)
    embed.add_field(name="Watched UGC Items", value=str(len(bot._watched_items)), inline=True)
    embed.add_field(name="Version Changes", value=str(len(bot._client_changelog)), inline=True)
    embed.add_field(name="Muted", value=muted, inline=True)
    embed.add_field(name="Alert Threshold", value=f"{bot._alert_threshold:.1f}%", inline=True)
    embed.add_field(name="Filters", value=", ".join(name for name, enabled in bot._filters.items() if enabled) or "None", inline=False)
    return embed


def status_embed() -> discord.Embed:
    embed = base_embed("Roblox Platform Status", 0x4CC9F0)
    return embed


@bot.tree.command(name="roblox_version", description="Current live Roblox client version")
async def roblox_version(interaction: discord.Interaction):
    bot._command_uses += 1
    await interaction.response.defer()
    version = await bot.get_client_version()
    now = datetime.now(timezone.utc)
    embed = discord.Embed(
        title="Roblox Update Info",
        description="Current live version from the Roblox CDN.",
        colour=0xE63946,
        timestamp=now,
    )
    embed.add_field(name="Platform", value="Windows", inline=True)
    embed.add_field(name="Version Hash", value=f"`{version or 'N/A'}`", inline=True)
    embed.add_field(name="Checked At", value=now.strftime("%B %d, %Y %I:%M %p"), inline=False)
    await interaction.followup.send(embed=embed)


async def _forum_posts_command(interaction: discord.Interaction, title: str, url: str, colour: int):
    bot._command_uses += 1
    await interaction.response.defer()
    posts = await bot.get_devforum_posts(url, limit=5)
    embed = base_embed(title, colour)
    if posts:
        for post in posts:
            embed.add_field(
                name=post["title"],
                value=f"[Read more]({post['url']}) - {post['posts_count']} replies",
                inline=False,
            )
    else:
        embed.description = "Could not retrieve forum posts right now."
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="latest_updates", description="Latest DevForum announcements")
async def latest_updates(interaction: discord.Interaction):
    await _forum_posts_command(interaction, "Latest DevForum Announcements", DEVFORUM_ANNOUNCEMENTS_URL, 0xFFD166)


@bot.tree.command(name="release_notes", description="Official Roblox release notes")
async def release_notes(interaction: discord.Interaction):
    await _forum_posts_command(interaction, "Roblox Release Notes", DEVFORUM_RELEASES_URL, 0x06D6A0)


@bot.tree.command(name="upcoming_features", description="Beta and upcoming Roblox features")
async def upcoming_features(interaction: discord.Interaction):
    await _forum_posts_command(interaction, "Upcoming Roblox Features", DEVFORUM_BETA_URL, 0x9B5DE5)


@bot.tree.command(name="security_updates", description="Recent Roblox security and incident updates")
async def security_updates(interaction: discord.Interaction):
    bot._command_uses += 1
    await interaction.response.defer()
    incidents = await bot.get_unresolved_incidents()
    posts = await bot.get_devforum_posts(DEVFORUM_ANNOUNCEMENTS_URL, limit=3)
    embed = base_embed("Roblox Security Updates", 0xFF6B35)
    if incidents:
        lines = [
            f"[{incident['name']}]({incident['url']}) - {incident['status'].replace('_', ' ').title()} ({incident['impact'].title()})"
            for incident in incidents[:3]
        ]
        embed.add_field(name="Active Incidents", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Active Incidents", value="None", inline=False)
    if posts:
        embed.add_field(
            name="Recent Announcements",
            value="\n".join(f"[{post['title']}]({post['url']})" for post in posts),
