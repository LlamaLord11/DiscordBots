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
        EmbedBuilder = self.EmbedBuilder(InitialModal=self.InitialModal, FieldModal=self.FieldModal, EmbedButtons=self.EmbedBuilderButtons, ColorSelector=self.ColorSelectorView)
        await interaction.response.send_message('Select a Color for your Embed', view=self.ColorSelectorView(embed_builder=EmbedBuilder), ephemeral=True)

    
    class EmbedBuilder():
        def __init__(self, InitialModal, FieldModal, EmbedButtons, ColorSelector):
            self.InitialModal = InitialModal
            self.FieldModal = FieldModal
            self.EmbedButtons = EmbedButtons
            self.ColorSelector = ColorSelector
            self.color = None
            self.title = ''
            self.description = ''
            self.author = ''
            self.footer = ''
            self.fields = []

        def setColor(self, color: discord.Color):
            self.color = color

        def initialModalFeedback(self, title, description, author, footer):
            self.title=title
            self.description=description
            self.author=author
            self.footer=footer

        def fieldModalFeedback(self, field):
            self.fields.append(field)

        def deleteLastField(self):
            self.fields.pop()

        def getEmbedLength(self):
            charCount = 0
            charCount += len(self.title)
            charCount += len(self.description)
            charCount += len(self.author)
            charCount += len(self.footer)

            for currentField in self.fields:
                charCount += len(currentField.title)
                charCount += len(currentField.description)

            return charCount
        
        def getFieldCount(self):
            return len(self.fields)

        def getEmbed(self) -> discord.Embed:
            embed = discord.Embed(
                title=self.title,
                description=self.description,
                color=self.color,
            )
            if self.author: embed.set_author(name=self.author)
            if self.footer: embed.set_footer(text=self.footer)

            if len(self.fields) > 0:
                for currentField in self.fields:
                    embed.add_field(name=currentField.title, value=currentField.description, inline=False)

            return embed

    class ColorSelectorView(discord.ui.View):
        def __init__(self, *, timeout = 180, embed_builder, editing=False):
            self.embed_builder = embed_builder
            super().__init__(timeout=timeout)
            self.add_item(self.ColorSelections(embed_builder=self.embed_builder, editing=editing))

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

            def __init__(self, embed_builder, editing):
                self.editing = editing
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
                selected_label = next(opt.label for opt in self.options if opt.value == self.values[0])

                if not self.editing:
                    await interaction.response.send_modal(self.embed_builder.InitialModal(embed_builder=self.embed_builder))
                    await interaction.edit_original_response(content=f"Selected Color: {selected_label}", view=None)
                else:
                    await interaction.response.edit_message(
                        content=f"{self.embed_builder.getEmbedLength()} of maximum 6,000 Characters | {self.embed_builder.getFieldCount()} of maximum 25 Fields",
                        embed=self.embed_builder.getEmbed(),
                        view=self.embed_builder.EmbedButtons(embed_builder=self.embed_builder)
                    )

    class InitialModal(discord.ui.Modal, title='Embed Builder'):
        def __init__(self, embed_builder, editing=False):
            super().__init__()
            self.embed_builder = embed_builder
            self.editing=editing
            
            self.embedAuthor = discord.ui.TextInput(
                label = 'Embed Author',
                style = discord.TextStyle.short,
                placeholder = '(Optional) Enter the Embed Author here...',
                required = False,
                max_length = 256,
                default=self.embed_builder.author if editing else None,
            )

            self.embedTitle = discord.ui.TextInput(
                label = 'Embed Title',
                style = discord.TextStyle.short,
                placeholder = '(Optional) Enter the Embed Title here...',
                required = False,
                max_length = 256,
                default=self.embed_builder.title if editing else None,
            )

            self.embedDescription = discord.ui.TextInput(
                label = 'Embed Body',
                style = discord.TextStyle.long,
                placeholder = '(Optional) Enter the Embed Body here...',
                required = False,
                max_length = 4000,
                default=self.embed_builder.description if editing else None,
            )

            self.embedFooter = discord.ui.TextInput(
                label = 'Embed Footer',
                style = discord.TextStyle.long,
                placeholder = '(Optional) Enter the Embed Footer here...',
                required = False,
                max_length = 2048,
                default=self.embed_builder.footer if editing else None,
            )
        
            self.add_item(self.embedAuthor)
            self.add_item(self.embedTitle)
            self.add_item(self.embedDescription)
            self.add_item(self.embedFooter)

        async def on_submit(self, interaction: discord.Interaction):

            potentialLength = (
                len(self.embedTitle.value) +
                len(self.embedDescription.value) +
                len(self.embedAuthor.value) +
                len(self.embedFooter.value) +
                sum(len(f.title) + len(f.description) for f in self.embed_builder.fields)
            )

            if potentialLength > 6000:
                await interaction.response.send_message(content="Character limit reached. Embed total can't exceed 6,000 characters.", ephemeral=True)
                return
            
            self.embed_builder.initialModalFeedback(self.embedTitle.value, self.embedDescription.value, self.embedAuthor.value, self.embedFooter.value)
            if self.editing:
                await interaction.response.edit_message(content=f"{self.embed_builder.getEmbedLength()} of maximum 6,000 Characters | {self.embed_builder.getFieldCount()} of maximum 25 Fields", embed=self.embed_builder.getEmbed(), view=self.embed_builder.EmbedButtons(embed_builder=self.embed_builder))
            else:
                await interaction.response.send_message(content=f"{self.embed_builder.getEmbedLength()} of maximum 6,000 Characters | {self.embed_builder.getFieldCount()} of maximum 25 Fields", embed=self.embed_builder.getEmbed(), view=self.embed_builder.EmbedButtons(embed_builder=self.embed_builder), ephemeral=True)

    class FieldModal(discord.ui.Modal, title='Field Builder'):
        def __init__(self, embed_builder):
            super().__init__()
            self.embed_builder = embed_builder

        fieldTitle = discord.ui.TextInput(
            label = 'Field Title',
            style = discord.TextStyle.short,
            placeholder = '(Optional) Enter the Field Title here...',
            required = False,
            max_length = 256,
        )

        fieldDescription = discord.ui.TextInput(
            label = 'Field Body',
            style = discord.TextStyle.long,
            placeholder = '(Optional) Enter the Field Body here...',
            required = False,
            max_length = 1024,
        )

        class Field():
            def __init__(self, title="", description=""):
                self.title=title
                self.description=description
            
        async def on_submit(self, interaction: discord.Interaction):
            field = self.Field(self.fieldTitle.value, self.fieldDescription.value)
            self.embed_builder.fieldModalFeedback(field)

            if self.embed_builder.getEmbedLength() > 6000:
                self.embed_builder.deleteLastField()
                await interaction.response.send_message(content="Character limit reached. Embed total can't exceed 6,000 characters.", ephemeral=True)
            elif self.embed_builder.getFieldCount() > 25:
                self.embed_builder.deleteLastField()
                await interaction.response.send_message(content="Field limit reached. Field count can't exceed 25", ephemeral=True)
            else:
                await interaction.response.edit_message(content=f"{self.embed_builder.getEmbedLength()} of maximum 6,000 Characters | {self.embed_builder.getFieldCount()} of maximum 25 Fields", embed=self.embed_builder.getEmbed(), view=self.embed_builder.EmbedButtons(embed_builder=self.embed_builder))

    class EmbedBuilderButtons(discord.ui.View):
        def __init__(self, *, timeout = None, embed_builder):
            super().__init__(timeout=timeout)
            self.embed_builder=embed_builder

        @discord.ui.button(label="Edit Embed", style=discord.ButtonStyle.blurple)
        async def edit_embed(self, interaction:discord.Interaction, button:discord.ui.Button):
            await interaction.response.send_modal(self.embed_builder.InitialModal(embed_builder=self.embed_builder, editing=True))

        @discord.ui.button(label="Change Color", style=discord.ButtonStyle.blurple)
        async def change_color(self, interaction:discord.Interaction, button:discord.ui.Button):
            await interaction.response.edit_message(content='Select a new color:', view=self.embed_builder.ColorSelector(embed_builder=self.embed_builder, editing=True), embed=None)

        @discord.ui.button(label="Add Field", style=discord.ButtonStyle.blurple)
        async def add_field(self, interaction:discord.Interaction, button:discord.ui.Button):
            await interaction.response.send_modal(self.embed_builder.FieldModal(embed_builder=self.embed_builder))

        @discord.ui.button(label="Delete Last Field", style=discord.ButtonStyle.red)
        async def delete_last_field(self, interaction:discord.Interaction, button:discord.ui.Button):
            if len(self.embed_builder.fields) > 0:
                self.embed_builder.deleteLastField()
                await interaction.response.edit_message(content=f"{self.embed_builder.getEmbedLength()} of maximum 6,000 Characters | {self.embed_builder.getFieldCount()} of maximum 25 Fields", embed=self.embed_builder.getEmbed(), view=self.embed_builder.EmbedButtons(embed_builder=self.embed_builder))
            else:
                await interaction.response.send_message("No Fields to Delete", ephemeral=True)

        @discord.ui.button(label="Delete Embed", style=discord.ButtonStyle.red)
        async def delete_embed(self, interaction:discord.Interaction, button:discord.ui.Button):
            await interaction.response.edit_message(content="Embed Creation Stopped", embed=None, view=None)

        @discord.ui.button(label="Create Embed", style=discord.ButtonStyle.green)
        async def create_embed(self, interaction:discord.Interaction, button:discord.ui.Button):
            await interaction.response.edit_message(content="Embed Creation Completed", embed=None, view=None)
            await interaction.channel.send(embed=self.embed_builder.getEmbed())

async def setup(bot: commands.Bot):
    await bot.add_cog(embed_builder(bot))