import os
import discord
from discord.ext import commands
from discord import app_commands

from embedBot.embedLibrary import EmbedLibrary

serverID = int(os.getenv("CURRENT_SERVER_ID"))

class embed_fetcher(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="embed-fetcher", description="Fetches an embed from the library")
    @app_commands.guilds(discord.Object(id=serverID))
    @app_commands.describe(embed_number="The number of the relevant embed in the library")
    async def embed_fetcher(self, interaction: discord.Interaction, embed_number: int):
        library = EmbedLibrary()
        embedName = f"embed{embed_number}"

        if hasattr(library, embedName):
            embed = getattr(library, embedName)()
            await interaction.response.defer(ephemeral=True)
            await interaction.channel.send(embed=embed)
            await interaction.delete_original_response()
        else:
            await interaction.response.send_message(f"Embed {embed_number} not found in the library.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(embed_fetcher(bot))