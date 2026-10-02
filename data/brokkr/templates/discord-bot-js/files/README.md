# {{name}}

Bot Discord en TypeScript forgé par **Brokkr** sur Yggdrasil le {{date}}.

```bash
npm install
cp .env.example .env      # jeton, identifiant de l'application
npm run deployer          # enregistre les commandes slash
npm run dev               # relance à chaque modification
npm test
```

Ajoute une commande : un fichier dans `src/commandes/`, puis une ligne dans `src/commandes/index.ts`.
Hébergement : `brokkr deploy` (Bifröst).
