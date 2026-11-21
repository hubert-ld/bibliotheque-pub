// Administration : test des catalogues, à la demande et à l'ouverture si le dernier est ancien.
(function () {
  const bouton = document.getElementById("tester-catalogues");
  if (!bouton) return;
  async function tester() {
    bouton.disabled = true;
    const texte = bouton.textContent;
    bouton.textContent = tr("Test en cours…");
    try {
      await fetch("/admin/catalogues/tester", { method: "POST" });
      location.reload();
    } catch (e) {
      bouton.disabled = false;
      bouton.textContent = texte;
    }
  }
  bouton.addEventListener("click", tester);
  if (bouton.dataset.auto) tester();
})();
