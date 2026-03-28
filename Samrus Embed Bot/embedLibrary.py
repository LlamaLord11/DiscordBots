import discord

class EmbedLibrary:
    def embed1(self) -> discord.Embed:
        def __init__(self):
            pass

        # Testbench Embed

        embed = discord.Embed(
            title="Embed 1",
            description=(
                "Line1\n"
                "Line2\n"
                "Line3"
            ),
            color=discord.Color.gold(),
        )

        embed.set_footer(text="Footer text")
        
        return embed
    
    # Rule Channel Embed

    def embed2(self) -> discord.Embed:
        def __init__(self):
            pass

        embed = discord.Embed(
            description=("## Samrus Software Company Rules"),
            color=discord.Color.gold(),
        )

        embed.add_field(name=":scroll: - Stoneworks Rules", value="This server is officially part of the Stoneworks Minecraft server. We will enforce all SW rules here.", inline=False)
        embed.add_field(name=":mirror_ball: - Discord Rules", value="We strictly adhere to, and enforce, the Discord Community Guidelines and Terms of Service.", inline=False)
        embed.add_field(name=":man_detective: - Scammers", value="Scammers and others who abuse our practices or impersonate us will be punished severely.", inline=False)
        embed.add_field(name=":bank: - SSC Exclusives", value="We reserve the right to offer exclusive content and services to our members, and to enforce rules regarding their use. Redistribution or resale of any SSC-exclusive content is strictly prohibited.", inline=False)

        embed.set_footer(text="Samrus Software Company")
        
        return embed
    
    # Announcement Reaction Role Embed

    def embed3(self) -> discord.Embed:
        def __init__(self):
            pass

        embed = discord.Embed(
            title="Reaction Roles",
            description=(
                "React to this message with the following emojis to receive the corresponding role:"
            ),
            color=discord.Color.gold(),
        )

        embed.add_field(name=":mega: - Announcements", value="", inline=False)

        embed.set_footer(text="Samrus Software Company")
        
        return embed
    
    # Info Page Embed

    def embed4(self) -> discord.Embed:
        def __init__(self):
            pass

        embed = discord.Embed(
            title="",
            description=(
                "## Samrus Software Company (SSC)"
            ),
            color=discord.Color.gold(),
        )

        embed.add_field(name=":computer: - Discord Bots", 
value="""The SSC can build discord bots for whatever purposes you need, including but not limited to:
- Banking Bots
- Auction House Bots
- Invite Tracker Bots
- Custom Ticket Tool Bots
- Marketplace Bots
Whatever your need, we can handle it. Have an idea you don't see here? Just open a ticket and we'll discuss it with you!""", inline=False)
        
        embed.add_field(name=":video_game: - Custom Minecraft Mods", value="Whatever idea you may have, the SSC is ready to execute it. Any mod idea under the sun, the world is your oyster! Our only interest is in building mods that can enhance *your* gaming experience.", inline=False)

        embed.add_field(name=":floppy_disk: - Hosting ($20k/month)", value="The SSC is pleased to offer convenient and simple bot hosting for all our clients. For a reasonable monthly fee, you will never have to worry about uptime limits, interaction limits, or any other limitations that common services impose.", inline=False)
                        
        embed.add_field(name=":ambulance: - Support ($30k/month)", value="The SSC offers a simple and timely support service that focuses on fixing issues you may face as your service scales up. Ranging from bug fixes to crash recovery, our expert supporters aim to keep your bot up and running at full capacity at all times, all for an incredibly reasonable monthly cost.", inline=False)
        
        embed.add_field(name="", value="What are you waiting for? Open a ticket today so we can discuss your next big idea: https://discord.com/channels/1234362510186909777/1404910481357144084\n\n-# All payments are to be made exclusively in Stoneworks Currency (Crowns). Exchange of real currencies is explicitly prohibited under Stoneworks Rules/TOS.")

        embed.set_footer(text="Samrus Software Company")
        
        return embed