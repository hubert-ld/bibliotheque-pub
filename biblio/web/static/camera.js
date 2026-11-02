// Mode caméra du poste de scan : le téléphone (ou la webcam) lit les codes-barres.
// Chaque code reconnu passe par le même chemin qu'un scan de douchette (posteScan.scanner).
// Sur téléphone, la caméra s'ouvre en plein écran : l'image, l'emplacement en en-tête,
// et en bas le dernier livre scanné.
(function () {
  const $ = (id) => document.getElementById(id);
  const zone = $("camera"), video = $("camera-video"), etat = $("camera-etat");
  const btnOuvrir = $("camera-ouvrir"), btnLampe = $("camera-lampe"), btnChanger = $("camera-changer");
  const viseur = zone.querySelector(".viseur");
  const poste = window.posteScan;
  const tactile = matchMedia("(pointer: coarse)").matches;
  const demandee = new URLSearchParams(location.search).has("camera");
  const VENDOR = "/static/vendor/";
  const PONYFILL = VENDOR + "barcode-detector-3.2.2.ponyfill.js";
  const WASM = VENDOR + "zxing_reader-3.1.3.wasm";

  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    if (demandee) {
      zone.hidden = false;
      zone.querySelector(".cam-haut").hidden = true;
      etat.textContent = tr("La caméra n'est utilisable que sur une connexion sécurisée (https). Lancez la bibliothèque avec « serve --phone » et scannez le QR code de la page Téléphone.");
    }
    return;
  }
  btnOuvrir.hidden = false;

  let detecteur = null, flux = null, piste = null, actif = false, lampe = false;
  let cameras = [], cameraChoisie = null, repriseAuRetour = false, verrouEcran = null;
  let dernierLu = "", lecturesIdentiques = 0, nbLivres = 0, noticeAffichee = null;
  const vus = new Map();                       // code -> dernière fois qu'il était dans le viseur
  const toile = document.createElement("canvas");
  const ctx = toile.getContext("2d", { willReadFrequently: true });

  // --- validation : ISBN-13 (978/979) avec clé EAN correcte -------------------
  function isbnValide(code) {
    if (!/^97[89]\d{10}$/.test(code)) return false;
    let somme = 0;
    for (let i = 0; i < 12; i++) somme += +code[i] * (i % 2 ? 3 : 1);
    return (10 - (somme % 10)) % 10 === +code[12];
  }

  // --- décodeur : natif (Chrome Android) sinon zxing-wasm embarqué (iPhone) ----
  function chargerScript(src) {
    return new Promise((ok, ko) => {
      const s = document.createElement("script");
      s.src = src; s.onload = ok; s.onerror = () => ko(new Error("chargement de " + src));
      document.head.appendChild(s);
    });
  }
  async function creerDetecteur() {
    const formats = ["ean_13"];
    if ("BarcodeDetector" in window) {
      try {
        if ((await BarcodeDetector.getSupportedFormats()).includes("ean_13")) return new BarcodeDetector({ formats });
      } catch (e) { /* on passe au décodeur embarqué */ }
    }
    await chargerScript(PONYFILL);
    const api = window.BarcodeDetectionAPI;
    await api.prepareZXingModule({
      overrides: { locateFile: (chemin, prefixe) => (chemin.endsWith(".wasm") ? WASM : prefixe + chemin) },
      fireImmediately: true,
    });
    return new api.BarcodeDetector({ formats });
  }

  // --- caméra ---------------------------------------------------------------
  function messageErreur(e) {
    switch (e && e.name) {
      case "NotAllowedError": return tr("Accès à la caméra refusé. Autorisez-le dans les réglages du navigateur, puis rechargez la page.");
      case "NotFoundError": return tr("Aucune caméra trouvée.");
      case "NotReadableError": return tr("La caméra est utilisée par une autre application.");
      default: return tr("Impossible de démarrer la caméra : {erreur}", { erreur: e && e.message || e });
    }
  }

  async function ouvrir() {
    zone.hidden = false;
    btnOuvrir.hidden = true;
    etat.hidden = false;
    etat.textContent = tr("Démarrage de la caméra…");
    majEntete();
    try {
      const [d] = await Promise.all([detecteur || creerDetecteur(), demarrerFlux()]);
      detecteur = d;
    } catch (e) {
      etat.textContent = messageErreur(e);
      return;
    }
    actif = true;
    etat.textContent = tr("Visez le code-barres au dos du livre");
    memo(true);
    boucle();
  }

  async function demarrerFlux() {
    arreterFlux();
    const video_ = { width: { ideal: 1920 }, height: { ideal: 1080 } };
    if (cameraChoisie) video_.deviceId = { exact: cameraChoisie };
    else video_.facingMode = { ideal: "environment" };
    flux = await navigator.mediaDevices.getUserMedia({ audio: false, video: video_ });
    video.srcObject = flux;
    await video.play();
    piste = flux.getVideoTracks()[0];
    const caps = piste.getCapabilities ? piste.getCapabilities() : {};
    if (caps.focusMode && caps.focusMode.includes("continuous")) {
      piste.applyConstraints({ advanced: [{ focusMode: "continuous" }] }).catch(() => {});
    }
    btnLampe.hidden = !caps.torch;
    lampe = false;
    btnLampe.classList.remove("allume");
    cameras = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
    btnChanger.hidden = cameras.length < 2;
  }

  function arreterFlux() {
    if (flux) flux.getTracks().forEach((t) => t.stop());
    flux = piste = null;
  }

  function fermer() {
    actif = false;
    arreterFlux();
    quitterPleinEcran();
    zone.hidden = true;
    btnOuvrir.hidden = false;
    memo(false);
  }

  function memo(ouverte) {
    try { localStorage.setItem("scan.camera", ouverte ? "1" : "0"); } catch (e) {}
  }

  // --- plein écran ------------------------------------------------------------
  // iPhone ne permet pas le vrai plein écran d'une page : la caméra recouvre alors toute
  // la fenêtre (et tout l'écran une fois la page ajoutée à l'écran d'accueil).
  function pleinEcran(avecGeste) {
    zone.classList.add("immersif");
    document.body.classList.add("immersif");
    if (avecGeste) demarrerSession(); else $("cam-depart").hidden = false;
  }

  function quitterPleinEcran() {
    zone.classList.remove("immersif");
    document.body.classList.remove("immersif");
    $("cam-depart").hidden = true;
    $("cam-reglages").hidden = true;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    if (verrouEcran) { verrouEcran.release().catch(() => {}); verrouEcran = null; }
  }

  // Doit être appelé pendant un toucher : son, vrai plein écran (Android), écran allumé
  function demarrerSession() {
    $("cam-depart").hidden = true;
    poste.debloquerSon();
    const racine = document.documentElement;
    if (racine.requestFullscreen && !document.fullscreenElement) racine.requestFullscreen().catch(() => {});
    garderEcranAllume();
  }

  async function garderEcranAllume() {
    if (!("wakeLock" in navigator) || verrouEcran) return;
    try {
      verrouEcran = await navigator.wakeLock.request("screen");
      verrouEcran.addEventListener("release", () => { verrouEcran = null; });
    } catch (e) {}
  }

  // --- en-tête : mode et emplacement -------------------------------------------
  const NOMS_MODES = { ajout: tr("Ajouter"), deplacement: tr("Déplacer"), ou: tr("Où est-il ?"), inventaire: tr("Inventaire") };

  function majEntete() {
    $("cam-mode").textContent = NOMS_MODES[poste.mode] || poste.mode;
    $("cam-place").textContent = poste.nomEmplacement();
  }

  function ouvrirReglages() {
    const choixPlace = $("cam-choix-place");
    choixPlace.innerHTML = '<option value=":">' + tr("Non localisé") + "</option>";
    for (const l of poste.LIEUX) {
      choixPlace.add(new Option(l.nom, l.id + ":"));
      for (const e of l.etageres) choixPlace.add(new Option("   " + l.nom + " › " + e.nom, l.id + ":" + e.id));
    }
    choixPlace.value = ($("lieu").value || "") + ":" + ($("lieu").value ? $("etagere").value : "");
    $("cam-choix-mode").value = poste.mode;
    $("cam-son").checked = $("son").checked;
    $("cam-reglages").hidden = false;
  }

  function appliquerReglages() {
    const [lieu, etagere] = $("cam-choix-place").value.split(":");
    poste.choisirEmplacement(lieu, etagere);
    poste.choisirMode($("cam-choix-mode").value);
    if ($("son").checked !== $("cam-son").checked) {
      $("son").checked = $("cam-son").checked;
      $("son").dispatchEvent(new Event("change"));
    }
    $("cam-reglages").hidden = true;
    majEntete();
  }

  // --- dernier livre scanné (bas de l'écran) -----------------------------------
  function afficherResultat(res, type) {
    const P = poste, n = res.notice;
    const carte = $("cam-carte");
    carte.className = "cam-carte " + (type === "ok" ? "ok" : type === "alerte" ? "alerte" : "erreur");
    noticeAffichee = res.notice_id || null;
    let titre;
    if (n && n.statut === "en_attente") titre = '<span class="chargement"></span>';
    else if (n && n.titre) titre = P.esc(n.titre);
    else titre = P.esc(res.code || tr("Code non reconnu"));
    const auteurs = n && n.auteurs ? P.esc(n.auteurs.slice(0, 2).join(", ")) : "";
    const message = res.statut === "ajoute" ? (res.emplacement ? "→ " + res.emplacement : "") : res.message;
    carte.innerHTML = `${n ? P.couv(n) : ""}<div class="cam-texte">
        <div class="cam-titre">${titre}</div><div class="cam-auteurs">${auteurs}</div>
        <div><span class="badge ${P.esc(res.statut)}">${P.LIBELLES[res.statut] || res.statut}</span>
          <span class="cam-message">${P.esc(message || "")}</span></div></div>
      ${n && n.cote ? `<span class="cote">${P.esc(n.cote)}</span>` : ""}`;
    $("cam-annuler").hidden = !(res.exemplaire_id && ["ajoute", "doublon"].includes(res.statut));
  }

  document.addEventListener("scan:resultat", (ev) => {
    const { res, type, compteurs } = ev.detail;
    if (res.statut === "rebond") return;
    afficherResultat(res, type);
    nbLivres = compteurs.scans;
    $("cam-compteur").textContent = (nbLivres > 1 ? tr("{n} livres scannés", { n: nbLivres }) : tr("{n} livre scanné", { n: nbLivres }))
      + (compteurs.alertes ? " · " + (compteurs.alertes > 1 ? tr("{n} alertes", { n: compteurs.alertes }) : tr("{n} alerte", { n: compteurs.alertes })) : "");
  });
  document.addEventListener("scan:notice", (ev) => {
    const { id, notice } = ev.detail;
    if (id !== noticeAffichee) return;
    const carte = $("cam-carte");
    carte.querySelector(".couv")?.replaceWith(document.createRange().createContextualFragment(poste.couv(notice)));
    carte.querySelector(".cam-titre").innerHTML = poste.esc(notice.titre || (notice.statut === "introuvable" ? tr("Introuvable : à compléter") : notice.reference));
    carte.querySelector(".cam-auteurs").textContent = (notice.auteurs || []).slice(0, 2).join(", ");
    if (notice.cote && !carte.querySelector(".cote")) carte.insertAdjacentHTML("beforeend", `<span class="cote">${poste.esc(notice.cote)}</span>`);
  });

  document.addEventListener("scan:file", (ev) => {
    const { n } = ev.detail;
    $("cam-attente").hidden = !n;
    $("cam-attente").textContent = n > 1 ? tr("{n} gardés", { n }) : tr("1 gardé");
  });

  // --- lecture en continu -------------------------------------------------------
  // On n'analyse que la bande centrale de l'image, à pleine résolution.
  async function boucle() {
    if (!actif) return;
    if (video.readyState >= 2 && !document.hidden && video.videoWidth) {
      const lv = video.videoWidth, hv = video.videoHeight;
      const l = Math.round(lv * 0.9), h = Math.round(hv * 0.5);
      if (toile.width !== l || toile.height !== h) { toile.width = l; toile.height = h; }
      ctx.drawImage(video, (lv - l) / 2, (hv - h) / 2, l, h, 0, 0, l, h);
      try {
        const codes = await detecteur.detect(toile);
        traiter(codes.map((c) => (c.rawValue || "").replace(/\D/g, "")));
      } catch (e) { /* image illisible : on continue */ }
    }
    setTimeout(boucle, 110);
  }

  function traiter(codes) {
    const maintenant = Date.now();
    const code = codes.find(isbnValide);
    if (!code) return;
    // Deux lectures identiques de suite : écarte les fausses lectures
    lecturesIdentiques = code === dernierLu ? lecturesIdentiques + 1 : 1;
    dernierLu = code;
    if (lecturesIdentiques < 2) return;
    // Tant que le livre reste sous la caméra (vu il y a moins de 3 s), on ne le recompte pas
    const vu = vus.get(code);
    vus.set(code, maintenant);
    if (vu && maintenant - vu < 3000) return;
    if (poste.scanner(code)) {
      if (navigator.vibrate) navigator.vibrate(70);
      viseur.classList.remove("lu");
      void viseur.offsetWidth;
      viseur.classList.add("lu");
      etat.textContent = tr("Lu : {code}", { code });
    }
  }

  // --- boutons et cycle de vie ------------------------------------------------
  btnOuvrir.addEventListener("click", () => {
    poste.debloquerSon();
    ouvrir();
    if (tactile) pleinEcran(true);
  });
  $("camera-fermer").addEventListener("click", fermer);
  $("camera-plein").addEventListener("click", () => {
    if (zone.classList.contains("immersif")) quitterPleinEcran(); else pleinEcran(true);
  });
  $("cam-depart").addEventListener("click", demarrerSession);
  $("cam-lieu").addEventListener("click", ouvrirReglages);
  $("cam-reglages-ok").addEventListener("click", appliquerReglages);
  $("cam-annuler").addEventListener("click", async () => {
    if (await poste.annulerDernier()) {
      $("cam-carte").classList.add("annule");
      $("cam-annuler").hidden = true;
      etat.textContent = tr("Dernier ajout annulé");
    }
  });
  $("lieu").addEventListener("change", majEntete);
  $("etagere").addEventListener("change", majEntete);
  document.querySelectorAll(".modes button").forEach((b) => b.addEventListener("click", majEntete));
  btnLampe.addEventListener("click", () => {
    if (!piste) return;
    lampe = !lampe;
    piste.applyConstraints({ advanced: [{ torch: lampe }] }).catch(() => {});
    btnLampe.classList.toggle("allume", lampe);
  });
  btnChanger.addEventListener("click", async () => {
    const actuel = piste && piste.getSettings().deviceId;
    const i = cameras.findIndex((c) => c.deviceId === actuel);
    cameraChoisie = cameras[(i + 1) % cameras.length].deviceId;
    try { await demarrerFlux(); } catch (e) { etat.textContent = messageErreur(e); }
  });
  // Le téléphone coupe la caméra en arrière-plan : on la relance au retour
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && actif) { repriseAuRetour = true; actif = false; arreterFlux(); }
    else if (!document.hidden && repriseAuRetour) {
      repriseAuRetour = false;
      ouvrir();
      if (zone.classList.contains("immersif")) garderEcranAllume();
    }
  });

  // Rouverte d'office sur téléphone si elle l'était (pas sur l'ordinateur et sa webcam)
  let rouvrir = demandee;
  try { rouvrir = rouvrir || (tactile && localStorage.getItem("scan.camera") === "1"); } catch (e) {}
  if (rouvrir) {
    ouvrir();
    if (tactile) pleinEcran(false);       // sans toucher : « Touchez l'écran pour commencer »
  }
})();
