// {{name}} — bot Discord forgé par Brokkr sur Yggdrasil.
import "dotenv/config";
import { Client, Events, GatewayIntentBits } from "discord.js";
import { commandes } from "./commandes/index.js";

const jeton = process.env.DISCORD_TOKEN;
if (!jeton || jeton === "colle-ton-jeton-ici") {
  console.error("DISCORD_TOKEN manquant : copie .env.example en .env et colle ton jeton.");
  process.exit(1);
}

const client = new Client({ intents: [GatewayIntentBits.Guilds] });

client.once(Events.ClientReady, (c) => console.log(`connecté en tant que ${c.user.tag}`));

client.on(Events.InteractionCreate, async (interaction) => {
  if (!interaction.isChatInputCommand()) return;
  const commande = commandes.get(interaction.commandName);
  if (!commande) return;
  try {
    await commande.executer(interaction);
  } catch (erreur) {
    console.error(erreur);
    const reponse = { content: "Une erreur est survenue.", ephemeral: true };
    if (interaction.replied || interaction.deferred) await interaction.followUp(reponse);
    else await interaction.reply(reponse);
  }
});

client.login(jeton);
