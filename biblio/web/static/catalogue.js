// Filtres sur téléphone : panneau ouvert par le bouton « Filtres ».
// Sur grand écran, le dialog reste fermé et s'efface (voir style.css).
(function () {
  const panneau = document.getElementById("panneau-filtres");
  const ouvrir = document.getElementById("ouvrir-filtres");
  const petit = window.matchMedia("(max-width: 900px)");
  ouvrir.addEventListener("click", () => panneau.showModal());
  document.getElementById("fermer-filtres").addEventListener("click", () => panneau.close());
  panneau.addEventListener("click", (ev) => {           // un toucher sur le fond : le dialog lui-même
    if (ev.target === panneau) panneau.close();
  });
  petit.addEventListener?.("change", () => { if (!petit.matches && panneau.open) panneau.close(); });
})();

// Catalogue : cases à cocher et barre d'opérations groupées.
// Maj+clic coche toute la plage depuis la dernière case cliquée.
(function () {
  const lot = document.getElementById("lot");
  if (!lot) return;
  const cases = [...document.querySelectorAll('#table-catalogue input[name="ex"]')];
  const casePage = document.getElementById("choix-page");
  const compte = document.getElementById("lot-compte");
  const tous = document.getElementById("lot-tous");
  const boutonTout = document.getElementById("lot-tout");
  let derniere = null;

  function maj() {
    const n = cases.filter((c) => c.checked).length;
    if (n < cases.length) tous.value = "";
    lot.hidden = n === 0;
    casePage.checked = n > 0 && n === cases.length;
    casePage.indeterminate = n > 0 && n < cases.length;
    if (tous.value) {
      compte.textContent = tr("Les {n} résultats sont sélectionnés", { n: tous.dataset.total });
    } else {
      compte.textContent = (n > 1 ? tr("{n} livres sélectionnés", { n }) : tr("{n} livre sélectionné", { n }));
    }
    if (boutonTout) boutonTout.hidden = !!tous.value || n < cases.length;
    cases.forEach((c) => c.closest("tr").classList.toggle("choisi", c.checked));
  }

  cases.forEach((c, i) => c.addEventListener("click", (ev) => {
    if (ev.shiftKey && derniere !== null) {
      const [a, b] = [Math.min(derniere, i), Math.max(derniere, i)];
      for (let k = a; k <= b; k++) cases[k].checked = c.checked;
    }
    derniere = i;
    maj();
  }));
  casePage.addEventListener("change", () => {
    cases.forEach((c) => { c.checked = casePage.checked; });
    tous.value = "";
    maj();
  });
  boutonTout?.addEventListener("click", () => {
    cases.forEach((c) => { c.checked = true; });
    tous.value = "1";
    maj();
  });
  document.getElementById("lot-aucun").addEventListener("click", () => {
    cases.forEach((c) => { c.checked = false; });
    tous.value = "";
    maj();
  });
  // Don : un changement de propriétaire, à confirmer (ce n'est pas un prêt)
  const vers = document.getElementById("lot-vers");
  document.getElementById("lot-donner")?.addEventListener("click", (ev) => {
    const qui = vers.value.trim();
    if (!qui) {
      ev.preventDefault();
      vers.focus();
      return;
    }
    const n = tous.value ? tous.dataset.total : cases.filter((c) => c.checked).length;
    const question = n > 1
      ? tr("Donner ces {n} livres à {qui} ? C'est un don, pas un prêt : ils quitteront votre collection.", { n, qui })
      : tr("Donner ce livre à {qui} ? C'est un don, pas un prêt : il quittera votre collection.", { qui });
    if (!confirm(question)) ev.preventDefault();
  });

  // Un clic n'importe où sur la ligne (hors liens) coche la case
  document.querySelector("#table-catalogue tbody").addEventListener("click", (ev) => {
    if (ev.target.closest("a, input, button")) return;
    const c = ev.target.closest("tr")?.querySelector('input[name="ex"]');
    if (c) c.click();
  });
  maj();
})();
