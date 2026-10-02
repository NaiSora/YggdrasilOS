"""Économie : une monnaie du serveur. /solde, /quotidien, /payer, /fortunes."""

from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands

MONNAIE = "pièces d'or"
QUOTIDIEN = 100
DELAI_HEURES = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS portefeuilles (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    solde    INTEGER NOT NULL DEFAULT 0,
    quotidien TEXT,
    PRIMARY KEY (guild_id, user_id)
);
"""


def attente_quotidien(dernier: str | None, maintenant: dt.datetime, heures: int = DELAI_HEURES) -> dt.timedelta:
    """Ce qu'il reste à attendre avant le prochain /quotidien (zéro : c'est le moment)."""
    if not dernier:
        return dt.timedelta(0)
    reste = dt.datetime.fromisoformat(dernier) + dt.timedelta(hours=heures) - maintenant
    return max(reste, dt.timedelta(0))


class Economie(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        await self.bot.db.ensure(SCHEMA)

    async def portefeuille(self, guild_id: int, user_id: int) -> tuple[int, str | None]:
        await self.bot.db.execute("INSERT OR IGNORE INTO portefeuilles (guild_id, user_id) VALUES (?, ?)",
                                  (guild_id, user_id))
        return await self.bot.db.fetchone(
            "SELECT solde, quotidien FROM portefeuilles WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))

    @app_commands.command(name="solde", description=f"Tes {MONNAIE}")
    @app_commands.guild_only()
    async def solde(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        cible = membre or interaction.user
        solde, _ = await self.portefeuille(interaction.guild_id, cible.id)
        await interaction.response.send_message(f"💰 **{cible.display_name}** a {solde} {MONNAIE}.")

    @app_commands.command(name="quotidien", description=f"Réclamer tes {QUOTIDIEN} {MONNAIE} du jour")
    @app_commands.guild_only()
    async def quotidien(self, interaction: discord.Interaction) -> None:
        maintenant = dt.datetime.now()
        solde, dernier = await self.portefeuille(interaction.guild_id, interaction.user.id)
        reste = attente_quotidien(dernier, maintenant)
        if reste:
            heures, secondes = divmod(int(reste.total_seconds()), 3600)
            await interaction.response.send_message(
                f"Reviens dans {heures} h {secondes // 60} min.", ephemeral=True)
            return
        await self.bot.db.execute(
            "UPDATE portefeuilles SET solde = solde + ?, quotidien = ? WHERE guild_id = ? AND user_id = ?",
            (QUOTIDIEN, maintenant.isoformat(), interaction.guild_id, interaction.user.id))
        await interaction.response.send_message(f"🪙 +{QUOTIDIEN} {MONNAIE} ! Solde : {solde + QUOTIDIEN}.")

    @app_commands.command(name="payer", description=f"Donner des {MONNAIE} à un membre")
    @app_commands.guild_only()
    async def payer(self, interaction: discord.Interaction, membre: discord.Member,
                    montant: app_commands.Range[int, 1, 1_000_000]) -> None:
        if membre.id == interaction.user.id or membre.bot:
            await interaction.response.send_message("Choisis un autre membre.", ephemeral=True)
            return
        await self.portefeuille(interaction.guild_id, membre.id)
        debite = await self.bot.db.execute(
            "UPDATE portefeuilles SET solde = solde - ? WHERE guild_id = ? AND user_id = ? AND solde >= ?",
            (montant, interaction.guild_id, interaction.user.id, montant))
        if not debite:
            await interaction.response.send_message("Tu n'as pas assez de pièces.", ephemeral=True)
            return
        await self.bot.db.execute("UPDATE portefeuilles SET solde = solde + ? WHERE guild_id = ? AND user_id = ?",
                                  (montant, interaction.guild_id, membre.id))
        await interaction.response.send_message(f"🤝 {interaction.user.mention} donne {montant} {MONNAIE} à "
                                                f"{membre.mention}.")

    @app_commands.command(name="fortunes", description="Les plus riches du serveur")
    @app_commands.guild_only()
    async def fortunes(self, interaction: discord.Interaction) -> None:
        lignes = await self.bot.db.fetchall(
            "SELECT user_id, solde FROM portefeuilles WHERE guild_id = ? AND solde > 0 ORDER BY solde DESC LIMIT 10",
            (interaction.guild_id,))
        texte = "\n".join(f"**{r}.** <@{u}> — {s}" for r, (u, s) in enumerate(lignes, 1)) or "Les coffres sont vides."
        await interaction.response.send_message(embed=discord.Embed(title="Fortunes", description=texte,
                                                                    color=0xE8CC8C),
                                                allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economie(bot))
