// Filtre le sommaire en direct
document.getElementById("recherche").addEventListener("input", (e) => {
  const mot = e.target.value.toLowerCase();
  document.querySelectorAll("nav a").forEach((a) => {
    a.hidden = mot && !a.textContent.toLowerCase().includes(mot);
  });
});
