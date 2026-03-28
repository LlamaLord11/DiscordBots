import os
import discord
from discord.ext import commands
from discord import app_commands

serverID = int(os.getenv("CURRENT_SERVER_ID"))

class misc_commands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Checks the bot's latency")
    @app_commands.guilds(discord.Object(id=serverID))
    async def ping(self, interaction: discord.Interaction):
        latency = self.bot.latency * 1000  # Convert to milliseconds
        await interaction.response.send_message(f"Pong! Latency: {latency:.2f} ms", ephemeral=True)

    @app_commands.command(name="shutdown", description="Shuts down the bot (Admin only)")
    @app_commands.guilds(discord.Object(id=serverID))
    @app_commands.checks.has_permissions(administrator=True)
    async def shutdown(self, interaction: discord.Interaction):
        await interaction.response.send_message("Shutting down...", ephemeral=True)
        await self.bot.close()

async def setup(bot: commands.Bot):
    await bot.add_cog(misc_commands(bot))