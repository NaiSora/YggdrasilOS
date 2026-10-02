import { SlashCommandBuilder } from "discord.js";
import type { Commande } from "./index.js";

const ping: Commande = {
  data: new SlashCommandBuilder().setName("ping").setDescription("Vérifie que le bot répond"),
  async executer(interaction) {
    await interaction.reply(`Pong ! ${interaction.client.ws.ping} ms`);
  },
};

export default ping;
