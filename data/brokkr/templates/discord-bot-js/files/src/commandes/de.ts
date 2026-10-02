import { SlashCommandBuilder } from "discord.js";
import { lancer } from "../outils/hasard.js";
import type { Commande } from "./index.js";

const de: Commande = {
  data: new SlashCommandBuilder()
    .setName("de")
    .setDescription("Lancer un dé")
    .addIntegerOption((o) => o.setName("faces").setDescription("Nombre de faces (6)").setMinValue(2).setMaxValue(1000)),
  async executer(interaction) {
    const faces = interaction.options.getInteger("faces") ?? 6;
    await interaction.reply(`🎲 ${lancer(faces)} (sur ${faces})`);
  },
};

export default de;
