"""Tickets : /ticket ouvre un fil privé entre le membre et l'équipe ; /fermer le referme."""

from __future__ import annotations

import os

import discord
from discord import app_commands
from discord.ext import commands

PREFIXE = "ticket-"


def nom_ticket(pseudo: str, sujet: str) -> str:
    """« Astrid », « Problème de rôle » → « ticket-astrid-probleme-de-role » (100 caractères au plus)."""
    import re
    import unicodedata

    texte = unicodedata.normalize("NFKD", f"{pseudo} {sujet}").encode("ascii", "ignore").decode().lower()
    return (PREFIXE + re.sub(r"[^a-z0-9]+", "-", texte).strip("-"))[:100]


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        role = os.getenv("TICKETS_ROLE_ID", "").strip()
        self.role_id = int(role) if role.isdigit() else None

    @app_commands.command(name="ticket", description="Ouvrir un ticket avec l'équipe")
    @app_commands.guild_only()
    async def ticket(self, interaction: discord.Interaction, sujet: str) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Ouvre le ticket depuis un salon textuel.", ephemeral=True)
            return
        fil = await interaction.channel.create_thread(name=nom_ticket(interaction.user.name, sujet),
                                                      type=discord.ChannelType.private_thread, invitable=False)
        await fil.add_user(interaction.user)
        equipe = f"<@&{self.role_id}>" if self.role_id else "L'équipe"
        await fil.send(f"🎫 {interaction.user.mention} : « {sujet} ». {equipe} arrive. « /fermer » une fois réglé.",
                       allowed_mentions=discord.AllowedMentions(roles=True, users=True))
        await interaction.response.send_message(f"Ton ticket est ouvert : {fil.mention}", ephemeral=True)

    @app_commands.command(name="fermer", description="Fermer ce ticket")
    @app_commands.guild_only()
    async def fermer(self, interaction: discord.Interaction) -> None:
        fil = interaction.channel
        if not isinstance(fil, discord.Thread) or not fil.name.startswith(PREFIXE):
            await interaction.response.send_message("Ce n'est pas un ticket.", ephemeral=True)
            return
        await interaction.response.send_message("🔒 Ticket fermé. Merci !")
        await fil.edit(archived=True, locked=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))
