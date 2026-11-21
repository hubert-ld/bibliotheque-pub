// Poste de scan : la douchette se comporte comme un clavier (code + Entrée).
(function () {
  const LIEUX = JSON.parse(document.getElementById("lieux-data").textContent);
  const $ = (id) => document.getElementById(id);
  const input = $("code"), flux = $("flux"), selLieu = $("lieu"), selEtagere = $("etagere"), selRangee = $("rangee");
  const PEUT_SCANNER = JSON.parse($("droits-scan").textContent).scanner;
  const DETAILS = {
    ajout: tr("Chaque livre scanné est ajouté à la collection, rangé à l'emplacement choisi."),
    deplacement: tr("Chaque livre scanné est déplacé vers l'emplacement choisi."),
    ou: tr("Scannez un livre pour savoir où il est rangé."),
    inventaire: tr("Vérifiez une étagère : scannez tout ce qu'elle contient, le rapport liste les absents et les intrus."),
  };
  const compteurs = { scans: 0, ok: 0, alertes: 0 };
  const enAttente = new Map();          // numéro de notice -> éléments du flux à compléter
  const tactile = window.matchMedia("(pointer: coarse)").matches;

  // --- état mémorisé (par navigateur) -------------------------------------
  const memo = {
    get(k, d) { try { return localStorage.getItem("scan." + k) ?? d; } catch (e) { return d; } },
    set(k, v) { try { v == null ? localStorage.removeItem("scan." + k) : localStorage.setItem("scan." + k, v); } catch (e) {} },
  };
  let mode = memo.get("mode", "ajout");
  let inventaire = memo.get("inventaire", null) ? JSON.parse(memo.get("inventaire")) : null;
  $("son").checked = memo.get("son", "1") === "1";
  // Comment on scanne : douchette, caméra ou à la main. La caméra a sa propre mémoire (camera.js)
  function saisieMemorisee() {
    const s = memo.get("saisie", null);
    return s === "douchette" || s === "main" ? s : (tactile ? "main" : "douchette");
  }
  let saisie = saisieMemorisee();

  function remplirEtageres() {
    const lieu = LIEUX.find((l) => String(l.id) === selLieu.value);
    selEtagere.innerHTML = '<option value="">' + (lieu ? tr("Tout le lieu") : "—") + "</option>";
    (lieu ? lieu.etageres : []).forEach((e) => {
      const o = document.createElement("option");
      o.value = e.id; o.textContent = e.nom; selEtagere.appendChild(o);
    });
    selEtagere.disabled = !lieu || !lieu.etageres.length;
    remplirRangees();
  }
  function etagereChoisie() {
    const lieu = LIEUX.find((l) => String(l.id) === selLieu.value);
    return lieu ? lieu.etageres.find((e) => String(e.id) === selEtagere.value) : null;
  }
  function remplirRangees() {
    const e = etagereChoisie();
    selRangee.innerHTML = '<option value="">' + (e ? tr("Toute l'étagère") : "—") + "</option>";
    (e ? e.rangees : []).forEach((r) => {
      const o = document.createElement("option");
      o.value = r.id; o.textContent = r.nom; selRangee.appendChild(o);
    });
    $("champ-rangee").hidden = !e || !e.rangees.length;
  }
  selLieu.value = memo.get("lieu", "");
  if (selLieu.value !== memo.get("lieu", "")) selLieu.value = "";
  remplirEtageres();
  selEtagere.value = memo.get("etagere", "");
  remplirRangees();
  selRangee.value = memo.get("rangee", "");
  selLieu.addEventListener("change", () => { remplirEtageres(); sauverEmplacement(); });
  selEtagere.addEventListener("change", () => { remplirRangees(); sauverEmplacement(); });
  selRangee.addEventListener("change", sauverEmplacement);
  // Livre sans code-barre : la page d'ajout manuel reprend l'emplacement courant
  $("lien-manuel")?.addEventListener("click", (ev) => {
    if (selLieu.value) ev.currentTarget.href = "/manuel?emplacement=" + encodeURIComponent(selLieu.value + ":" + selEtagere.value + (selRangee.value ? ":" + selRangee.value : ""));
  });
  function sauverEmplacement() {
    memo.set("lieu", selLieu.value); memo.set("etagere", selEtagere.value); memo.set("rangee", selRangee.value);
    if (inventaire && (String(inventaire.lieu_id) !== selLieu.value || String(inventaire.etagere_id || "") !== selEtagere.value
                       || String(inventaire.rangee_id || "") !== selRangee.value)) {
      finInventaire();
    }
    // Une liste changée par le code (étiquette, réglages de la caméra) ne déclenche pas « change »
    document.dispatchEvent(new CustomEvent("scan:emplacement"));
    focus();
  }
  function nomEmplacement() {
    const l = LIEUX.find((x) => String(x.id) === selLieu.value);
    if (!l) return tr("Non localisé");
    const e = l.etageres.find((x) => String(x.id) === selEtagere.value);
    if (!e) return l.nom;
    const r = e.rangees.find((x) => String(x.id) === selRangee.value);
    return r ? `${l.nom} › ${e.nom} › ${r.nom}` : `${l.nom} › ${e.nom}`;
  }

  // --- modes ---------------------------------------------------------------
  function choisirMode(m) {
    mode = m; memo.set("mode", m);
    document.querySelectorAll(".modes button").forEach((b) => b.classList.toggle("actif", b.dataset.mode === m));
    $("scan").classList.toggle("mode-inventaire", m === "inventaire");
    $("mode-detail").textContent = DETAILS[m];
    majInvite();
    focus();
  }
  document.querySelectorAll(".modes button").forEach((b) => b.addEventListener("click", () => choisirMode(b.dataset.mode)));
  function majInvite() {
    input.placeholder = mode === "inventaire" && !inventaire ? tr("Commencez l'inventaire…")
      : saisie === "main" ? tr("Tapez l'ISBN ou le code-barres…") : tr("Scannez un livre…");
  }

  // --- saisie : douchette, caméra ou à la main ------------------------------
  // `geste` : appelé pendant un toucher, seul moment où iOS accepte de donner le focus.
  function choisirSaisie(s, geste = false) {
    saisie = s;
    if (s !== "camera") memo.set("saisie", s);
    document.querySelectorAll(".saisies button").forEach((b) => b.classList.toggle("actif", b.dataset.saisie === s));
    $("scan").dataset.saisie = s;
    input.blur();                        // iOS ne relit `inputmode` qu'en reprenant le focus
    input.setAttribute("inputmode", s === "douchette" ? "none" : "numeric");
    input.value = "";
    majInvite();
    majVoyant();
    document.dispatchEvent(new CustomEvent("scan:saisie", { detail: { saisie: s } }));
    if (s !== "camera" && geste) input.focus();
    focus();
  }
  document.querySelectorAll(".saisies button").forEach((b) => b.addEventListener("click", () => choisirSaisie(b.dataset.saisie, true)));
  function majVoyant() {
    $("voyant-texte").textContent = tactile && !sonDebloque ? tr("Touchez l'écran une fois pour activer les bips") : tr("Prêt : lisez un code");
  }

  // --- inventaire ----------------------------------------------------------
  function afficherInventaire() {
    $("inv-inactif").hidden = !!inventaire;
    $("inv-actif").hidden = !inventaire;
    if (inventaire) {
      $("inv-zone").textContent = inventaire.emplacement;
      $("inv-rapport").href = "/inventaire/" + inventaire.id;
      majInventaire();
    }
    choisirMode(mode);
  }
  async function majInventaire() {
    if (!inventaire) return;
    const r = await fetch("/api/inventaire/" + inventaire.id).then((r) => r.json());
    if (!r.ok || r.clos) { finInventaire(); return; }
    $("inv-presents").textContent = r.presents;
    $("inv-manquants").textContent = r.manquants;
    $("inv-ailleurs").textContent = r.ailleurs + r.inconnus;
  }
  function finInventaire() { inventaire = null; memo.set("inventaire", null); afficherInventaire(); }
  $("inv-demarrer").addEventListener("click", async () => {
    if (!selLieu.value) { alerte(tr("Choisissez d'abord le lieu à inventorier.")); return; }
    const r = await fetch("/api/inventaire", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lieu_id: selLieu.value, etagere_id: selEtagere.value, rangee_id: selRangee.value }),
    }).then((r) => r.json());
    if (!r.ok) { alerte(r.message); return; }
    inventaire = { id: r.id, lieu_id: r.lieu_id, etagere_id: r.etagere_id, rangee_id: r.rangee_id, emplacement: r.emplacement };
    memo.set("inventaire", JSON.stringify(inventaire));
    afficherInventaire();
  });
  $("inv-abandon").addEventListener("click", finInventaire);

  // --- sons ----------------------------------------------------------------
  let audio;
  function contexteAudio() {
    if (!audio) {
      // iPhone : catégorie « lecture » pour que les bips s'entendent même en mode silencieux
      // (Safari 16.4+). Contrepartie : une musique en cours peut se mettre en pause.
      try { if (navigator.audioSession) navigator.audioSession.type = "playback"; } catch (e) {}
      audio = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audio.state !== "running") audio.resume().catch(() => {});
    return audio;
  }
  function bip(type) {
    if (!$("son").checked) return;
    try {
      const audio = contexteAudio();
      const notes = { ok: [[880, 0.09]], alerte: [[660, 0.1], [520, 0.14]], erreur: [[180, 0.32]] }[type];
      let t = audio.currentTime;
      notes.forEach(([f, d]) => {
        const o = audio.createOscillator(), g = audio.createGain();
        o.type = type === "erreur" ? "square" : "sine"; o.frequency.value = f;
        g.gain.setValueAtTime(0.18, t); g.gain.exponentialRampToValueAtTime(0.001, t + d);
        o.connect(g).connect(audio.destination); o.start(t); o.stop(t + d); t += d + 0.03;
      });
    } catch (e) {}
  }
  $("son").addEventListener("change", () => memo.set("son", $("son").checked ? "1" : "0"));
  // iPhone : le son n'est autorisé qu'après un geste, et un son doit démarrer pendant ce
  // geste (un son vide suffit). iOS le suspend parfois (caméra, appel) : on rouvre à chaque toucher.
  let sonDebloque = false;
  function debloquerSon() {
    try {
      const ctx = contexteAudio();
      const vide = ctx.createBufferSource();
      vide.buffer = ctx.createBuffer(1, 1, 22050);
      vide.connect(ctx.destination);
      vide.start(0);
      if (!sonDebloque) { sonDebloque = true; majVoyant(); }
    } catch (e) {}
  }
  document.addEventListener("touchend", debloquerSon, { passive: true });
  document.addEventListener("click", debloquerSon);
  function eclair(type) {
    const f = $("flash-ecran");
    f.className = "flash-ecran " + type + " visible";
    requestAnimationFrame(() => requestAnimationFrame(() => f.classList.remove("visible")));
  }

  // --- flux des scans -------------------------------------------------------
  const LIBELLES = { ajoute: tr("Ajouté"), doublon: tr("Déjà possédé"), rebond: tr("Double lecture"), deplace: tr("Déplacé"),
    deja_la: tr("Déjà là"), inconnu: tr("Inconnu"), trouve: tr("Trouvé"), present: tr("Présent"), ailleurs: tr("Mal rangé"),
    erreur: tr("Erreur"), attente: tr("En attente"), emplacement: tr("Emplacement") };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function couv(n) {
    const t = esc(n && n.titre || "?");
    if (n && n.couverture_url) {
      return `<span class="couv" data-titre="${t}"><img src="/couverture/${esc(n.id)}?v=${esc(n.uid)}" alt="" onerror="couvertureAbsente(this)" onload="couvertureChargee(this)"></span>`;
    }
    return `<span class="couv" data-titre="${t}"><span class="initiales">${t.slice(0, 2).toUpperCase()}</span></span>`;
  }
  function corpsNotice(n, code) {
    if (!n && !code) return `<div class="titre">${tr("Code non reconnu")}</div><div class="meta"></div>`;
    if (!n) return `<div class="titre">${esc(code)}</div><div class="meta"></div>`;
    if (n.statut === "en_attente") {
      return `<div class="titre"><span class="chargement"></span></div><div class="meta">${esc(code)} · ${tr("recherche dans les catalogues…")}</div>`;
    }
    if (n.statut === "introuvable" || n.statut === "erreur") {
      return `<div class="titre">${esc(code)}</div><div class="meta">${n.statut === "erreur" ? tr("Catalogues injoignables, nouvel essai plus tard") : tr("Introuvable dans les catalogues")} · <a href="/livre/${esc(n.id)}">${tr("compléter à la main")}</a></div>`;
    }
    const auteurs = (n.auteurs || []).slice(0, 2).join(", ");
    const meta = [auteurs, n.editeur, n.annee].filter(Boolean).map(esc).join(" · ");
    return `<div class="titre"><a href="/livre/${esc(n.id)}">${esc(n.titre || tr("Sans titre"))}</a></div><div class="meta">${meta}</div>`;
  }
  function rendre(res) {
    $("flux-vide")?.remove();
    const el = document.createElement("article");
    const code = res.code || "";
    el.className = "scan-item " + res.statut;
    const n = res.notice;
    const cote = n && n.cote ? `<span class="cote">${esc(n.cote)}</span>` : "";
    const annuler = res.exemplaire_id && (res.statut === "ajoute" || res.statut === "doublon")
      ? `<button type="button" class="petit" data-annuler="${res.exemplaire_id}">${tr("Annuler")}</button>` : "";
    const retirer = res.statut === "attente" ? `<button type="button" class="petit" data-retirer="${res.quand}">${tr("Annuler")}</button>` : "";
    const message = res.statut === "ajoute" ? (res.emplacement ? "→ " + res.emplacement : "") : res.message;
    el.innerHTML = `${couv(n)}<div class="corps">${corpsNotice(n, code)}
      <div class="message"><span class="badge ${esc(res.statut)}">${LIBELLES[res.statut] || res.statut}</span> ${esc(message || "")}</div></div>
      <div class="actions"><span class="cote-slot">${cote}</span>${annuler}${retirer}</div>`;
    flux.prepend(el);
    if (res.exemplaire_id && (res.statut === "ajoute" || res.statut === "doublon")) {
      dernierAjout = { id: res.exemplaire_id, el };
    }
    if (n && n.statut === "en_attente") {
      if (!enAttente.has(n.id)) enAttente.set(n.id, []);
      enAttente.get(n.id).push(el);
    }
    while (flux.children.length > 80) flux.lastElementChild.remove();
    return el;
  }
  flux.addEventListener("click", async (ev) => {
    const gardé = ev.target.closest("[data-retirer]");
    if (gardé) {
      retirerDeLaFile(Number(gardé.dataset.retirer));
      focus();
      return;
    }
    const b = ev.target.closest("[data-annuler]");
    if (!b) return;
    const r = await fetch("/api/annuler/" + b.dataset.annuler, { method: "POST" }).then((r) => r.json());
    if (r.ok) { b.closest(".scan-item").classList.add("annule"); b.remove(); }
    focus();
  });
  let dernierAjout = null;
  async function annulerDernier() {
    if (!dernierAjout) return false;
    const { id, el } = dernierAjout;
    dernierAjout = null;
    const r = await fetch("/api/annuler/" + id, { method: "POST" }).then((r) => r.json()).catch(() => ({}));
    if (r.ok) { el.classList.add("annule"); el.querySelector("[data-annuler]")?.remove(); }
    return !!r.ok;
  }
  $("vider").addEventListener("click", () => { flux.innerHTML = ""; enAttente.clear(); focus(); });

  // Complète les scans dont la description est arrivée
  async function sonder() {
    if (!enAttente.size) return;
    const qs = [...enAttente.keys()].map((i) => "id=" + encodeURIComponent(i)).join("&");
    try {
      const data = await fetch("/api/notices?" + qs).then((r) => r.json());
      for (const [cle, n] of Object.entries(data)) {
        const id = Number(cle);
        if (!n || n.statut === "en_attente") continue;
        for (const el of enAttente.get(id) || []) {
          el.querySelector(".couv").outerHTML = couv(n);
          el.querySelector(".corps").firstElementChild.remove();
          el.querySelector(".corps").firstElementChild.remove();
          el.querySelector(".corps").insertAdjacentHTML("afterbegin", corpsNotice(n, n.reference));
          el.querySelector(".cote-slot").innerHTML = n.cote ? `<span class="cote">${esc(n.cote)}</span>` : "";
          if (n.statut === "introuvable") el.classList.add("doublon");
        }
        enAttente.delete(id);
        document.dispatchEvent(new CustomEvent("scan:notice", { detail: { id, notice: n } }));
      }
    } catch (e) {}
  }
  setInterval(sonder, 1500);

  // --- envoi des scans (dans l'ordre, même en rafale) -----------------------
  // null : à réessayer plus tard (réseau coupé, serveur arrêté, clé refusée). Une panne du serveur sur ce
  // code est affichée comme une erreur : réessayer ne changerait rien, et bloquerait tous les scans suivants.
  async function poster(corps) {
    try {
      const r = await fetch("/api/scan", { method: "POST", headers: { "Content-Type": "application/json" },
                                           body: JSON.stringify(corps) });
      if (r.status >= 500) return { ok: false, statut: "erreur", code: corps.code, message: tr("Le serveur n'a pas pu traiter ce code : il n'est pas enregistré.") };
      return r.ok ? await r.json() : null;
    } catch (e) {
      return null;
    }
  }
  function afficher(res, compterLeScan) {
    if (res.statut === "emplacement") {         // étiquette reconnue par le serveur seulement
      window.posteScan.choisirEmplacement(String(res.lieu_id || ""), String(res.etagere_id || ""), String(res.rangee_id || ""));
      res = { ...res, message: "→ " + res.nom };
    }
    if (compterLeScan) compteurs.scans++;
    const alerteType = !res.ok ? "erreur" : ["doublon", "ailleurs", "attente"].includes(res.statut) ? "alerte" : "ok";
    if (res.statut !== "attente") {
      if (alerteType === "ok") compteurs.ok++; else compteurs.alertes++;
    }
    if (res.statut !== "rebond") { bip(alerteType); eclair(alerteType === "ok" ? "ok" : "err"); }
    $("compteurs-scan").hidden = false;
    $("nb-scans").textContent = compteurs.scans;
    $("nb-ok").textContent = compteurs.ok;
    $("nb-alertes").textContent = compteurs.alertes;
    const el = rendre(res);
    document.dispatchEvent(new CustomEvent("scan:resultat", { detail: { res, type: alerteType, compteurs } }));
    if (mode === "inventaire") majInventaire();
    return el;
  }

  // --- file d'attente hors ligne --------------------------------------------
  // Un scan qui n'atteint pas le serveur est gardé sur l'appareil, puis envoyé dans l'ordre au
  // retour de la connexion. Il survit à la fermeture de la page.
  const REBOND_MS = 4000;                 // comme sur le serveur : deux lectures rapprochées = une seule
  const gardes = new Map();               // quand -> élément du flux
  function lireFile() {
    try { return JSON.parse(memo.get("attente", "[]")) || []; } catch (e) { return []; }
  }
  function ecrireFile(liste) {
    memo.set("attente", liste.length ? JSON.stringify(liste) : null);
    const n = liste.length;
    $("file-scan").hidden = !n;
    $("file-scan").textContent = n > 1 ? tr("{n} scans gardés sur cet appareil : ils partiront au retour de la connexion.", { n })
      : tr("1 scan gardé sur cet appareil : il partira au retour de la connexion.");
    document.dispatchEvent(new CustomEvent("scan:file", { detail: { n } }));
  }
  function garder(corps) {
    const liste = lireFile();
    const dernier = liste[liste.length - 1];
    const quand = Date.now();
    if (dernier && dernier.code === corps.code && dernier.mode === corps.mode && dernier.lieu_id === corps.lieu_id
        && dernier.etagere_id === corps.etagere_id && dernier.rangee_id === corps.rangee_id && quand - dernier.quand < REBOND_MS) return;
    ecrireFile([...liste, { ...corps, quand }]);
    const res = { ok: true, statut: "attente", code: corps.code, quand,
                  message: tr("réseau indisponible : gardé sur cet appareil") };
    gardes.set(quand, afficher(res, true));
    if (mode === "ajout") dernierAjout = null;   // rien à annuler côté serveur pour ce scan
  }
  function retirerDeLaFile(quand) {
    ecrireFile(lireFile().filter((c) => c.quand !== quand));
    gardes.get(quand)?.remove();
    gardes.delete(quand);
  }
  let vidageEnCours = false;
  async function viderFile() {
    if (vidageEnCours || !lireFile().length) return;
    vidageEnCours = true;
    try {
      for (let liste = lireFile(); liste.length; liste = lireFile()) {
        const { quand, ...corps } = liste[0];
        const res = await poster({ ...corps, differe: true });
        if (!res) break;
        ecrireFile(lireFile().filter((c) => c.quand !== quand));
        const ancien = gardes.get(quand);
        gardes.delete(quand);
        const el = afficher(res, !ancien);       // gardé avant un rechargement de la page : pas encore compté
        ancien?.replaceWith(el);
      }
    } finally {
      vidageEnCours = false;
    }
  }
  // Une seule page à la fois vide la file, si plusieurs onglets sont ouverts
  function essayerDeVider() {
    if (!lireFile().length) return;
    if (navigator.locks) navigator.locks.request("biblio-scan-file", { ifAvailable: true }, (v) => (v ? viderFile() : null));
    else viderFile();
  }
  setInterval(essayerDeVider, 5000);
  window.addEventListener("online", essayerDeVider);

  let file = Promise.resolve();
  function envoyer(code) {
    file = file.then(async () => {
      const corps = { mode, code, lieu_id: selLieu.value, etagere_id: selEtagere.value, rangee_id: selRangee.value,
                      inventaire_id: inventaire && inventaire.id };
      if (lireFile().length) {                   // garder l'ordre : après ceux déjà en attente
        garder(corps);
        essayerDeVider();
        return;
      }
      const res = await poster(corps);
      if (res) afficher(res, true); else garder(corps);
    });
  }
  // Point d'entrée commun : douchette, clavier, ou caméra (camera.js)
  function scanner(code) {
    if (!code) return false;
    if (choisirParEtiquette(code)) return true;
    if (mode !== "ou" && !PEUT_SCANNER) { alerte(tr("Votre accès permet seulement de chercher où est rangé un livre.")); return false; }
    if (mode === "inventaire" && !inventaire) { alerte(tr("Commencez d'abord l'inventaire.")); return false; }
    envoyer(code);
    return true;
  }
  // Étiquette d'emplacement : préfixe 29, genre, numéro, clé (voir etiquettes.py). Lue dans la page,
  // elle marche aussi sans réseau. La douchette en QWERTY envoie les chiffres en « &é"'(… ».
  // Un téléphone peut retoucher la frappe (Ç en début de champ, guillemets typographiques). Même table dans isbn.py.
  const AZERTY = { "&": "1", "é": "2", "É": "2", '"': "3", "“": "3", "”": "3", "«": "3", "»": "3",
                   "'": "4", "’": "4", "‘": "4", "(": "5", "§": "6", "-": "6", "è": "7", "È": "7",
                   "!": "8", "_": "8", "ç": "9", "Ç": "9", "à": "0", "À": "0" };
  const enChiffres = (texte) => [...texte].map((c) => AZERTY[c] ?? c).join("");
  function chercherEtiquette(numero, genre) {
    for (const l of LIEUX) {
      if (genre === "1" && l.etiquette === numero) return [l.id];
      for (const e of l.etageres) {
        if (genre === "2" && e.etiquette === numero) return [l.id, e.id];
        for (const r of e.rangees) {
          if (genre === "3" && r.etiquette === numero) return [l.id, e.id, r.id];
        }
      }
    }
    return null;
  }
  function choisirParEtiquette(brut) {
    const code = /\d/.test(brut) ? brut : enChiffres(brut);
    const m = /^29([123])(\d{9})\d$/.exec(code);
    if (!m) return false;
    const place = chercherEtiquette(m[2], m[1]);
    if (!place) { alerte(tr("Cette étiquette ne correspond à aucun emplacement : rechargez la page si elle vient d'être créée.")); return true; }
    window.posteScan.choisirEmplacement(...place.map(String));
    bip("ok"); eclair("ok");
    rendre({ ok: true, statut: "emplacement", code, message: "→ " + nomEmplacement() });
    document.dispatchEvent(new CustomEvent("scan:resultat", { detail: { res: { ok: true, statut: "emplacement", code: nomEmplacement(), message: tr("Scannez maintenant les livres de cet emplacement.") }, type: "ok", compteurs } }));
    return true;
  }
  $("form-scan").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const brut = input.value.trim();
    input.value = "";
    scanner(/\d/.test(brut) ? brut : enChiffres(brut));
    if (tactile && saisie === "main") input.blur();       // referme le clavier du téléphone
  });
  // Entrée explicite : l'envoi implicite du formulaire ne suffit pas sur iPhone.
  // Certaines douchettes terminent par Tab au lieu d'Entrée.
  input.addEventListener("keydown", (ev) => {
    if ((ev.key === "Enter" || ev.key === "Tab") && input.value.trim()) { ev.preventDefault(); $("form-scan").requestSubmit(); }
  });

  // --- douchette -------------------------------------------------------------
  // Écoutée sur toute la page : plus besoin que le champ ait le focus, et rien ne passe par le texte
  // du champ (qu'un téléphone peut retoucher). `ev.code` désigne la touche physique, quelle que soit
  // la disposition du clavier : Digit7 reste 7 là où `ev.key` dit « è ».
  const ATTENTE_MAX_MS = 1000;           // au-delà, le tampon est une lecture incomplète : on l'oublie
  let derniereTouche = 0;
  function chiffreDe(ev) {
    const m = /^(?:Digit|Numpad)(\d)$/.exec(ev.code || "");
    if (m) return m[1];
    return /^\d$/.test(ev.key) ? ev.key : AZERTY[ev.key];
  }
  document.addEventListener("keydown", (ev) => {
    if (saisie !== "douchette" || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (ev.target !== input && ev.target.matches?.("input:not([type=checkbox]), textarea")) return;
    if ((ev.key === "Enter" || ev.key === "Tab") && input.value.trim()) {
      ev.preventDefault();
      $("form-scan").requestSubmit();
      return;
    }
    const chiffre = chiffreDe(ev);
    if (!chiffre) return;
    ev.preventDefault();
    const maintenant = performance.now();
    if (maintenant - derniereTouche > ATTENTE_MAX_MS) input.value = "";
    derniereTouche = maintenant;
    input.value += chiffre;
  }, true);

  // --- mode poche ------------------------------------------------------------
  // iOS ne transmet plus la douchette à la page quand l'écran est verrouillé : l'écran reste allumé,
  // tout noir, et les touchers sont ignorés. Sortie par un appui long.
  let verrouEcran = null;
  async function garderEcranAllume() {
    if (verrouEcran) return true;
    if (!("wakeLock" in navigator)) return false;
    try {
      verrouEcran = await navigator.wakeLock.request("screen");
      verrouEcran.addEventListener("release", () => { verrouEcran = null; });
      return true;
    } catch (e) {
      return false;
    }
  }
  function libererEcran() {
    verrouEcran?.release().catch(() => {});
    verrouEcran = null;
  }
  const poche = $("poche");
  const APPUI_LONG_MS = 2000;
  let appuiLong = null;
  function majPoche(n) {
    $("poche-compteur").textContent = n > 1 ? tr("{n} livres scannés", { n }) : tr("{n} livre scanné", { n });
  }
  async function ouvrirPoche() {
    debloquerSon();
    if (!(await garderEcranAllume())) {
      alerte(tr("L'écran ne peut pas rester allumé (mode économie d'énergie ?) : le mode poche ne s'ouvre pas."));
      return;
    }
    $("poche-alerte").hidden = true;
    majPoche(compteurs.scans);
    poche.hidden = false;
  }
  function fermerPoche() {
    poche.hidden = true;
    libererEcran();
    focus();
  }
  $("poche-ouvrir").addEventListener("click", ouvrirPoche);
  poche.addEventListener("touchstart", (ev) => ev.preventDefault(), { passive: false });
  poche.addEventListener("pointerdown", () => { clearTimeout(appuiLong); appuiLong = setTimeout(fermerPoche, APPUI_LONG_MS); });
  ["pointerup", "pointercancel", "pointerleave"].forEach((t) => poche.addEventListener(t, () => clearTimeout(appuiLong)));
  document.addEventListener("scan:resultat", (ev) => { if (!poche.hidden) majPoche(ev.detail.compteurs.scans); });
  document.addEventListener("visibilitychange", async () => {
    if (document.hidden || poche.hidden) return;
    const message = tr("Écran verrouillé : les livres lus pendant ce temps n'ont pas été enregistrés.");
    $("poche-alerte").textContent = message;
    $("poche-alerte").hidden = false;
    alerte(message);
    if (!(await garderEcranAllume())) fermerPoche();
  });


  function alerte(msg) {
    const res = { ok: false, statut: "erreur", message: msg };
    rendre(res);
    bip("erreur");
    document.dispatchEvent(new CustomEvent("scan:resultat", { detail: { res, type: "erreur", compteurs } }));
  }

  // Sur ordinateur, le champ garde le focus. Sur téléphone, jamais sans toucher : le clavier virtuel s'ouvrirait seul.
  function focus() { if (!tactile && saisie !== "camera") setTimeout(() => input.focus(), 0); }
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest("select, input, a, button, label, textarea")) focus();
  });
  window.addEventListener("focus", focus);

  window.posteScan = {
    scanner, bip, debloquerSon, annulerDernier, couv, esc, LIBELLES, LIEUX, nomEmplacement,
    garderEcranAllume, libererEcran, choisirSaisie, saisieMemorisee,
    get mode() { return mode; },
    get saisie() { return saisie; },
    choisirMode,
    choisirEmplacement(lieu, etagere, rangee) {
      selLieu.value = lieu || ""; remplirEtageres();
      selEtagere.value = etagere || ""; remplirRangees();
      selRangee.value = rangee || ""; sauverEmplacement();
    },
  };
  choisirSaisie(saisie);
  afficherInventaire();
  ecrireFile(lireFile());
  essayerDeVider();
})();
