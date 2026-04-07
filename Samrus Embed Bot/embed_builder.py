import os
import discord
from discord.ext import commands
from discord import app_commands

serverID = int(os.getenv("CURRENT_SERVER_ID"))

class embed_builder(commands.Cog):
    def __init__(self, bot:commands.Bot):
        self.bot = bot

    @app_commands.command(name='build_embed', description='Build an Embed')
    @app_commands.guilds(discord.Object(id=serverID))
    async def embed_builder_start(self, interaction: discord.Interaction):
        EmbedBuilder = self.embedBuilder(initialModal=self.initialModal)
        await interaction.response.send_message('Select a Color for your Embed', view=self.ColorSelectorView(embed_builder=EmbedBuilder), ephemeral=True)

    
    class embedBuilder():
        def __init__(self, initialModal):
            self.initialModal = initialModal
            self.color = None
            self.title = ''
            self.description = ''
            self.author = ''
            self.footer = ''

        def testPrint(self):
            return f"Title: {self.title} | Description: {self.description} | Author: {self.author} | Footer: {self.footer} | Color: {self.color}"

        def setColor(self, color: discord.Color):
            self.color = color

        def initialModalFeedback(self, title, description, author, footer):
            self.title=title
            self.description=description
            self.author=author
            self.footer=footer

    class ColorSelectorView(discord.ui.View):
        def __init__(self, *, timeout = 180, embed_builder):
            self.embed_builder = embed_builder
            super().__init__(timeout=timeout)
            self.add_item(self.ColorSelections(embed_builder=self.embed_builder))

        class ColorSelections(discord.ui.Select):

            COLOR_MAP = {
                "teal":             discord.Color.teal(),
                "dark_teal":        discord.Color.dark_teal(),
                "green":            discord.Color.green(),
                "dark_green":       discord.Color.dark_green(),
                "blue":             discord.Color.blue(),
                "dark_blue":        discord.Color.dark_blue(),
                "blurple":          discord.Color.blurple(),
                "purple":           discord.Color.purple(),
                "dark_purple":      discord.Color.dark_purple(),
                "magenta":          discord.Color.magenta(),
                "yellow":           discord.Color.yellow(),
                "gold":             discord.Color.gold(),
                "dark_gold":        discord.Color.dark_gold(),
                "orange":           discord.Color.orange(),
                "dark_orange":      discord.Color.dark_orange(),
                "red":              discord.Color.red(),
                "dark_red":         discord.Color.dark_red(),
                "light_grey":       discord.Color.light_grey(),
                "dark_grey":        discord.Color.dark_grey(),
                "darker_grey":      discord.Color.darker_grey(),
                "ebony":       discord.Color.dark_embed(),
                "antiflash_white":      discord.Color.light_embed(),
                "black":            discord.Color.default(),
            }

            def __init__(self, embed_builder):
                self.embed_builder = embed_builder
                options = [
                    discord.SelectOption(label="Teal", value='teal'),
                    discord.SelectOption(label="Dark Teal", value='dark_teal'),
                    discord.SelectOption(label="Green", value='green'),
                    discord.SelectOption(label="Dark Green", value='dark_green'),
                    discord.SelectOption(label="Blue", value='blue'),
                    discord.SelectOption(label="Dark Blue", value='dark_blue'),
                    discord.SelectOption(label="Blueish Purple", value='blurple'),
                    discord.SelectOption(label="Purple", value='purple'),
                    discord.SelectOption(label="Dark Purple", value='dark_purple'),
                    discord.SelectOption(label="Magenta", value='magenta'),
                    discord.SelectOption(label="Yellow", value='yellow'),
                    discord.SelectOption(label="Gold", value='gold'),
                    discord.SelectOption(label="Dark Gold", value='dark_gold'),
                    discord.SelectOption(label="Orange", value='orange'),
                    discord.SelectOption(label="Dark Orange", value='dark_orange'),
                    discord.SelectOption(label="Red", value='red'),

                    discord.SelectOption(label="Dark Red", value='dark_red'),
                    discord.SelectOption(label="Light Grey", value='light_grey'),
                    discord.SelectOption(label="Dark Grey", value='dark_grey'),
                    discord.SelectOption(label="Darker Grey", value='darker_grey'),
                    discord.SelectOption(label="Ebony", value='ebony'),
                    discord.SelectOption(label="Anti-Flash White", value='antiflash_white'),
                    discord.SelectOption(label="Black", value='black'),
                ]
                super().__init__(placeholder='Select A Color', max_values=1, min_values=1, options=options)

            async def callback(self, interaction: discord.Interaction):
                self.embed_builder.setColor(self.COLOR_MAP[self.values[0]])
                await interaction.response.send_modal(self.embed_builder.initialModal(embed_builder=self.embed_builder))

    class initialModal(discord.ui.Modal, title='Embed Builder'):
        def __init__(self, embed_builder):
            super().__init__()
            self.embed_builder = embed_builder

        embedTitle = discord.ui.TextInput(
            label = 'Embed Title',
            style = discord.TextStyle.short,
            placeholder = '(Optional) Enter the Embed Title here...',
            required = False,
            max_length = 256,
        )

        embedDescription = discord.ui.TextInput(
            label = 'Embed Body',
            style = discord.TextStyle.long,
            placeholder = '(Optional) Enter the Embed Body here...',
            required = False,
            max_length = 4000,
        )

        embedAuthor = discord.ui.TextInput(
            label = 'Embed Author',
            style = discord.TextStyle.short,
            placeholder = '(Optional) Enter the Embed Author here...',
            required = False,
            max_length = 256,
        )

        embedFooter = discord.ui.TextInput(
            label = 'Embed Footer',
            style = discord.TextStyle.long,
            placeholder = '(Optional) Enter the Embed Footer here...',
            required = False,
            max_length = 2048,
        )

        async def on_submit(self, interaction: discord.Interaction):
            self.embed_builder.initialModalFeedback(self.embedTitle.value, self.embedDescription.value, self.embedAuthor.value, self.embedFooter.value)
            await interaction.response.send_message(content=self.embed_builder.testPrint(), ephemeral=True)

            

async def setup(bot: commands.Bot):
    await bot.add_cog(embed_builder(bot))