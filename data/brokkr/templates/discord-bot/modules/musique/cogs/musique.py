"""Musique : /jouer, /pause, /suivant, /file, /stop dans un salon vocal.

Le son passe par un serveur Lavalink : « bifrost up lavalink », puis LAVALINK_URI et
LAVALINK_PASSWORD dans .env.
"""

from __future__ import annotations

import logging
import os

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)


def duree(ms: int) -> str:
    minutes, secondes = divmod(ms // 1000, 60)
    return f"{minutes}:{secondes:02d}"


class Musique(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        noeud = wavelink.Node(uri=os.getenv("LAVALINK_URI", "http://localhost:2333"),
                              password=os.getenv("LAVALINK_PASSWORD", ""))
        await wavelink.Pool.connect(nodes=[noeud], client=self.bot, cache_capacity=100)

    async def lecteur(self, interaction: discord.Interaction) -> wavelink.Player | None:
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice:
            await interaction.response.send_message("Rejoins d'abord un salon vocal.", ephemeral=True)
            return None
        lecteur = interaction.guild.voice_client
        if lecteur is None:
            lecteur = await interaction.user.voice.channel.connect(cls=wavelink.Player)
            lecteur.autoplay = wavelink.AutoPlayMode.partial  # enchaîne la file, sans suggestions
        return lecteur

    @app_commands.command(name="jouer", description="Jouer un morceau (titre ou lien)")
    @app_commands.guild_only()
    async def jouer(self, interaction: discord.Interaction, recherche: str) -> None:
        lecteur = await self.lecteur(interaction)
        if lecteur is None:
            return
        await interaction.response.defer()
        resultats = await wavelink.Playable.search(recherche)
        if not resultats:
            await interaction.followup.send("Rien trouvé.")
            return
        morceau = resultats[0] if isinstance(resultats, list) else resultats.tracks[0]
        if lecteur.playing:
            lecteur.queue.put(morceau)
            await interaction.followup.send(f"➕ Dans la file : **{morceau.title}** ({duree(morceau.length)})")
        else:
            await lecteur.play(morceau)
            await interaction.followup.send(f"🎶 **{morceau.title}** ({duree(morceau.length)})")

    @app_commands.command(name="pause", description="Mettre en pause ou reprendre")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        lecteur = interaction.guild.voice_client
        if not isinstance(lecteur, wavelink.Player):
            await interaction.response.send_message("Rien ne joue.", ephemeral=True)
            return
        await lecteur.pause(not lecteur.paused)
        await interaction.response.send_message("⏸️ Pause." if lecteur.paused else "▶️ Reprise.")

    @app_commands.command(name="suivant", description="Passer au morceau suivant")
    @app_commands.guild_only()
    async def suivant(self, interaction: discord.Interaction) -> None:
        lecteur = interaction.guild.voice_client
        if not isinstance(lecteur, wavelink.Player):
            await interaction.response.send_message("Rien ne joue.", ephemeral=True)
            return
        await lecteur.skip(force=True)
        await interaction.response.send_message("⏭️ Suivant.")

    @app_commands.command(name="file", description="Les morceaux à venir")
    @app_commands.guild_only()
    async def file(self, interaction: discord.Interaction) -> None:
        lecteur = interaction.guild.voice_client
        if not isinstance(lecteur, wavelink.Player) or lecteur.queue.is_empty:
            await interaction.response.send_message("La file est vide.", ephemeral=True)
            return
        texte = "\n".join(f"{i}. {m.title}" for i, m in enumerate(list(lecteur.queue)[:10], 1))
        await interaction.response.send_message(f"**À venir :**\n{texte}")

    @app_commands.command(name="stop", description="Arrêter la musique et quitter le vocal")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        lecteur = interaction.guild.voice_client
        if isinstance(lecteur, wavelink.Player):
            lecteur.queue.clear()
            await lecteur.disconnect()
        await interaction.response.send_message("⏹️ Silence.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Musique(bot))
