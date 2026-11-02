// Page Statistiques : grille d'activité, et pour chaque carte une bascule
// liste / camembert / histogramme. Tout est dessiné en SVG, couleurs en variables CSS.
(function () {
  const DONNEES = JSON.parse(document.getElementById("stats-donnees").textContent);
  const LANGUE = document.documentElement.lang || "fr";
  const NS = "http://www.w3.org/2000/svg";
  const nombre = new Intl.NumberFormat(LANGUE);
  const fmtPourcent = new Intl.NumberFormat(LANGUE, { style: "percent", maximumFractionDigits: 0 });
  const pourcent = (x) => (x > 0 && x < 0.005 ? "<" + fmtPourcent.format(0.01) : fmtPourcent.format(x));
  const MAX_LISTE = 12;          // lignes affichées en liste
  const MAX_PARTS = 5;           // parts nommées du camembert (+ « Autres »)

  const livres = (n) => (n > 1 ? tr("{n} livres", { n: nombre.format(n) }) : tr("{n} livre", { n: nombre.format(n) }));
  const prets = (n) => (n > 1 ? tr("{n} prêts", { n: nombre.format(n) }) : tr("{n} prêt", { n: nombre.format(n) }));
  const exemplaires = (n) => tr("{n} exemplaires", { n: nombre.format(n) });
  const UNITES = {
    livres: { compte: livres, un: () => tr("livre"), plusieurs: () => tr("livres") },
    prets: { compte: prets, un: () => tr("prêt"), plusieurs: () => tr("prêts") },
    exemplaires: { compte: exemplaires, un: () => tr("exemplaire"), plusieurs: () => tr("exemplaires") },
  };
  function el(nom, attrs = {}, parent) {
    const e = document.createElementNS(NS, nom);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }
  function html(nom, classe, parent, texte) {
    const e = document.createElement(nom);
    if (classe) e.className = classe;
    if (texte !== undefined) e.textContent = texte;
    if (parent) parent.appendChild(e);
    return e;
  }
  function vide(zone, message) {
    zone.replaceChildren();
    html("p", "doux", zone, message || tr("Pas encore de données."));
  }

  // --- infobulle commune -------------------------------------------------------
  const bulle = document.getElementById("infobulle");
  function montrer(cible, valeur, libelle) {
    bulle.replaceChildren();
    html("b", "", bulle, valeur);
    html("span", "", bulle, libelle);
    bulle.hidden = false;
    const r = cible.getBoundingClientRect(), b = bulle.getBoundingClientRect();
    let x = r.left + r.width / 2 - b.width / 2;
    x = Math.max(8, Math.min(x, window.innerWidth - b.width - 8));
    const y = r.top - b.height - 8 < 8 ? r.bottom + 8 : r.top - b.height - 8;
    bulle.style.left = x + window.scrollX + "px";
    bulle.style.top = y + window.scrollY + "px";
  }
  function cacher() { bulle.hidden = true; }
  function survol(cible, valeur, libelle) {
    cible.setAttribute("tabindex", "0");
    const voir = () => montrer(cible, valeur, libelle);
    cible.addEventListener("pointerenter", voir);
    cible.addEventListener("focus", voir);
    cible.addEventListener("pointerleave", cacher);
    cible.addEventListener("blur", cacher);
  }

  // --- liste (barres horizontales) ---------------------------------------------
  function liste(zone, lignes, lien, unite = UNITES.livres) {
    const total = lignes.reduce((s, r) => s + r.nb, 0);
    const premiers = lignes.slice(0, MAX_LISTE);
    const maxi = Math.max(...premiers.map((r) => r.nb), 1);
    const boite = html("div", "barres", zone);
    for (const r of premiers) {
      const ligne = html("div", "barre", boite);
      const nom = html(lien || r.url ? "a" : "span", "nom", ligne, String(r.nom));
      if (lien || r.url) nom.href = r.url || lien + encodeURIComponent(r.nom);
      nom.title = String(r.nom);
      const piste = html("span", "piste", ligne);
      const rempli = html("span", "rempli", piste);
      rempli.style.width = (100 * r.nb) / maxi + "%";
      html("span", "n", ligne, nombre.format(r.nb));
      survol(piste, unite.compte(r.nb), `${r.nom} · ${pourcent(r.nb / total)}`);
    }
    if (lignes.length > MAX_LISTE) {
      const reste = lignes.slice(MAX_LISTE);
      html("p", "doux note", zone, tr("+ {n} autres ({livres})",
        { n: nombre.format(reste.length), livres: unite.compte(reste.reduce((s, r) => s + r.nb, 0)) }));
    }
  }

  // --- camembert (anneau) : 5 parts nommées au plus, le reste en « Autres » -------
  function camembert(zone, lignes, lien, unite = UNITES.livres) {
    const total = lignes.reduce((s, r) => s + r.nb, 0);
    let parts = lignes.slice(0, MAX_PARTS).map((r, i) => ({ ...r, classe: "s" + (i + 1) }));
    const reste = lignes.slice(MAX_PARTS).reduce((s, r) => s + r.nb, 0);
    if (reste) parts.push({ nom: tr("Autres"), nb: reste, classe: "autres", autres: lignes.length - MAX_PARTS });

    const conteneur = html("div", "anneau", zone);
    const svg = el("svg", { viewBox: "0 0 160 160", role: "img", "aria-label": tr("Camembert") }, conteneur);
    const R = 64, EP = 24, C = 2 * Math.PI * R;
    let debut = 0;
    const segments = [];
    for (const p of parts) {
      const part = p.nb / total;
      const seg = el("circle", {
        cx: 80, cy: 80, r: R, class: "segment " + p.classe, "stroke-width": EP,
        "stroke-dasharray": `${Math.max(part * C - (parts.length > 1 ? 2 : 0), 0.5)} ${C}`,
        "stroke-dashoffset": -debut * C, transform: "rotate(-90 80 80)",
      }, svg);
      debut += part;
      survol(seg, `${unite.compte(p.nb)} · ${pourcent(part)}`, p.nom);
      segments.push(seg);
    }
    const centre = el("text", { x: 80, y: 78, "text-anchor": "middle", class: "centre-n" }, svg);
    centre.textContent = nombre.format(total);
    const sous = el("text", { x: 80, y: 96, "text-anchor": "middle", class: "centre-l" }, svg);
    sous.textContent = total > 1 ? unite.plusieurs() : unite.un();

    // Légende : toujours visible, avec valeurs et parts (l'identité ne repose pas sur la couleur)
    const legende = html("ul", "legende", conteneur);
    parts.forEach((p, i) => {
      const li = html("li", "", legende);
      html("span", "pastille-couleur " + p.classe, li);
      const nom = html("span", "nom", li, p.autres ? `${p.nom} (${nombre.format(p.autres)})` : String(p.nom));
      nom.title = String(p.nom);
      html("span", "n", li, nombre.format(p.nb));
      html("span", "pc", li, pourcent(p.nb / total));
      li.addEventListener("pointerenter", () => segments[i].classList.add("actif"));
      li.addEventListener("pointerleave", () => segments[i].classList.remove("actif"));
    });
  }

  // --- histogramme ---------------------------------------------------------------
  function histogramme(zone, lignes) {
    // Décennies vides comprises, pour une échelle de temps régulière
    const parDecennie = new Map(lignes.map((r) => [Number(r.nom), r.nb]));
    const decennies = [...parDecennie.keys()];
    const points = [];
    for (let d = Math.min(...decennies); d <= Math.max(...decennies); d += 10) {
      points.push({ court: String(d), detail: tr("années {d}", { d }), nb: parDecennie.get(d) || 0 });
    }
    dessinerColonnes(zone, points, UNITES.livres);
  }

  // Colonnes déjà régulières, fournies avec leurs valeurs nulles (mois, tranches de pages)
  function colonnes(zone, lignes, lien, unite = UNITES.livres) {
    dessinerColonnes(zone, lignes.map((r) => ({ court: r.court || r.nom, detail: r.nom, nb: r.nb })), unite);
  }

  function dessinerColonnes(zone, premiers, unite) {
    const maxi = Math.max(...premiers.map((r) => r.nb));
    let pas = 1;
    for (let k = 0; Math.ceil(maxi / pas) > 4; k++) pas = [1, 2, 5][k % 3] * Math.pow(10, Math.floor(k / 3));
    const haut = Math.ceil(maxi / pas) * pas;

    const L = 560, H = 220, G = 34, B = 26, Hh = 20;         // largeur, hauteur, marge gauche, bas, haut (place de l'étiquette)
    const svg = el("svg", { viewBox: `0 0 ${L} ${H}`, class: "histogramme", role: "img",
                            "aria-label": tr("Histogramme") }, html("div", "zone-histo", zone));
    const y = (v) => H - B - ((H - B - Hh) * v) / haut;
    for (let v = 0; v <= haut; v += pas) {
      el("line", { x1: G, x2: L, y1: y(v), y2: y(v), class: v ? "grille" : "axe" }, svg);
      const t = el("text", { x: G - 6, y: y(v) + 4, "text-anchor": "end", class: "graduation" }, svg);
      t.textContent = nombre.format(v);
    }
    const bande = (L - G) / premiers.length;
    const largeur = Math.min(24, bande - 2);
    const etiquetteTous = bande > 34 ? 1 : bande > 17 ? 2 : 5;
    premiers.forEach((r, i) => {
      const x = G + i * bande + (bande - largeur) / 2;
      if (r.nb) {
        const h = H - B - y(r.nb), rayon = Math.min(4, h);
        el("path", { class: "colonne", d: `M${x},${H - B} v${-(h - rayon)} q0,${-rayon} ${rayon},${-rayon} h${largeur - 2 * rayon} q${rayon},0 ${rayon},${rayon} v${h - rayon} z` }, svg);
      }
      const cible = el("rect", { x: G + i * bande, y: Hh, width: bande, height: H - B - Hh, class: "cible" }, svg);
      survol(cible, unite.compte(r.nb), r.detail);
      if (i % etiquetteTous === 0) {
        const t = el("text", { x: G + i * bande + bande / 2, y: H - 8, "text-anchor": "middle", class: "graduation" }, svg);
        t.textContent = r.court;
      }
      if (r.nb === maxi) {                                        // étiquette sur la plus haute seulement
        const t = el("text", { x: x + largeur / 2, y: y(r.nb) - 6, "text-anchor": "middle", class: "valeur" }, svg);
        t.textContent = nombre.format(r.nb);
      }
    });
  }

  // --- durée des prêts en cours : une barre par livre sorti, en jours ------------------
  function durees(zone, lignes) {
    const fmtDate = new Intl.DateTimeFormat(LANGUE, { day: "numeric", month: "long", year: "numeric" });
    const jours = (n) => (n === 0 ? tr("aujourd'hui") : n > 1 ? tr("{n} jours", { n: nombre.format(n) }) : tr("{n} jour", { n: 1 }));
    const premiers = lignes.slice(0, MAX_LISTE);
    const maxi = Math.max(...premiers.map((r) => r.nb), 1);
    const boite = html("div", "barres", zone);
    for (const r of premiers) {
      const ligne = html("div", "barre barre-pret", boite);
      const nom = html("div", "nom", ligne);
      const titre = html("a", "", nom, r.nom);
      titre.href = r.url;
      titre.title = r.nom;
      html("small", "doux", nom, r.qui);
      const piste = html("span", "piste", ligne);
      html("span", "rempli", piste).style.width = Math.max((100 * r.nb) / maxi, 1.5) + "%";
      html("span", "n", ligne, r.nb === 0 ? tr("< 1 j") : tr("{n} j", { n: nombre.format(r.nb) }));
      survol(piste, jours(r.nb), tr("{titre} · prêté à {qui} le {date}",
        { titre: r.nom, qui: r.qui, date: fmtDate.format(new Date(r.depuis + "T12:00:00")) }));
    }
    if (lignes.length > MAX_LISTE) {
      html("p", "doux note", zone, tr("+ {n} autres prêts", { n: nombre.format(lignes.length - MAX_LISTE) }));
    }
  }

  // --- jauges : part de chaque total, sur une même échelle de 0 à 100 % ----------------
  function jauges(zone, lignes) {
    const boite = html("div", "barres", zone);
    for (const r of lignes) {
      const ligne = html("div", "barre", boite);
      html("span", "nom", ligne, r.nom).title = r.nom;
      const piste = html("span", "piste", ligne);
      html("span", "rempli", piste).style.width = (100 * r.nb) / r.total + "%";
      html("span", "n", ligne, pourcent(r.nb / r.total));
      survol(piste, tr("{n} sur {total}", { n: nombre.format(r.nb), total: nombre.format(r.total) }), r.nom);
    }
  }

  // --- réseau des prêts : personnes (nœuds) et prêts entre elles (liens) ---------------
  // Échelles absolues : une même taille veut toujours dire la même chose, quel que soit le graphe.
  const rayonNoeud = (livres) => Math.max(5, 3.6 * Math.log2(1 + (livres || 0)));
  const epaisseurLien = (nb) => 1.5 * Math.log2(1 + nb);
  const coupe = (nom, max) => (nom.length > max ? nom.slice(0, max - 1) + "…" : nom);

  // Disposition par forces, sans hasard : le même graphe s'affiche toujours de la même façon
  function disposer(noeuds, liens, L, H) {
    const n = noeuds.length, cx = L / 2, cy = H / 2;
    const ideal = Math.max(90, Math.min(190, Math.sqrt((L * H) / Math.max(n, 1)) * 0.75));
    noeuds.forEach((p, i) => {
      if (p.a_moi) { p.x = cx; p.y = cy; return; }
      const angle = (2 * Math.PI * i) / n;
      p.x = cx + (Math.min(L, H) / 3) * Math.cos(angle);
      p.y = cy + (Math.min(L, H) / 3) * Math.sin(angle);
    });
    const garder = (p) => {
      p.x = Math.max(p.r + 52, Math.min(L - p.r - 52, p.x));
      p.y = Math.max(p.r + 24, Math.min(H - p.r - 24, p.y));   // place du nom, au-dessus ou en dessous
    };
    for (let tour = 0; tour < 400; tour++) {
      const pas = 14 * (1 - tour / 400) + 0.5;
      noeuds.forEach((p) => { p.dx = 0; p.dy = 0; });
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const a = noeuds[i], b = noeuds[j];
          const ex = a.x - b.x || 0.01, ey = a.y - b.y || 0.01;
          const d = Math.hypot(ex, ey);
          const f = (0.3 * ideal * ideal) / Math.max(d - a.r - b.r, 8) / d;
          a.dx += ex * f; a.dy += ey * f;
          b.dx -= ex * f; b.dy -= ey * f;
        }
      }
      for (const l of liens) {
        const ex = l.a.x - l.b.x, ey = l.a.y - l.b.y;
        const d = Math.hypot(ex, ey) || 0.01;
        const f = (d - ideal - l.a.r - l.b.r) * 0.6;
        l.a.dx -= (ex / d) * f; l.a.dy -= (ey / d) * f;
        l.b.dx += (ex / d) * f; l.b.dy += (ey / d) * f;
      }
      for (const p of noeuds) {
        p.dx += (cx - p.x) * 0.25;                       // rappel vers le centre, plus fort en hauteur
        p.dy += (cy - p.y) * 0.5;
        const d = Math.hypot(p.dx, p.dy) || 1;
        p.x += (p.dx / d) * Math.min(d, pas);
        p.y += (p.dy / d) * Math.min(d, pas);
        garder(p);
      }
    }
    // Derniers écarts : aucun nœud ni nom ne doit en chevaucher un autre
    for (let tour = 0; tour < 60; tour++) {
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const a = noeuds[i], b = noeuds[j];
          const ex = a.x - b.x || 0.01, ey = a.y - b.y || 0.01;
          const d = Math.hypot(ex, ey), mini = a.r + b.r + 30;
          if (d < mini) {
            const f = (mini - d) / (2 * d);
            a.x += ex * f; a.y += ey * f;
            b.x -= ex * f; b.y -= ey * f;
            garder(a); garder(b);
          }
        }
      }
    }
  }

  function reseau(zone, aretes) {
    const noeuds = DONNEES.reseau_noeuds.map((p) => ({ ...p, r: rayonNoeud(p.livres), prets: 0, voisins: new Set() }));
    const parId = new Map(noeuds.map((p) => [p.id, p]));
    const liens = aretes.map((a) => ({ ...a, a: parId.get(a.de), b: parId.get(a.vers) }));
    for (const l of liens) {
      l.a.prets += l.nb; l.b.prets += l.nb;
      l.a.voisins.add(l); l.b.voisins.add(l);
    }
    const L = Math.max(zone.clientWidth, 300);
    const H = Math.max(320, Math.min(640, 220 + noeuds.length * 24));
    disposer(noeuds, liens, L, H);

    const svg = el("svg", { viewBox: `0 0 ${L} ${H}`, class: "reseau", role: "img",
                            "aria-label": tr("Réseau des prêts") }, zone);
    const groupeLiens = el("g", {}, svg), groupeNoeuds = el("g", {}, svg);
    function surligner(lies, noeudsLies) {
      svg.classList.add("survol");
      lies.forEach((g) => g.classList.add("lie"));
      noeudsLies.forEach((g) => g.classList.add("lie"));
    }
    function eteindre() {
      svg.classList.remove("survol");
      svg.querySelectorAll(".lie").forEach((g) => g.classList.remove("lie"));
    }
    const ecouter = (cible, entree) => {
      cible.addEventListener("pointerenter", entree);
      cible.addEventListener("focus", entree);
      cible.addEventListener("pointerleave", eteindre);
      cible.addEventListener("blur", eteindre);
    };
    for (const l of liens) {
      const g = el("g", { class: "lien" }, groupeLiens);
      const trait = { x1: l.a.x, y1: l.a.y, x2: l.b.x, y2: l.b.y };
      const w = epaisseurLien(l.nb);
      const visible = { ...trait, class: "lien-trait", "stroke-width": w };
      if (!l.en_cours) visible["stroke-dasharray"] = `${Math.max(w * 2, 5)} ${Math.max(w * 2, 5)}`;   // tous rendus
      el("line", visible, g);
      const cible = el("line", { ...trait, class: "lien-cible", "stroke-width": Math.max(w, 14) }, g);
      survol(cible, prets(l.nb), l.en_cours ? tr("{liens} · dont {n} en cours", { liens: l.nom, n: nombre.format(l.en_cours) }) : l.nom);
      l.g = g;
    }
    for (const p of noeuds) p.g = el(p.url ? "a" : "g", { class: "noeud" + (p.a_moi ? " moi" : p.livres === null ? " inconnu" : " ami") }, groupeNoeuds);
    for (const l of liens) {
      ecouter(l.g.querySelector(".lien-cible"), () => surligner([l.g], [l.a.g, l.b.g]));
    }
    for (const p of noeuds) {
      if (p.url) p.g.setAttribute("href", p.url);
      el("circle", { cx: p.x, cy: p.y, r: p.r }, p.g);
      // Le nom va du côté opposé au centre : il ne tombe pas sur le lien de la personne
      const nom = el("text", { x: p.x, y: p.y < H / 2 ? p.y - p.r - 7 : p.y + p.r + 15, "text-anchor": "middle" }, p.g);
      nom.textContent = coupe(p.nom, L < 500 ? 12 : 18);
      survol(p.g, p.livres === null ? tr("Bibliothèque inconnue") : livres(p.livres),
             p.prets ? `${p.nom} · ${prets(p.prets)}` : p.nom);
      ecouter(p.g, () => surligner([...p.voisins].map((l) => l.g),
                                   [p.g, ...[...p.voisins].map((l) => (l.a === p ? l.b : l.a).g)]));
    }
    legendeReseau(zone, noeuds, liens);
  }

  function legendeReseau(zone, noeuds, liens) {
    const legende = html("div", "legende-reseau", zone);
    const symbole = (classe, r, texte) => {
      const item = html("span", "", legende);
      const svg = el("svg", { width: 2 * r + 4, height: 2 * r + 4, "aria-hidden": "true", class: "reseau" }, item);
      el("circle", { cx: r + 2, cy: r + 2, r }, el("g", { class: "noeud " + classe }, svg));
      item.append(texte);
    };
    const trait = (w, texte, tirets) => {
      const item = html("span", "", legende);
      const svg = el("svg", { width: 34, height: 12, "aria-hidden": "true", class: "reseau" }, item);
      const attrs = { x1: 1, x2: 33, y1: 6, y2: 6, class: "lien-trait", "stroke-width": w };
      if (tirets) attrs["stroke-dasharray"] = "5 5";
      el("line", attrs, svg);
      item.append(texte);
    };
    symbole("moi", 6, tr("Vous"));
    if (noeuds.some((p) => !p.a_moi && p.livres !== null)) symbole("ami", 6, tr("Bibliothèque connue"));
    if (noeuds.some((p) => p.livres === null)) symbole("inconnu", 6, tr("Bibliothèque inconnue"));
    if (liens.some((l) => l.en_cours)) trait(2, tr("Au moins un prêt en cours"));
    if (liens.some((l) => !l.en_cours)) trait(2, tr("Tous rendus"), true);
    symbole("ami", rayonNoeud(10), tr("10 livres"));          // à la taille réelle du graphe
    symbole("ami", rayonNoeud(100), tr("100 livres"));
    trait(epaisseurLien(1), tr("1 prêt"));
    trait(epaisseurLien(5), tr("5 prêts"));
    trait(epaisseurLien(20), tr("20 prêts"));
  }

  // --- grille d'activité, façon GitHub ---------------------------------------------
  function activite(zone) {
    const parJour = DONNEES.activite;
    const jour = (d) => d.toISOString().slice(0, 10);
    const aujourdhui = new Date();
    aujourdhui.setHours(12, 0, 0, 0);
    // Début : le lundi d'il y a 52 semaines
    const debut = new Date(aujourdhui);
    debut.setDate(debut.getDate() - 364 - ((debut.getDay() + 6) % 7));
    const valeurs = Object.values(parJour).filter((v) => v > 0).sort((a, b) => a - b);
    const quantile = (q) => valeurs[Math.min(valeurs.length - 1, Math.floor(q * valeurs.length))] || 1;
    const seuils = [1, quantile(0.25) + 1, quantile(0.5) + 1, quantile(0.75) + 1];
    const niveau = (n) => (n <= 0 ? 0 : n < seuils[1] ? 1 : n < seuils[2] ? 2 : n < seuils[3] ? 3 : 4);

    const C = 12, E = 3, HAUT = 18, GAUCHE = 30;
    const semaines = Math.ceil(((aujourdhui - debut) / 86400000 + 1) / 7);
    const svg = el("svg", { viewBox: `0 0 ${GAUCHE + semaines * (C + E)} ${HAUT + 7 * (C + E)}`,
                            class: "grille-activite", role: "img",
                            "aria-label": tr("Livres ajoutés ces 12 derniers mois") }, zone);
    const fmtJour = new Intl.DateTimeFormat(LANGUE, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    const fmtMois = new Intl.DateTimeFormat(LANGUE, { month: "short" });
    const fmtJourSem = new Intl.DateTimeFormat(LANGUE, { weekday: "short" });
    [0, 2, 4].forEach((j) => {                                     // lun, mer, ven
      const d = new Date(2024, 0, 1 + j);                          // 1er janvier 2024 : un lundi
      const t = el("text", { x: 0, y: HAUT + j * (C + E) + C - 2, class: "graduation" }, svg);
      t.textContent = fmtJourSem.format(d);
    });
    let total = 0, record = { n: 0 }, moisPrecedent = -1;
    const mois = [];                                                // [colonne, date] de chaque début de mois
    for (let s = 0; s < semaines; s++) {
      for (let j = 0; j < 7; j++) {
        const d = new Date(debut);
        d.setDate(debut.getDate() + s * 7 + j);
        if (d > aujourdhui) break;
        if (j === 0 && d.getMonth() !== moisPrecedent) {
          moisPrecedent = d.getMonth();
          mois.push([s, d]);
        }
        const n = parJour[jour(d)] || 0;
        total += n;
        if (n > record.n) record = { n, d };
        const cell = el("rect", { x: GAUCHE + s * (C + E), y: HAUT + j * (C + E), width: C, height: C, rx: 2,
                                  class: "jour n" + niveau(n) }, svg);
        survol(cell, n ? livres(n) : tr("Aucun livre"), fmtJour.format(d));
      }
    }
    // Nom des mois au-dessus de leur première semaine ; un mois tronqué (moins de 3 semaines
    // avant le suivant) n'a pas d'étiquette, pour ne pas chevaucher sa voisine
    mois.forEach(([s, d], i) => {
      const suivant = mois[i + 1] ? mois[i + 1][0] : semaines;
      if (suivant - s < 3) return;
      const t = el("text", { x: GAUCHE + s * (C + E), y: 11, class: "graduation" }, svg);
      t.textContent = fmtMois.format(d);
    });
    zone.scrollLeft = zone.scrollWidth;                            // la semaine en cours en vue

    // Série en cours : jours consécutifs avec au moins un ajout, jusqu'à aujourd'hui (ou hier)
    let serie = 0;
    const d = new Date(aujourdhui);
    if (!parJour[jour(d)]) d.setDate(d.getDate() - 1);
    while (parJour[jour(d)]) { serie++; d.setDate(d.getDate() - 1); }

    const resume = document.getElementById("activite-resume");
    const morceaux = [tr("{livres} ajoutés", { livres: livres(total) })];
    if (record.n) morceaux.push(tr("record : {livres} le {date}", { livres: livres(record.n),
      date: new Intl.DateTimeFormat(LANGUE, { day: "numeric", month: "long" }).format(record.d) }));
    if (serie > 1) morceaux.push(tr("{n} jours d'affilée", { n: serie }));
    resume.textContent = morceaux.join(" · ");

    const legende = html("div", "legende-activite", zone.parentElement);
    html("span", "doux", legende, tr("Moins"));
    for (let k = 0; k <= 4; k++) {
      const c = html("span", "case n" + k, legende);
      c.title = k ? `≥ ${seuils[k - 1]}` : "0";
    }
    html("span", "doux", legende, tr("Plus"));
  }

  // --- cartes et bascules ----------------------------------------------------------
  const DESSINS = { liste, camembert, histogramme, colonnes, durees, jauges, reseau };
  // Ces vues ont besoin des lignes à zéro : un mois sans prêt, un prêt du jour même
  const GARDE_LES_ZEROS = new Set(["colonnes", "durees", "jauges"]);
  const fmtMoisLong = new Intl.DateTimeFormat(LANGUE, { month: "long", year: "numeric" });
  const fmtMoisCourt = new Intl.DateTimeFormat(LANGUE, { month: "short" });
  function memo(cle, valeur) {
    try {
      if (valeur === undefined) return localStorage.getItem("stats." + cle);
      localStorage.setItem("stats." + cle, valeur);
    } catch (e) { return null; }
  }

  for (const carte of document.querySelectorAll(".graphique[data-serie]")) {
    const serie = carte.dataset.serie;
    const toutes = DONNEES[serie] || [];
    for (const r of toutes) {
      if (!r.mois) continue;
      const [an, mois] = r.mois.split("-").map(Number);
      r.nom = fmtMoisLong.format(new Date(an, mois - 1, 1));
      r.court = fmtMoisCourt.format(new Date(an, mois - 1, 1));
    }
    const lignes = toutes.filter((r) => r.nb > 0);
    const unite = UNITES[carte.dataset.unite] || UNITES.livres;
    const vues = carte.dataset.vues.split(",");
    const zone = carte.querySelector(".zone-graphique");
    const bascule = carte.querySelector(".bascule");
    function afficher(vue) {
      cacher();
      zone.replaceChildren();
      const garde = GARDE_LES_ZEROS.has(vue);
      const aDonnees = vue === "colonnes" ? lignes.length : (garde ? toutes : lignes).length;
      if (!aDonnees) vide(zone, carte.dataset.vide);
      else DESSINS[vue](zone, garde ? toutes : lignes, carte.dataset.lien, unite);
      if (bascule) {
        const i = vues.indexOf(vue);
        bascule.style.setProperty("--i", i);
        bascule.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.vue === vue));
      }
      memo(serie, vue);
    }
    bascule?.addEventListener("click", (ev) => {
      const b = ev.target.closest("button");
      if (b) afficher(b.dataset.vue);
    });
    const choisie = memo(serie);
    afficher(vues.includes(choisie) ? choisie : vues[0]);
  }
  activite(document.getElementById("activite"));
  window.addEventListener("scroll", cacher, { passive: true });
})();
