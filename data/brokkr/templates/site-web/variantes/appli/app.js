// {{name}} — une liste de tâches qui se souvient (localStorage).
const CLE = "{{slug}}-taches";
const liste = document.getElementById("taches");
const charger = () => JSON.parse(localStorage.getItem(CLE) || "[]");
const garder = (taches) => localStorage.setItem(CLE, JSON.stringify(taches));

function afficher() {
  liste.replaceChildren();
  charger().forEach((tache, i) => {
    const li = document.createElement("li");
    const case_ = Object.assign(document.createElement("input"), { type: "checkbox", checked: tache.faite });
    case_.addEventListener("change", () => { const t = charger(); t[i].faite = case_.checked; garder(t); afficher(); });
    const texte = Object.assign(document.createElement("span"), { textContent: " " + tache.texte + " " });
    if (tache.faite) texte.style.textDecoration = "line-through";
    const suppr = Object.assign(document.createElement("button"), { textContent: "✕" });
    suppr.addEventListener("click", () => { const t = charger(); t.splice(i, 1); garder(t); afficher(); });
    li.append(case_, texte, suppr);
    liste.append(li);
  });
}

document.getElementById("ajout").addEventListener("submit", (e) => {
  e.preventDefault();
  const champ = document.getElementById("texte");
  garder([...charger(), { texte: champ.value.trim(), faite: false }]);
  champ.value = "";
  afficher();
});
afficher();
