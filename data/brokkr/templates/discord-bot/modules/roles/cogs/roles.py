"""Rôles-réactions : réagir à un message pour recevoir un rôle, retirer la réaction pour le rendre."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

SCHEMA = """
CREATE TABLE IF NOT EXISTS roles_reaction (
    guild_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    emoji TEXT NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (message_id, emoji)
);
"""


class Roles(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        await self.bot.db.ensure(SCHEMA)

    @app_commands.command(name="role-reaction", description="Associer un émoji d'un message à un rôle")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def role_reaction(self, interaction: discord.Interaction, message_id: str, emoji: str,
                            role: discord.Role) -> None:
        if not message_id.isdigit():
            await interaction.response.send_message("Identifiant de message invalide.", ephemeral=True)
            return
        try:
            message = await interaction.channel.fetch_message(int(message_id))
            await message.add_reaction(emoji)
        except discord.HTTPException:
            await interaction.response.send_message("Message ou émoji introuvable (dans ce salon).", ephemeral=True)
            return
        await self.bot.db.execute("INSERT OR REPLACE INTO roles_reaction VALUES (?, ?, ?, ?)",
                                  (interaction.guild_id, message.id, str(emoji), role.id))
        await interaction.response.send_message(f"{emoji} → {role.mention} : c'est en place.", ephemeral=True)

    async def role_pour(self, payload: discord.RawReactionActionEvent) -> discord.Role | None:
        ligne = await self.bot.db.fetchone("SELECT role_id FROM roles_reaction WHERE message_id = ? AND emoji = ?",
                                           (payload.message_id, str(payload.emoji)))
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        return guild.get_role(ligne[0]) if ligne and guild else None

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        role = await self.role_pour(payload)
        if role and payload.member and not payload.member.bot:
            await payload.member.add_roles(role, reason="rôle-réaction")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        role = await self.role_pour(payload)
        if role:
            membre = await role.guild.fetch_member(payload.user_id)
            await membre.remove_roles(role, reason="rôle-réaction retiré")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Roles(bot))
