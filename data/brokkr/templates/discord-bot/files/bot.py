"""{{name}} — bot Discord forgé par Brokkr sur Yggdrasil.

Modules : {{modules}}.
Les fichiers du dossier cogs/ sont chargés automatiquement au démarrage : ajoute un
cogs/mon_module.py avec une fonction `setup(bot)` (ou « brokkr add module <id> »).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import Database

load_dotenv()
log = logging.getLogger("{{slug}}")

COGS_DIR = Path(__file__).parent / "cogs"


class Bot(commands.Bot):
    def __init__(self, db: Database) -> None:
        intents = discord.Intents.default()
        # Le contenu des messages est un intent « privilégié » : ne l'active que si
        # tu en as besoin, et coche-le aussi sur le portail développeur Discord.
        intents.message_content = os.getenv("MESSAGE_CONTENT", "0") == "1"
        super().__init__(command_prefix=os.getenv("PREFIX", "!"), intents=intents, help_command=None)
        self.db = db

    async def setup_hook(self) -> None:
        await self.db.connect()
        for path in sorted(COGS_DIR.glob("*.py")):
            if path.stem.startswith("_"):
                continue
            await self.load_extension(f"cogs.{path.stem}")
            log.info("module chargé : %s", path.stem)
        guild_id = os.getenv("DEV_GUILD_ID", "").strip()
        if guild_id:
            # Sur un serveur de test, les commandes slash apparaissent immédiatement.
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()
        log.info("%d commande(s) slash synchronisée(s)", len(synced))

    async def on_ready(self) -> None:
        log.info("connecté en tant que %s", self.user)

    async def close(self) -> None:
        await self.db.close()
        await super().close()


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-8s %(name)s : %(message)s",
    )
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "colle-ton-jeton-ici":
        raise SystemExit("DISCORD_TOKEN manquant : copie .env.example en .env et colle ton jeton.")
    db = Database(os.getenv("DATABASE_PATH", "data/{{slug}}.db"))
    async with Bot(db) as bot:
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
