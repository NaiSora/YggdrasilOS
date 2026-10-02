import type { ChatInputCommandInteraction } from "discord.js";
import de from "./de.js";
import ping from "./ping.js";

export interface Commande {
  data: { name: string; toJSON(): unknown };
  executer(interaction: ChatInputCommandInteraction): Promise<void>;
}

export const commandes = new Map<string, Commande>([ping, de].map((c) => [c.data.name, c]));
