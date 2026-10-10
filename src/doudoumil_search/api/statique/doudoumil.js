// Autocomplétion des lieux et copie des citations ; tout le reste fonctionne sans JavaScript.
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  // champs vides non envoyés : l'adresse de la recherche reste lisible et partageable
  for (const formulaire of document.querySelectorAll("form[method=get]")) {
    formulaire.addEventListener("submit", () => {
      for (const champ of formulaire.elements) {
        if (champ.name && !champ.value) champ.disabled = true;
      }
    });
  }

  for (const champ of document.querySelectorAll("[data-suggestions-lieux]")) {
    const liste = document.getElementById(champ.getAttribute("list"));
    let minuterie;
    champ.addEventListener("input", () => {
      clearTimeout(minuterie);
      const texte = champ.value.trim();
      if (texte.length < 2) return;
      minuterie = setTimeout(async () => {
        const reponse = await fetch(`/api/lieux?q=${encodeURIComponent(texte)}`);
        if (!reponse.ok) return;
        liste.replaceChildren(
          ...(await reponse.json()).map(({ libelle, valeur }) => {
            const option = document.createElement("option");
            option.value = valeur;
            option.label = libelle;
            return option;
          })
        );
      }, 150);
    });
  }

  for (const bouton of document.querySelectorAll("[data-copier]")) {
    bouton.addEventListener("click", async () => {
      const texte = document.getElementById(bouton.dataset.copier).textContent;
      try {
        await navigator.clipboard.writeText(texte);
        bouton.textContent = "Copiée ✓";
      } catch {
        bouton.textContent = "Copie impossible";
      }
      setTimeout(() => { bouton.textContent = "Copier la citation"; }, 2000);
    });
  }
});
