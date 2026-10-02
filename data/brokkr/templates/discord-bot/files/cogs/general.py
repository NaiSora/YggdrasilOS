"""Commandes générales : /ping et /info."""

import discord
from discord import app_commands
from discord.ext import commands


class General(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Vérifie que le bot répond")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"Pong ! {round(self.bot.latency * 1000)} ms")

    @app_commands.command(name="info", description="Informations sur le bot")
    async def info(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="{{name}}",
            description="Bot forgé par Brokkr sur Yggdrasil.",
            color=0xE8CC8C,
        )
        embed.add_field(name="Modules", value="{{modules}}", inline=False)
        embed.add_field(name="Serveurs", value=str(len(self.bot.guilds)))
        embed.add_field(name="Latence", value=f"{round(self.bot.latency * 1000)} ms")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
