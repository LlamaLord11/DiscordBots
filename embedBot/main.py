import sys, os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Run Command: python -m embedBot.main

sys.dont_write_bytecode = True
load_dotenv()

CLIENT_TOKEN = os.getenv("BOT_TOKEN")
CURRENT_SERVER_ID = discord.Object(id=int(os.getenv("CURRENT_SERVER_ID")))

class SamrusEmbedBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=discord.Intents.all())

    async def setup_hook(self):
        await self.cogLoader()

        print("Syncing commands...")
        try:
            synced = await self.tree.sync(guild=CURRENT_SERVER_ID)
            guild = self.get_guild(CURRENT_SERVER_ID.id) or await self.fetch_guild(CURRENT_SERVER_ID.id)
            print(f"Synced {len(synced)} commands to {guild.name} ({CURRENT_SERVER_ID.id})")
            print("Synced: " + " ".join(f"/{cmd.name}" for cmd in synced))
        except Exception as e:
            print(f"Sync error: {e}")

    async def on_ready(self):
        print(f"Logged in as {self.user}")

    async def cogLoader(self):
        try:
            await self.load_extension("embedBot.embed_fetcher")
            print("-> Loaded cog: embedFetcher")
            await self.load_extension("embedBot.misc_commands")
            print("-> Loaded cog: miscCommands")
            await self.load_extension("embedBot.modal_testing")
            print("-> Loaded cog: modalTesting")
            await self.load_extension("embedBot.embed_builder")
            print("-> Loaded cog: embedBuilder")
        except Exception as e:
            print(f"-> Failed to load Cogs\n{e}")

def main() -> None:
    bot = SamrusEmbedBot()
    bot.run(CLIENT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()