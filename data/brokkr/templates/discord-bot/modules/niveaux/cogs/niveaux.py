"""Niveaux : des points d'expérience à chaque message (avec délai anti-spam), /niveau, /classement."""

from __future__ import annotations

import math
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

DELAI = 60  # secondes entre deux gains pour un même membre

SCHEMA = """
CREATE TABLE IF NOT EXISTS xp (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    points   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
"""


def niveau_de(points: int) -> int:
    """Niveau n à partir de 50·n² points : 0, 50, 200, 450, 800…"""
    return int(math.isqrt(max(points, 0) // 50))


def points_pour(niveau: int) -> int:
    return 50 * niveau * niveau


class Niveaux(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._dernier: dict[tuple[int, int], float] = {}

    async def cog_load(self) -> None:
        await self.bot.db.ensure(SCHEMA)

    async def points(self, guild_id: int, user_id: int) -> int:
        ligne = await self.bot.db.fetchone("SELECT points FROM xp WHERE guild_id = ? AND user_id = ?",
                                           (guild_id, user_id))
        return ligne[0] if ligne else 0

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        cle = (message.guild.id, message.author.id)
        maintenant = time.monotonic()
        if maintenant - self._dernier.get(cle, 0.0) < DELAI:
            return
        self._dernier[cle] = maintenant
        avant = await self.points(*cle)
        gain = random.randint(5, 15)
        await self.bot.db.execute(
            "INSERT INTO xp (guild_id, user_id, points) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET points = points + excluded.points",
            (*cle, gain),
        )
        if niveau_de(avant + gain) > niveau_de(avant):
            await message.channel.send(f"✨ {message.author.mention} passe au niveau **{niveau_de(avant + gain)}** !")

    @app_commands.command(name="niveau", description="Le niveau d'un membre")
    @app_commands.guild_only()
    async def niveau(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        cible = membre or interaction.user
        points = await self.points(interaction.guild_id, cible.id)
        n = niveau_de(points)
        await interaction.response.send_message(
            f"**{cible.display_name}** : niveau {n} ({points} points, prochain niveau à {points_pour(n + 1)}).")

    @app_commands.command(name="classement", description="Les membres les plus actifs")
    @app_commands.guild_only()
    async def classement(self, interaction: discord.Interaction) -> None:
        lignes = await self.bot.db.fetchall(
            "SELECT user_id, points FROM xp WHERE guild_id = ? ORDER BY points DESC LIMIT 10", (interaction.guild_id,))
        if not lignes:
            await interaction.response.send_message("Personne n'a encore de points : à vos claviers !")
            return
        texte = "\n".join(f"**{rang}.** <@{u}> — niveau {niveau_de(p)} ({p} pts)"
                          for rang, (u, p) in enumerate(lignes, 1))
        embed = discord.Embed(title="Classement", description=texte, color=0x79AC99)
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Niveaux(bot))
