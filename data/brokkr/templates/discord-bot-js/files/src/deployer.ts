// Enregistre les commandes slash auprès de Discord : npm run deployer
import "dotenv/config";
import { REST, Routes } from "discord.js";
import { commandes } from "./commandes/index.js";

const { DISCORD_TOKEN, CLIENT_ID, DEV_GUILD_ID } = process.env;
if (!DISCORD_TOKEN || !CLIENT_ID) {
  console.error("DISCORD_TOKEN et CLIENT_ID sont nécessaires (.env).");
  process.exit(1);
}
const rest = new REST().setToken(DISCORD_TOKEN);
const corps = [...commandes.values()].map((c) => c.data.toJSON());
const route = DEV_GUILD_ID
  ? Routes.applicationGuildCommands(CLIENT_ID, DEV_GUILD_ID)
  : Routes.applicationCommands(CLIENT_ID);
await rest.put(route, { body: corps });
console.log(`${corps.length} commande(s) enregistrée(s)${DEV_GUILD_ID ? " sur le serveur de test" : ""}.`);
