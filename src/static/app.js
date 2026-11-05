// Dashboard Hikvision Video Monitor — script externe (CSP sans unsafe-inline).
'use strict';

if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' });
    }

const $ = s => document.querySelector(s);
const esc = v => (v === null || v === undefined || v === "") ? '<span class="muted">UNKNOWN</span>'
  : String(v).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmt = iso => iso ? new Date(iso).toLocaleString("fr-FR") : '<span class="muted">—</span>';
const pill = v => {
  const cls = v === "ONLINE" || v === "RECORDING" ? "p-ok" : (v === "OFFLINE" || v === "NOT_RECORDING") ? "p-ko" : "p-unk";
  return `<span class="pill ${cls}">${esc(v || "UNKNOWN")}</span>`;
};
let cams = [], sortKey = "nvr_name", sortDir = 1;

// --- jeton d'acces (DASHBOARD_TOKEN) : lu une fois depuis ?token=... puis memorise ---
const TOKEN_KEY = "hikvision_token";
(function () {
  const u = new URL(location.href), t = u.searchParams.get("token");
  if (t) { localStorage.setItem(TOKEN_KEY, t); u.searchParams.delete("token"); history.replaceState(null, "", u.pathname + (u.search || "")); }
})();
const token = () => localStorage.getItem(TOKEN_KEY) || "";
const withToken = url => token() ? url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token()) : url;

async function j(url, opt) {
  opt = opt || {};
  if (token()) opt.headers = Object.assign({}, opt.headers, { "X-Auth-Token": token() });
  const r = await fetch(url, opt);
  if (!r.ok) {
    let msg = "erreur " + r.status;
    try { const d = await r.json(); if (d && d.error) msg = d.error; } catch (_) {}
    const e = new Error(msg); e.status = r.status; throw e;
  }
  return r.json();
}

// Disques du NVR : nombre, capacite totale, et signalement des disques au statut inhabituel.
function hddCell(n) {
  const h = n.hdd || [];
  if (!h.length) return '<span class="muted">—</span>';
  const to = h.reduce((a, d) => a + (d.volume || 0), 0) / 1048576;
  const odd = h.filter(d => d.status);
  const warn = odd.length
    ? ` <span class="ko" title="${esc(odd.map(d => "disque " + d.id + " : statut " + d.status).join(", "))} — à vérifier sur site">!</span>`
    : "";
  return `${h.length} disque(s) · ${to.toFixed(1)} To${warn}`;
}

function renderSummary(s) {
  const g = s.global, lc = s.last_cycle;
  $("#meta").textContent = lc ? `Dernier cycle : ${new Date(lc.ts).toLocaleString("fr-FR")} (${lc.duration_ms} ms) · polling ${s.poll_interval}s` : "aucun cycle encore";
  $("#cards").innerHTML = [
    ["NVR joignables", `${g.nvr_reachable}/${g.nvr_total}`, g.nvr_reachable === g.nvr_total ? "ok" : "ko"],
    ["Caméras", g.total, ""], ["En ligne", g.online, "ok"], ["Hors ligne", g.offline, g.offline ? "ko" : "ok"],
    ["Inconnu", g.unknown, g.unknown ? "unk" : ""], ["Enregistrent", g.recording, "ok"], ["N'enregistrent pas", g.not_recording, g.not_recording ? "ko" : "ok"],
  ].map(([l, v, c]) => `<div class="card"><div class="v ${c}">${v}</div><div class="l">${l}</div></div>`).join("");

  $("#nvrTable tbody").innerHTML = s.nvrs.map(n => `<tr>
    <td><b>${esc(n.nvr_name)}</b></td><td>${esc(n.ip)}</td><td>${esc(n.model)}</td><td>${esc(n.firmware)}</td>
    <td>${n.reachable ? pill("ONLINE") : '<span class="pill p-ko">INJOIGNABLE</span>'}</td>
    <td>${n.total}</td><td class="ok">${n.online}</td><td class="${n.offline ? "ko" : ""}">${n.offline}</td>
    <td class="${n.unknown ? "unk" : ""}">${n.unknown}</td><td>${n.recording}</td><td>${hddCell(n)}</td><td>${fmt(n.last_ok)}</td></tr>`).join("");

  const al = [];
  if (s.monitor_error) al.push(`Erreur du moniteur : ${esc(s.monitor_error)}`);
  s.nvrs.filter(n => !n.reachable).forEach(n => al.push(`NVR ${esc(n.nvr_name)} (${esc(n.ip)}) injoignable : ${esc(n.last_error)}`));
  $("#alerts").innerHTML = al.length ? `<div class="alert">${al.join("<br>")}</div>` : "";

  const an = [];
  s.duplicate_ips.forEach(d => an.push(`Même caméra (IP ${esc(d.ip)}) enregistrée sur plusieurs NVR : ${esc(d.where_)}`));
  if (g.offline) an.push(`${g.offline} caméra(s) hors ligne — filtrer « OFFLINE » dans le tableau.`);
  $("#anomalies").innerHTML = an.length ? an.map(a => `• ${a}`).join("<br>") : "Aucune anomalie.";

  const sel = $("#fNvr"), cur = sel.value;
  sel.innerHTML = '<option value="">Tous les NVR</option>' + s.nvrs.map(n => `<option>${esc(n.nvr_name)}</option>`).join("");
  sel.value = cur;
}

const CLASSES_MP = [1, 2, 3, 4, 5, 6, 8, 12, 16, 24, 32];

// Classe commerciale la plus proche (2, 4, 8 MP...) d'apres la resolution reelle du flux principal.
function classeMp(c) {
  if (!c.width || !c.height) return "";
  const mp = c.width * c.height / 1e6;
  return CLASSES_MP.reduce((a, b) => Math.abs(b - mp) < Math.abs(a - mp) ? b : a) + " MP";
}

function cellDef(c) {
  const m = classeMp(c);
  if (!m) return '<span class="muted">UNKNOWN</span>';
  return `<b>${m}</b> <span class="muted">${c.width}×${c.height}</span>`;
}

function compteMp() {
  const compte = {};
  cams.filter(c => c.present).forEach(c => { const m = classeMp(c); if (m) compte[m] = (compte[m] || 0) + 1; });
  return compte;
}

// Alimente le selecteur de definition (reconstruit seulement si les classes changent).
function majOptionsMp() {
  const sel = $("#fMp");
  if (!sel) return;
  const compte = compteMp();
  const classes = Object.keys(compte).sort((a, b) => parseFloat(b) - parseFloat(a));
  const signature = classes.map(m => m + ":" + compte[m]).join("|");
  if (sel.dataset.sig === signature) return;
  const garde = sel.value;
  sel.innerHTML = '<option value="">Toutes définitions</option>' +
    classes.map(m => `<option value="${m}">${m} (${compte[m]})</option>`).join("");
  if (classes.includes(garde)) sel.value = garde;
  sel.dataset.sig = signature;
}

// Alimente le selecteur de focale (uniquement les valeurs reellement saisies).
function majOptionsLens() {
  const sel = $("#fLens");
  if (!sel) return;
  const compte = {};
  cams.filter(c => c.present && c.lens).forEach(c => { compte[c.lens] = (compte[c.lens] || 0) + 1; });
  const valeurs = Object.keys(compte).sort((a, b) => parseFloat(a) - parseFloat(b));
  const signature = valeurs.map(m => m + ":" + compte[m]).join("|");
  if (sel.dataset.sig === signature) return;
  const garde = sel.value;
  sel.innerHTML = '<option value="">Toutes focales</option>' +
    valeurs.map(m => `<option value="${m}">${m} (${compte[m]})</option>`).join("");
  if (valeurs.includes(garde)) sel.value = garde;
  sel.dataset.sig = signature;
}

function renderRepartitionMp() {
  const compte = compteMp();
  const entrees = Object.entries(compte).sort((a, b) => parseFloat(b[0]) - parseFloat(a[0]));
  const el = $("#mpRepart");
  if (!el) return;
  el.innerHTML = entrees.length
    ? "Définitions : " + entrees.map(([m, n]) =>
        `<a href="#" class="mplink" data-mp="${m}" title="Filtrer sur ${m} seulement">${m} × ${n}</a>`).join("  ·  ")
    : "Définitions inconnues";
}

function renderCams() {
  majOptionsMp();
  majOptionsLens();
  const fn = $("#fNvr").value, fs = $("#fStatus").value, fr = $("#fRec").value,
        fm = $("#fMp").value, fl = $("#fLens").value, ft = $("#fText").value.trim().toLowerCase();
  let rows = cams.filter(c => c.present &&
    (!fn || c.nvr_name === fn) && (!fs || c.status === fs) && (!fr || c.recording === fr) &&
    (!fm || classeMp(c) === fm) && (!fl || (c.lens || "") === fl) &&
    (!ft || [c.name, c.ip, c.model, c.nvr_name, "ch" + c.channel, classeMp(c), c.lens]
      .join(" ").toLowerCase().includes(ft)));
  rows.sort((a, b) => {
    let x = a[sortKey], y = b[sortKey];
    if (sortKey === "nvr_name") { x = a.nvr_ip + String(a.channel).padStart(3, "0"); y = b.nvr_ip + String(b.channel).padStart(3, "0"); }
    if (sortKey === "mp") { x = (a.width || 0) * (a.height || 0); y = (b.width || 0) * (b.height || 0); }
    if (sortKey === "lens") { x = parseFloat(a.lens) || 0; y = parseFloat(b.lens) || 0; }
    if (typeof x === "number" && typeof y === "number") return (x - y) * sortDir;
    return String(x ?? "").localeCompare(String(y ?? ""), "fr", {numeric: true}) * sortDir;
  });
  $("#camCount").textContent = `(${rows.length} affichée(s) sur ${cams.filter(c => c.present).length})`;
  renderRepartitionMp();
  $("#camTable tbody").innerHTML = rows.map(c => `<tr>
    <td><button class="snapbtn" data-nvr="${esc(c.nvr_id)}" data-ch="${c.channel}" data-name="${esc(c.name)}" title="Voir une image de cette camera">&#128247;</button></td>
    <td>${esc(c.nvr_name)}</td><td>CH${c.channel}</td><td><b class="cname" data-nvr="${esc(c.nvr_id)}" data-ch="${c.channel}" title="Cliquer pour renommer (appliqué au NVR)">${esc(c.name)}</b></td><td>${esc(c.ip)}</td>
    <td>${esc(c.model)}</td><td>${cellDef(c)}</td>
    <td><b class="lens" data-nvr="${esc(c.nvr_id)}" data-ch="${c.channel}" title="Cliquer pour saisir la focale (ex. 4mm)">${c.lens ? esc(c.lens) : '<span class="muted">—</span>'}</b></td>
    <td>${pill(c.status)}</td><td>${pill(c.recording)}</td>
    <td>${fmt(c.last_seen)}</td><td class="muted">${esc(c.detect)}</td></tr>`).join("");
}

function renderEvents(reponse) {
  const ev = (reponse && reponse.events) ? reponse.events : (reponse || []);
  if (reponse && typeof reponse.total === "number") {
    const c = $("#evCount");
    if (c) c.textContent = (ev.length === reponse.total
      ? reponse.total + " changement(s)"
      : ev.length + " affichés sur " + reponse.total) + " · " + reponse.days + " j";
  }
  const label = {STATUS:"Statut", RECORDING:"Enregistrement", CAMERA_ADDED:"Caméra ajoutée", CAMERA_REMOVED_FROM_NVR:"Retirée du NVR",
    CAMERA_RETURNED:"Caméra revenue", IP_CHANGED:"IP changée", NVR_UNREACHABLE:"NVR injoignable", NVR_ONLINE:"NVR rétabli"};
  $("#evTable tbody").innerHTML = ev.length ? ev.map(e => `<tr>
    <td>${fmt(e.ts)}</td><td>${esc(e.nvr_name)}</td><td>${e.channel ? "CH" + e.channel : ""}</td><td>${e.camera_name ? esc(e.camera_name) : ""}</td>
    <td>${label[e.type] || esc(e.type)}</td><td>${e.old_value || e.new_value ? `${esc(e.old_value)} → ${esc(e.new_value)}` : ""}</td></tr>`).join("")
    : '<tr><td colspan="6" class="muted">Aucun changement depuis le premier inventaire.</td></tr>';
}

$("#evDays").onchange = () => {
  $("#evCount").textContent = "chargement…";
  chargerEvenements().catch(err => { $("#evCount").textContent = "Erreur : " + err.message; });
};

function demanderJeton() {
  // Un jeton est requis et absent pour CETTE origine (le jeton est memorise par origine) :
  // le demander une fois, le stocker, recharger. Evite un dashboard vide inexplicable.
  if ($("#jetonForm")) return;
  const d = document.createElement("div");
  d.className = "alert";
  d.id = "jetonForm";
  d.innerHTML = '<b>Jeton d\'accès requis.</b> Collez la valeur de <code>DASHBOARD_TOKEN</code> '
    + '(fichier <code>config/.env</code>) : <input type="password" id="jetonInput" placeholder="jeton" class="min220"> '
    + '<button id="jetonOk">Valider</button>';
  $("#alerts").appendChild(d);
  $("#jetonInput").focus();
  const valider = () => {
    const v = $("#jetonInput").value.trim();
    if (v) { localStorage.setItem(TOKEN_KEY, v); location.reload(); }
  };
  $("#jetonOk").onclick = valider;
  $("#jetonInput").onkeydown = ev => { if (ev.key === "Enter") valider(); };
}

async function chargerEvenements() {
  const jours = parseInt($("#evDays").value, 10) || 30;
  const res = await j("/api/events?days=" + jours + "&limit=1000");
  renderEvents(res);
  const lien = $("#evCsv");
  if (lien) lien.href = withToken("/api/events.csv?days=" + jours);
}

async function load() {
  try {
    const [s, c] = await Promise.all([j("/api/summary"), j("/api/cameras")]);
    cams = c; renderSummary(s); renderCams(); await chargerEvenements();
  } catch (err) {
    if (err.status === 401) {
      $("#meta").textContent = "jeton d'accès requis pour cette adresse";
      demanderJeton();
    } else {
      $("#meta").textContent = "Serveur injoignable : " + err.message;
    }
  }
}

$("#mpRepart").addEventListener("click", ev => {
  const a = ev.target.closest(".mplink");
  if (!a) return;
  ev.preventDefault();
  const sel = $("#fMp");
  sel.value = (sel.value === a.dataset.mp) ? "" : a.dataset.mp;
  renderCams();
});

document.querySelectorAll("#camTable th").forEach(th => th.onclick = () => {
  const k = th.dataset.k; sortDir = (sortKey === k) ? -sortDir : 1; sortKey = k; renderCams();
});
["#fNvr", "#fStatus", "#fRec", "#fMp", "#fLens"].forEach(s => $(s).onchange = renderCams);
$("#fText").oninput = renderCams;
let captureUrl = null;

// L'image est chargee par fetch (et non par <img src>) pour pouvoir lire la reponse
// du serveur et afficher la cause exacte : service arrete, NVR muet, camera hors ligne.
async function ouvrirCapture(nvrId, ch, nom) {
  const m = $("#snapModal");
  m.dataset.nvr = nvrId; m.dataset.ch = ch; m.dataset.name = nom;
  m.style.display = "flex";
  $("#snapTitle").textContent = "Capture — " + nom + " (CH" + ch + ")";
  const msg = $("#snapMsg"), img = $("#snapImg");
  msg.style.color = "";
  msg.textContent = "chargement…";
  img.removeAttribute("src");
  if (captureUrl) { URL.revokeObjectURL(captureUrl); captureUrl = null; }
  try {
    const entetes = token() ? { "X-Auth-Token": token() } : {};
    const res = await fetch("/api/snapshot?nvr_id=" + encodeURIComponent(nvrId)
                            + "&channel=" + ch + "&t=" + Date.now(), { headers: entetes });
    if (!res.ok) {
      let detail = "erreur " + res.status;
      try { const d = await res.json(); if (d && d.error) detail = d.error; } catch (_) {}
      throw new Error(detail);
    }
    captureUrl = URL.createObjectURL(await res.blob());
    img.src = captureUrl;
    msg.textContent = "";
  } catch (e) {
    msg.textContent = (e instanceof TypeError)
      ? "Serveur injoignable : le service Hikvision Monitor n'est pas démarré."
      : "Capture refusée : " + e.message;
    msg.style.color = "var(--ko)";
  }
}

let toastTimer = null;
async function chargerJetons() {
  const d = await j("/api/tokens");
  const tb = $("#tokTable tbody");
  tb.innerHTML = "";
  (d.tokens || []).forEach(k => {
    const actif = !k.revoked_at;
    const tr = document.createElement("tr");
    tr.innerHTML = "<td>" + esc(k.label) + "</td><td>" + esc(k.created_at) + "</td><td>"
      + esc(k.last_used_at || "jamais") + "</td><td>" + (actif
        ? '<span class="ok">actif</span>'
        : '<span class="ko">révoqué ' + esc(k.revoked_at) + "</span>") + "</td><td>"
      + (actif ? '<button class="btn sec" data-id="' + k.id + '">Révoquer</button>' : "") + "</td>";
    tb.appendChild(tr);
  });
  tb.querySelectorAll("button[data-id]").forEach(b => b.onclick = async () => {
    if (!confirm("Révoquer ce jeton ? L'appareil qui l'utilise perdra l'accès immédiatement.")) return;
    await j("/api/tokens/" + b.dataset.id, { method: "DELETE" });
    toast("Jeton révoqué");
    chargerJetons();
  });
}

async function ouvrirJetons() {
  $("#tokModal").style.display = "flex";
  $("#tokNew").style.display = "none";
  $("#tokLabel").value = "";
  try { await chargerJetons(); } catch (e) { toast(e.message, true); }
}

function toast(texte, erreur) {
  let d = $("#toast");
  if (!d) { d = document.createElement("div"); d.id = "toast"; document.body.appendChild(d); }
  d.textContent = texte;
  d.className = erreur ? "show err" : "show";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { d.className = ""; }, 4500);
}

function editerNom(cell) {
  const ancien = cell.textContent.trim();
  const nvr = cell.dataset.nvr, ch = cell.dataset.ch;
  cell.dataset.editing = "1";
  cell.textContent = "";
  const inp = document.createElement("input");
  inp.type = "text";
  inp.className = "cnameEdit";
  inp.maxLength = 32;
  inp.value = (ancien === "UNKNOWN") ? "" : ancien;
  cell.appendChild(inp);
  inp.focus();
  inp.select();
  let fini = false;

  const annuler = () => {
    if (fini) return;
    fini = true;
    cell.textContent = ancien;
    delete cell.dataset.editing;
  };
  const valider = async () => {
    if (fini) return;
    const nom = inp.value.trim();
    if (!nom || nom === ancien) return annuler();
    fini = true;
    cell.textContent = "…";
    try {
      const r = await j("/api/camera/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nvr_id: nvr, channel: Number(ch), name: nom })
      });
      cell.textContent = r.name;
      toast("Nom appliqué au NVR : " + r.name);
    } catch (e) {
      cell.textContent = ancien;
      toast("Renommage refusé : " + e.message, true);
    }
    delete cell.dataset.editing;
  };

  inp.onkeydown = ev => {
    if (ev.key === "Enter") { ev.preventDefault(); valider(); }
    else if (ev.key === "Escape") { ev.preventDefault(); annuler(); }
  };
  inp.onblur = annuler;
}

function editerFocale(cell) {
  const ancien = cell.textContent.trim();
  const nvr = cell.dataset.nvr, ch = cell.dataset.ch;
  cell.dataset.editing = "1";
  cell.textContent = "";
  const inp = document.createElement("input");
  inp.type = "text";
  inp.className = "cnameEdit";
  inp.maxLength = 12;
  inp.placeholder = "4mm";
  inp.value = (ancien === "—" || ancien === "UNKNOWN") ? "" : ancien;
  cell.appendChild(inp);
  inp.focus();
  inp.select();
  let fini = false;

  const annuler = () => { if (fini) return; fini = true; cell.textContent = ancien; delete cell.dataset.editing; };
  const valider = async () => {
    if (fini) return;
    const valeur = inp.value.trim();
    if (valeur === ((ancien === "—") ? "" : ancien)) return annuler();
    fini = true;
    cell.textContent = "…";
    try {
      const r = await j("/api/camera/lens", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nvr_id: nvr, channel: Number(ch), lens: valeur })
      });
      const cam = cams.find(c => c.nvr_id === nvr && String(c.channel) === String(ch));
      if (cam) cam.lens = r.lens || null;
      cell.innerHTML = r.lens ? esc(r.lens) : '<span class="muted">—</span>';
      delete cell.dataset.editing;
      renderCams();
    } catch (e) {
      cell.textContent = ancien;
      delete cell.dataset.editing;
      toast("Focale refusée : " + e.message, true);
    }
  };

  inp.onkeydown = ev => {
    if (ev.key === "Enter") { ev.preventDefault(); valider(); }
    else if (ev.key === "Escape") { ev.preventDefault(); annuler(); }
  };
  inp.onblur = annuler;
}

$("#camTable tbody").addEventListener("click", ev => {
  const b = ev.target.closest(".snapbtn");
  if (b) { ouvrirCapture(b.dataset.nvr, b.dataset.ch, b.dataset.name); return; }
  const n = ev.target.closest(".cname");
  if (n && !n.dataset.editing) { editerNom(n); return; }
  const l = ev.target.closest(".lens");
  if (l && !l.dataset.editing) editerFocale(l);
});
$("#snapClose").onclick = () => { $("#snapModal").style.display = "none"; };
$("#snapReload").onclick = () => {
  const m = $("#snapModal");
  ouvrirCapture(m.dataset.nvr, m.dataset.ch, m.dataset.name);
};
$("#snapSave").onclick = async () => {
  const m = $("#snapModal");
  $("#snapMsg").style.color = "";
  $("#snapMsg").textContent = "enregistrement…";
  try {
    const r = await j("/api/snapshot?nvr_id=" + encodeURIComponent(m.dataset.nvr)
                      + "&channel=" + m.dataset.ch + "&save=1");
    $("#snapMsg").textContent = "Enregistre : " + r.name;
    $("#snapMsg").style.color = "var(--ok)";
  } catch (e) {
    $("#snapMsg").textContent = "Echec de l'enregistrement : " + e.message;
    $("#snapMsg").style.color = "var(--ko)";
  }
};
$("#snapModal").onclick = ev => { if (ev.target.id === "snapModal") $("#snapModal").style.display = "none"; };
document.addEventListener("keydown", ev => { if (ev.key === "Escape") $("#snapModal").style.display = "none"; });

$("#report").onclick = async () => {
  const b = $("#report"), msg = $("#reportMsg"), link = $("#reportLink");
  b.disabled = true; b.textContent = "Génération…"; msg.textContent = ""; msg.style.color = "";
  try {
    const r = await j("/api/export", { method: "POST" });
    link.href = withToken(r.url); link.textContent = "Télécharger " + r.file; link.style.display = "";
    msg.textContent = "Rapport généré.";
    b.textContent = "Régénérer le rapport";
  } catch (err) {
    msg.textContent = "Échec de la génération : " + err.message;
    msg.style.color = "var(--ko)";
    b.textContent = "Générer le rapport Excel";
  } finally { b.disabled = false; }
};
// seul le jeton maitre (super admin) voit la gestion des jetons
j("/api/me").then(d => {
  if (!d.admin) { $("#tokBtn").style.display = "none"; }
}).catch(() => {});

$("#tokBtn").onclick = ouvrirJetons;
$("#tokClose").onclick = () => { $("#tokModal").style.display = "none"; };
$("#tokCreate").onclick = async () => {
  const label = $("#tokLabel").value.trim();
  try {
    const d = await j("/api/tokens", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: label }) });
    $("#tokValue").textContent = d.token;
    $("#tokNew").style.display = "block";
    $("#tokLabel").value = "";
    chargerJetons();
  } catch (e) { toast(e.message, true); }
};
$("#tokCopy").onclick = () => {
  navigator.clipboard.writeText($("#tokValue").textContent)
    .then(() => toast("Jeton copié"))
    .catch(() => toast("Copie impossible : sélectionnez le texte", true));
};
$("#refresh").onclick = async () => {
  const b = $("#refresh");
  b.disabled = true; b.textContent = "Collecte…";
  let before = null;
  try { const s = await j("/api/summary"); before = s.last_cycle ? s.last_cycle.ts : null; } catch (e) {}
  try { await j("/api/refresh", { method: "POST" }); } catch (e) {}
  const t0 = Date.now();   // attendre le cycle REEL : un cycle peut durer ~20 s si un NVR est lent
  while (Date.now() - t0 < 90000) {
    await new Promise(r => setTimeout(r, 1500));
    try {
      const s = await j("/api/summary");
      const now = s.last_cycle ? s.last_cycle.ts : null;
      if (now && now !== before) break;
    } catch (e) {}
  }
  await load();
  b.disabled = false; b.textContent = "Actualiser maintenant";
};
$("#csvLink").href = withToken("/api/cameras.csv");
load();
setInterval(load, 30000);
