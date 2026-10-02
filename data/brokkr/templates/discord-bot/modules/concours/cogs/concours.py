"""Concours : /concours lance un tirage ; on réagit 🎉 ; un gagnant est tiré au sort à la fin."""

from __future__ import annotations

import datetime as dt
import random
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

EMOJI = "🎉"
SCHEMA = """
CREATE TABLE IF NOT EXISTS concours (
    message_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    prix TEXT NOT NULL,
    gagnants INTEGER NOT NULL,
    fin TEXT NOT NULL,
    termine INTEGER NOT NULL DEFAULT 0
);
"""


def parse_duree(texte: str) -> int:
    unites = {"s": 1, "m": 60, "h": 3600, "j": 86400}
    return sum(int(n) * unites[u] for n, u in re.findall(r"(\d+)\s*([smhj])", texte.lower()))


def tirer_gagnants(participants: list[int], nombre: int, rng: random.Random | None = None) -> list[int]:
    uniques = list(dict.fromkeys(participants))
    return (rng or random.SystemRandom()).sample(uniques, min(nombre, len(uniques)))


class Concours(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        await self.bot.db.ensure(SCHEMA)
        self.cloture.start()

    async def cog_unload(self) -> None:
        self.cloture.cancel()

    @app_commands.command(name="concours", description="Lancer un concours (durée ex. 1h, 2j)")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def concours(self, interaction: discord.Interaction, duree: str, prix: str,
                       gagnants: app_commands.Range[int, 1, 20] = 1) -> None:
        secondes = parse_duree(duree)
        if secondes <= 0:
            await interaction.response.send_message("Durée invalide (ex. 30m, 2h, 3j).", ephemeral=True)
            return
        fin = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=secondes)
        embed = discord.Embed(title=f"{EMOJI} Concours : {prix}",
                              description=f"Réagis avec {EMOJI} pour participer !\nFin : <t:{int(fin.timestamp())}:R>",
                              color=0xE8CC8C)
        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        await message.add_reaction(EMOJI)
        await self.bot.db.execute("INSERT INTO concours (message_id, channel_id, prix, gagnants, fin) "
                                  "VALUES (?, ?, ?, ?, ?)", (message.id, message.channel.id, prix, gagnants,
                                                             fin.isoformat()))

    @tasks.loop(seconds=30)
    async def cloture(self) -> None:
        maintenant = dt.datetime.now(dt.timezone.utc).isoformat()
        for message_id, channel_id, prix, nombre in await self.bot.db.fetchall(
                "SELECT message_id, channel_id, prix, gagnants FROM concours WHERE termine = 0 AND fin <= ?",
                (maintenant,)):
            await self.bot.db.execute("UPDATE concours SET termine = 1 WHERE message_id = ?", (message_id,))
            salon = self.bot.get_channel(channel_id)
            if salon is None:
                continue
            try:
                message = await salon.fetch_message(message_id)
            except discord.HTTPException:
                continue
            reaction = discord.utils.get(message.reactions, emoji=EMOJI)
            participants = [u.id async for u in reaction.users() if not u.bot] if reaction else []
            elus = tirer_gagnants(participants, nombre)
            texte = ", ".join(f"<@{u}>" for u in elus) if elus else "personne (aucun participant)"
            await salon.send(f"{EMOJI} Concours « {prix} » terminé : bravo à {texte} !")

    @cloture.before_loop
    async def avant(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Concours(bot))
