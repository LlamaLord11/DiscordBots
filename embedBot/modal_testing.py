import os
import discord
from discord.ext import commands
from discord import app_commands
import traceback

serverID = int(os.getenv("CURRENT_SERVER_ID"))

class modal_testing(commands.Cog):
    def __init__(self, bot:commands.Bot):
        self.bot = bot

    @app_commands.command(name="modal_test", description="Basic Modal Test Command")
    @app_commands.guilds(discord.Object(id=serverID))
    async def modalTest(self, interaction: discord.Interaction):
        await interaction.response.send_modal(self.TestModal())

    
    class TestModal(discord.ui.Modal, title='TestModal'):

        name = discord.ui.TextInput(
            label='Name', 
            placeholder='Your Name Here',
        )

        feedback = discord.ui.TextInput(
            label='What do you think of this new feature?',
            style=discord.TextStyle.long,
            placeholder='Type your feedback here...',
            required=False,
            max_length=300,
        )

        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.send_message(f'Thanks for your feedback, {self.name.value}!', ephemeral=True)
            print(self.feedback.value)

        async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
            await interaction.response.send_message('Oops! Something went wrong.', ephemeral=True)

            # Make sure we know what the error actually is
            traceback.print_exception(type(error), error, error.__traceback__)

async def setup(bot: commands.Bot):
    await bot.add_cog(modal_testing(bot))

