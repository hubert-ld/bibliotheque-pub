// Traduction des textes des scripts : window.I18N est fourni par la page (vide en français).
function tr(texte, valeurs) {
  let s = (window.I18N && window.I18N[texte]) || texte;
  if (valeurs) for (const [k, v] of Object.entries(valeurs)) s = s.split("{" + k + "}").join(v);
  return s;
}

// Thème : Auto (celui de l'appareil), Clair ou Sombre. Mémorisé sur cet appareil seulement :
// l'ordinateur et le téléphone peuvent avoir chacun le leur.
(function () {
  const boutons = document.querySelectorAll("[data-theme-choix]");
  const meta = document.querySelector('meta[name="theme-color"]');
  const systemeSombre = window.matchMedia("(prefers-color-scheme: dark)");
  function lire() {
    try { return localStorage.getItem("theme") || "auto"; } catch (e) { return "auto"; }
  }
  function appliquer(theme) {
    if (theme === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    boutons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeChoix === theme)));
    const sombre = theme === "dark" || (theme === "auto" && systemeSombre.matches);
    if (meta) meta.content = sombre ? "#1a1613" : "#7a2a1c";
  }
  boutons.forEach((b) => b.addEventListener("click", () => {
    const theme = b.dataset.themeChoix;
    try {
      if (theme === "auto") localStorage.removeItem("theme"); else localStorage.setItem("theme", theme);
    } catch (e) { /* stockage indisponible : le choix vaut pour cette page */ }
    appliquer(theme);
  }));
  systemeSombre.addEventListener?.("change", () => appliquer(lire()));
  appliquer(lire());
})();

// Navigation qui défile sur téléphone : la page en cours reste en vue.
document.querySelector(".topbar nav a.actif")?.scrollIntoView({ inline: "center", block: "nearest" });

// Indicateur « en recherche » de la barre du haut, mis à jour toutes les 3 s.
(function () {
  const zone = document.getElementById("file-attente");
  const nb = document.getElementById("file-nb");
  if (!zone) return;
  async function maj() {
    try {
      const r = await fetch("/api/etat");
      const d = await r.json();
      nb.textContent = d.en_attente;
      zone.classList.toggle("vide", !d.en_attente);
    } catch (e) { /* serveur arrêté : on réessaiera */ }
  }
  setInterval(maj, 3000);
})();

// Couverture absente : on affiche les initiales du titre.
function couvertureAbsente(img) {
  const boite = img.parentElement;
  img.remove();
  const s = document.createElement("span");
  s.className = "initiales";
  s.textContent = (boite.dataset.titre || "?").replace(/^(le|la|les|l'|un|une|the|a)\s+/i, "").slice(0, 2).toUpperCase();
  boite.appendChild(s);
}

// Couverture Open Library « vide » (image 1×1 renvoyée quand aucune n'existe)
function couvertureChargee(img) {
  if (img.naturalWidth < 5) couvertureAbsente(img);
}
