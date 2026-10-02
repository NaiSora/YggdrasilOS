"""Modération : bannir, expulser, exclure un temps, purger un salon, avertir (gardé en base)."""

from __future__ import annotations

import datetime as dt
import re

import discord
from discord import app_commands
from discord.ext import commands

DUREE_RE = re.compile(r"(\d+)\s*([smhj])")
UNITES = {"s": 1, "m": 60, "h": 3600, "j": 86400}
EXCLUSION_MAX = 28 * 86400  # limite de Discord

SCHEMA = """
CREATE TABLE IF NOT EXISTS avertissements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    moderateur_id INTEGER NOT NULL,
    raison TEXT NOT NULL,
    date TEXT NOT NULL
);
"""


def parse_duree(texte: str) -> int:
    """« 1h30m » → 5400 secondes ; « 2j » → 172800 ; 0 si illisible."""
    return sum(int(n) * UNITES[u] for n, u in DUREE_RE.findall(texte.lower()))


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        await self.bot.db.ensure(SCHEMA)

    @app_commands.command(name="bannir", description="Bannir un membre")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    async def bannir(self, interaction: discord.Interaction, membre: discord.Member,
                     raison: str = "aucune raison donnée") -> None:
        await membre.ban(reason=f"{interaction.user} : {raison}")
        await interaction.response.send_message(f"🔨 **{membre}** est banni. Raison : {raison}")

    @app_commands.command(name="expulser", description="Expulser un membre (il peut revenir)")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.guild_only()
    async def expulser(self, interaction: discord.Interaction, membre: discord.Member,
                       raison: str = "aucune raison donnée") -> None:
        await membre.kick(reason=f"{interaction.user} : {raison}")
        await interaction.response.send_message(f"👢 **{membre}** est expulsé. Raison : {raison}")

    @app_commands.command(name="exclure", description="Exclure un membre un temps (ex. 10m, 1h30m, 2j)")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def exclure(self, interaction: discord.Interaction, membre: discord.Member, duree: str,
                      raison: str = "aucune raison donnée") -> None:
        secondes = parse_duree(duree)
        if not 0 < secondes <= EXCLUSION_MAX:
            await interaction.response.send_message("Durée invalide (de 1s à 28j, ex. 1h30m).", ephemeral=True)
            return
        await membre.timeout(dt.timedelta(seconds=secondes), reason=f"{interaction.user} : {raison}")
        await interaction.response.send_message(f"⏳ **{membre}** est exclu pour {duree}. Raison : {raison}")

    @app_commands.command(name="purger", description="Effacer les derniers messages du salon")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def purger(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 100]) -> None:
        await interaction.response.defer(ephemeral=True)
        effaces = await interaction.channel.purge(limit=nombre)
        await interaction.followup.send(f"🧹 {len(effaces)} message(s) effacé(s).", ephemeral=True)

    @app_commands.command(name="avertir", description="Avertir un membre (gardé en mémoire)")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def avertir(self, interaction: discord.Interaction, membre: discord.Member, raison: str) -> None:
        await self.bot.db.execute(
            "INSERT INTO avertissements (guild_id, user_id, moderateur_id, raison, date) VALUES (?, ?, ?, ?, ?)",
            (interaction.guild_id, membre.id, interaction.user.id, raison, dt.datetime.now().isoformat()),
        )
        (nombre,) = await self.bot.db.fetchone(
            "SELECT COUNT(*) FROM avertissements WHERE guild_id = ? AND user_id = ?",
            (interaction.guild_id, membre.id),
        )
        await interaction.response.send_message(f"⚠️ **{membre}** est averti ({nombre} au total). Raison : {raison}")

    @app_commands.command(name="avertissements", description="Les avertissements d'un membre")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def avertissements(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        lignes = await self.bot.db.fetchall(
            "SELECT date, raison FROM avertissements WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT 10",
            (interaction.guild_id, membre.id),
        )
        texte = "\n".join(f"• {d[:10]} — {r}" for d, r in lignes) or "Aucun avertissement."
        await interaction.response.send_message(f"**{membre}** :\n{texte}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
