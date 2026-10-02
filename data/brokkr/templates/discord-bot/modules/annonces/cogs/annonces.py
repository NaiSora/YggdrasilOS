"""Annonces : les lives Twitch et les nouvelles vidéos YouTube, dans un salon.

Réglages (.env) : ANNONCES_SALON_ID ; YOUTUBE_CHAINES (identifiants « UC… », séparés par des
virgules) ; TWITCH_CHAINES (pseudos) avec TWITCH_CLIENT_ID et TWITCH_CLIENT_SECRET
(https://dev.twitch.tv/console/apps). Vérification toutes les 5 minutes.
"""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET

import aiohttp
import discord
from discord.ext import commands, tasks

log = logging.getLogger(__name__)
ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"

SCHEMA = "CREATE TABLE IF NOT EXISTS annonces_vues (cle TEXT PRIMARY KEY);"


def parse_flux_youtube(xml: str) -> list[tuple[str, str, str]]:
    """Flux RSS d'une chaîne YouTube → [(identifiant, titre, lien)], le plus récent d'abord."""
    racine = ET.fromstring(xml)
    videos = []
    for entree in racine.findall(f"{ATOM}entry"):
        vid = entree.findtext(f"{YT}videoId") or ""
        titre = entree.findtext(f"{ATOM}title") or ""
        lien = entree.find(f"{ATOM}link")
        videos.append((vid, titre, lien.get("href", "") if lien is not None else ""))
    return videos


def liste(variable: str) -> list[str]:
    return [x.strip() for x in os.getenv(variable, "").split(",") if x.strip()]


class Annonces(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        salon = os.getenv("ANNONCES_SALON_ID", "").strip()
        self.salon_id = int(salon) if salon.isdigit() else None
        self.jeton_twitch = ""

    async def cog_load(self) -> None:
        await self.bot.db.ensure(SCHEMA)
        if self.salon_id:
            self.veille.start()

    async def cog_unload(self) -> None:
        self.veille.cancel()

    async def nouveau(self, cle: str) -> bool:
        return bool(await self.bot.db.execute("INSERT OR IGNORE INTO annonces_vues (cle) VALUES (?)", (cle,)))

    async def youtube(self, session: aiohttp.ClientSession, salon: discord.abc.Messageable, premier: bool) -> None:
        for chaine in liste("YOUTUBE_CHAINES"):
            url = f"https://www.youtube.com/feeds/videos.xml?channel_id={chaine}"
            async with session.get(url) as reponse:
                if reponse.status != 200:
                    continue
                videos = parse_flux_youtube(await reponse.text())
            for vid, titre, lien in videos[:5]:
                if await self.nouveau(f"yt:{vid}") and not premier:
                    await salon.send(f"📺 Nouvelle vidéo : **{titre}**\n{lien}")

    async def twitch(self, session: aiohttp.ClientSession, salon: discord.abc.Messageable) -> None:
        chaines, client, secret = liste("TWITCH_CHAINES"), os.getenv("TWITCH_CLIENT_ID"), os.getenv("TWITCH_CLIENT_SECRET")
        if not (chaines and client and secret):
            return
        if not self.jeton_twitch:
            async with session.post("https://id.twitch.tv/oauth2/token", params={
                    "client_id": client, "client_secret": secret, "grant_type": "client_credentials"}) as r:
                self.jeton_twitch = (await r.json()).get("access_token", "")
        entetes = {"Client-ID": client, "Authorization": f"Bearer {self.jeton_twitch}"}
        params = [("user_login", c) for c in chaines]
        async with session.get("https://api.twitch.tv/helix/streams", headers=entetes, params=params) as r:
            if r.status == 401:
                self.jeton_twitch = ""
                return
            lives = (await r.json()).get("data", [])
        for live in lives:
            if await self.nouveau(f"twitch:{live['id']}"):
                await salon.send(f"🔴 **{live['user_name']}** est en live : {live['title']}\n"
                                 f"https://twitch.tv/{live['user_login']}")

    @tasks.loop(minutes=5)
    async def veille(self) -> None:
        salon = self.bot.get_channel(self.salon_id)
        if salon is None:
            return
        premier = self.veille.current_loop == 0  # au démarrage : on mémorise sans annoncer le passé
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                await self.youtube(session, salon, premier)
                await self.twitch(session, salon)
        except (aiohttp.ClientError, TimeoutError) as exc:
            log.warning("annonces : %s", exc)

    @veille.before_loop
    async def avant(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Annonces(bot))
