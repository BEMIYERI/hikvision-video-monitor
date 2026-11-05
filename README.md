# HIKVISION VIDEO MONITOR

Agent Hermes de supervision des 5 NVR Hikvision. Profil Hermes dédié : `hikvision-monitor`.

Spécification de référence : [`docs/AGENT_SPEC.md`](docs/AGENT_SPEC.md) (v2.0, convertie depuis le .docx d'origine).

## Jetons d'accès

Deux niveaux :

| Jeton | Où | Usage |
|---|---|---|
| **maître** | `DASHBOARD_TOKEN` dans `config/.env` | dépannage / administration ; ne peut pas être révoqué depuis l'interface |
| **individuel** | table `tokens` de la base | un par personne ou par appareil, créé et révoqué depuis le bouton « Jetons d'accès » |

Un jeton individuel est affiché **une seule fois** à la création (seul son SHA-256 est stocké).
La révocation coupe l'accès immédiatement, sans toucher aux autres jetons.
Si ni jeton maître ni jeton individuel n'existe, l'accès reste libre (poste local uniquement).

## Rôle super administrateur

Le **jeton maître** (`DASHBOARD_TOKEN`) est le seul à porter le rôle `admin` :

| Action | jeton maître (admin) | jeton individuel (utilisateur) |
|---|---|---|
| lire le dashboard, les caméras, les exports | oui | oui |
| lister / créer / révoquer des jetons | **oui** | non (403) |
| voir le bouton « Jetons d'accès » | oui | non (masqué) |

Générer ou renouveler le jeton maître :

```bat
generer-jeton-admin.bat
```

(ou `python jeton_admin.py`) : remplace la ligne `DASHBOARD_TOKEN=` dans `config/.env`,
affiche le jeton une fois et l'URL prête à ouvrir. Redémarrer le service ensuite.
`GET /api/me` renvoie le rôle de la session (`{"role":"admin"|"user"}`).

## Landing page et téléchargements

- `GET /landing.html` sert `marketing/landing.html` (copiée à côté de l'exécutable au déploiement).
- `GET /HikvisionMonitor.exe` et `GET /app.apk` servent les deux installateurs, sans jeton,
  pour que les liens de la landing page fonctionnent depuis un téléphone du réseau local.
- Captures d'écran du dashboard : `marketing/dashboard-0*.png` (embarquées en base64 dans la landing page).

## Captures de la landing page

Les captures du site public sont un **jeu de démonstration anonyme** (1 024 canaux sur 16 NVR,
« Site 1 » à « Site 16 », « Caméra 01 » à « Caméra 64 », adresses en 10.0.xxx.xxx) : aucun nom
de site, de caméra ni d'adresse du parc réel n'y figure. Régénérer la base :
`python outils/seed_demo.py <dossier>`, puis servir ce dossier avec l'exécutable et capturer.

## Landing page en ligne

https://hikvision-monitor-demo.vercel.app — projet Vercel `james-ae85/hikvision-monitor-demo`.
Source déployée : `deploy/landing/` (`index.html` = `marketing/landing.html` avec `/app.apk`
renommé en `/HikvisionMonitor.apk`). Redéployer : `cd deploy/landing && npx vercel deploy --prod --yes`.

## Sécurité — corrections appliquées

Audit Hackaiz du 05/11/2026 sur ce dépôt (17 détections). État après correction :

| Détection | Gravité | Correction |
|---|---|---|
| Trafic non chiffré autorisé (Android) | Élevée | `usesCleartextTraffic="false"` + `res/xml/network_security_config.xml` : clair autorisé uniquement vers les IP du serveur déclarées |
| Absence de CSP | Moyenne | `Content-Security-Policy` sur le site (`default-src 'none'`) et sur le dashboard |
| Clickjacking | Moyenne | `X-Frame-Options: DENY` + `frame-ancestors 'none'` |
| Politique de confidentialité absente | Moyenne | page `/confidentialite` + lien en pied de page |
| `requests` (5 avis) | Moyenne/Info | `requests>=2.34.2` — première version sans avis OSV |
| `python-dotenv` (2 avis) | Moyenne/Info | `python-dotenv>=1.2.4` — première version sans avis OSV |
| XML non sécurisé — CWE-611 | Moyenne | `defusedxml` + refus de toute `DOCTYPE`/`ENTITY` avant parsing |
| Détails techniques exposés — CWE-209 | Faible | erreur générique + référence de corrélation ; détail au journal seulement |
| `X-Content-Type-Options` absent | Faible | `nosniff` |
| `Referrer-Policy` absente | Faible | `no-referrer` |
| CSP avec `unsafe-inline` (dashboard) | Durcissement | script et styles sortis dans `app.js` / `app.css` ; `script-src 'self'; style-src 'self'`, aucun contenu inline dans la page |
| RGPD : responsable et droits absents | Moyenne | page `/confidentialite` complétée : responsable du traitement, base légale, durées, droits d'accès / rectification / effacement / limitation / opposition / portabilité, réclamation |
| XML non sécurisé (2ᵉ passe) | Moyenne | suppression du repli `ET.fromstring` : `defusedxml` obligatoire, parsing refusé s'il manque |

Les erreurs de collecte (`last_error` des NVR) restent stockées en base et visibles dans le
dashboard authentifié : utile au diagnostic, sans exposition anonyme.

## État
Projet redémarré de zéro le 14/10/2026.
- Étape 1 terminée : profil + dossier + spec.
- Étape 2 terminée : découverte ISAPI sur les 5 NVR → [`docs/DISCOVERY_2026-10-14.md`](docs/DISCOVERY_2026-10-14.md).
- Étape 3 terminée : moniteur + base SQLite + dashboard (http://127.0.0.1:8765). Décisions : [`docs/DECISIONS.md`](docs/DECISIONS.md).
- Étape 4 terminée : export Excel via `python src/export_excel.py` ou bouton CSV dans le dashboard. Rapports datés dans `reports/`.

## Installer
```
pip install -r requirements.txt
```

## Lancer
Double-cliquer `start_monitor.bat`. La supervision tourne tant que sa fenêtre reste ouverte ; la fermer arrête tout.
- Un cycle de test seul : `python src/main.py --once`
- Tests des règles de la spec : `python tests/test_store.py` (sans dépendance) ou `pytest -q`
- Le dashboard écoute sur `127.0.0.1` par défaut (ce PC seulement). Pour l'ouvrir depuis un téléphone, mettre `DASHBOARD_HOST` à l'IP du PC dans `config/.env` et **renseigner `DASHBOARD_TOKEN`** — sinon les noms et IP des caméras sont exposés à tout le réseau. Première ouverture : `http://<ip>:8765/?token=<jeton>`.

## Alertes
Une caméra hors ligne (ou qui n'enregistre plus) au-delà de `OFFLINE_ALERT_THRESHOLD` / `NO_RECORDING_THRESHOLD` secondes est signalée dans `logs/monitor.log` (une seule fois par anomalie) et, si `ALERT_WEBHOOK` est rempli dans `config/.env`, envoyée à ce webhook. L'historique est purgé au-delà de `RETENTION_DAYS` jours.

## Application Android (APK)
Le kit contient `HikvisionMonitor.apk` : une icône sur l'écran d'accueil, fenêtre plein écran,
sans barre d'adresse. C'est un habillage WebView du dashboard, pas une application native.

**Installation depuis le téléphone** (même réseau que le serveur) : ouvrir `http://<serveur>:8765/`,
bouton « APK Android ». Android demande d'autoriser l'installation d'une source inconnue.
Au premier lancement : saisir l'adresse (`http://192.168.88.80:8765`) et le jeton.

**Limites assumées** : trafic HTTP en clair (réseau local uniquement), pas de notifications push,
pas de Play Store, et chaque évolution de l'interface impose de reconstruire l'APK.

**Reconstruction** : `android\build_apk.bat` — voir `android/README.md`.
La clé de signature (`android/keystore.jks` + `keystore.properties`) doit être sauvegardée :
sans elle, aucune mise à jour ne peut remplacer une installation existante.

## Captures d'écran des caméras
Trois usages, aucun serveur vidéo supplémentaire (tout passe par l'ISAPI déjà utilisé) :
- **Bouton 📷 sur chaque ligne du tableau** : affiche l'image JPEG de la caméra à l'instant.
- **« Enregistrer la capture »** : écrit le JPEG dans `reports/snapshots/<AAAA-MM-JJ>/`.
- La capture est prise **directement sur la caméra** (1920×1080). Le NVR, lui, ne renvoie
  qu'un JPEG **704×576** quel que soit le canal demandé : le repli sur le NVR n'est utilisé
  que si la caméra est injoignable.
- **Capture automatique à la coupure** : quand une caméra passe de ONLINE à OFFLINE, sa dernière
  image est enregistrée avec le suffixe `_hors-ligne` — preuve de ce qu'elle montrait avant la panne.

Les captures sont des **données personnelles** : elles sont purgées au-delà de `RETENTION_DAYS`
jours (mettre `RETENTION_DAYS=0` dans `config/.env` pour les conserver indéfiniment).

## Historique et export
L'historique des changements s'affiche sur une période choisie — **24 h, 7 j, 30 j ou 90 j** — et
s'exporte en CSV sur cette même période (bouton « Télécharger (CSV) »).

Le CSV utilise le séparateur `;` avec BOM UTF-8 : il s'ouvre directement dans Excel, avec la date
et l'heure **locales**, le NVR, le canal, la caméra, l'événement, l'ancienne et la nouvelle valeur.
Les accents sont conservés.

La profondeur réelle dépend de `RETENTION_DAYS` (90 jours par défaut, dans `config/.env`) : au-delà,
les événements sont purgés et ne peuvent plus être exportés. Volumes mesurés sur cette installation :
3 296 événements en 13 jours, soit ~270 Ko de CSV pour 30 jours.

L'affichage est plafonné à 1 000 lignes pour rester fluide ; le compteur indique le total réel et
l'export contient **toutes** les lignes de la période.

## Renommer une caméra
Un clic sur le nom d'une caméra le rend modifiable : `Entrée` applique, `Échap` annule.

Le renommage se fait en **deux temps**, parce que les modèles ne se comportent pas tous pareil :
1. **sur la caméra elle-même** (`/ISAPI/System/Video/inputs/channels/<n>`) quand elle est joignable ;
2. **sur le NVR** (`/ISAPI/ContentMgmt/InputProxy/channels/<n>`), suffisant pour les modèles anciens.

Le nom est ensuite **relu sur le NVR** : s'il n'a pas été retenu, l'ancien nom revient à l'écran
avec le détail de l'échec (caméra injoignable, mot de passe différent, refus du NVR).

**Pourquoi deux niveaux** : certains modèles récents — `DS-2CD1047G2H-LIUF/SRB`, firmware
`V5.8.10` — réécrivent le nom du canal avec le leur. Renommer uniquement côté NVR renvoie
« statut OK » mais le nom reste inchangé. 15 caméras de ce modèle sont installées
(2 WAREHOUSE, 10 OFFICE, 2 FACTORY1, 1 FACTORY2).

- 32 caractères maximum, nom vide et caractères de contrôle refusés.
- Chaque renommage produit un événement `CAMERA_RENAMED` dans l'historique, donc dans l'export CSV.
- Pour désactiver toute écriture : `ALLOW_NVR_WRITE=false` dans `config/.env` (l'API renvoie 403).

## Définition des caméras (MP)
Chaque caméra affiche sa **définition réelle** : la résolution de son flux principal telle que le
NVR la transmet, convertie en classe commerciale (2, 4, 5, 8 MP…).

- Source : `/ISAPI/Streaming/channels` du NVR, **une seule requête pour tout le NVR**. Seuls les
  canaux `X01` sont retenus ; les `X02` sont les sous-flux 704×576 et ne qualifient pas la caméra.
- Colonne « Définition » triable dans le tableau, ligne de répartition au-dessus, et colonnes
  `Largeur (px)`, `Hauteur (px)`, `Definition` dans l'export CSV.
- Mesure sur ce parc : **226 caméras en 2 MP**, 41 en 4 MP, 3 en 5 MP (2560×1920), 1 en 3 MP,
  1 en 2 MP équivalent (1600×1200) ; 7 canaux sans flux, donc sans définition.

**C'est la résolution réellement transmise, pas la capacité maximale du capteur.** Une caméra 4 MP
réglée en 1080p apparaît en 2 MP — c'est ce qu'elle envoie, et c'est ce qui détermine la qualité
d'image et le volume de stockage. Lire la capacité maximale du capteur demanderait d'interroger
chaque caméra individuellement (283 requêtes) : faisable, mais à la demande.

## Focale des caméras (mm)
Chaque caméra porte une **focale saisie par vous** (ex. `4mm`, `2.8mm`, `2.8-12mm`), stockée en base,
filtrable, triable et exportée en CSV.

**Pourquoi une saisie manuelle** : ni l'ISAPI (`deviceInfo`, `capabilities`, `Image/channels`) ni
l'ONVIF ne l'exposent — vérifié sur une caméra DS-2CD1047G2H : aucune balise `lens`/`focal`, et
l'ONVIF est désactivé sur ces modèles (« ONVIF integrate function is disabled »). La valeur n'existe
que sur l'étiquette de l'objectif.

- Clic sur la cellule « Focale » : `4`, `4mm`, `2,8 mm`, `2.8-12mm` sont normalisés en `4mm`,
  `2.8mm`, `2.8-12mm` ; une saisie non numérique est refusée avec un message.
- Cellule vide = valeur effacée.
- La collecte **n'écrase jamais** cette valeur (elle n'est pas alimentée par le NVR).
- Sélecteur « Toutes focales » alimenté par les valeurs réellement saisies, avec effectifs.

## Code
| Fichier | Rôle |
|---|---|
| `src/main.py` | **point d'entrée unique** : boucle de supervision + serveur web + API |
| `src/config.py` | lecture de `config/.env` (secrets jamais journalisés) |
| `src/isapi.py` | client ISAPI en lecture seule (GET + Digest) |
| `src/collector.py` | instantané par NVR, NVR en parallèle, isolés en cas d'erreur |
| `src/store.py` | SQLite : inventaire, état, historique, cycles ; aucune suppression |
| `src/static/index.html` | dashboard |
|| `src/discovery.py` | outil de découverte des endpoints |
|| `src/export_excel.py` | export vers le modèle Excel maître (Summary, Daily Log, Camera Performance) |

API : `/api/summary`, `/api/cameras`, `/api/events`, `/api/cameras.csv`, `POST /api/refresh`, `POST /api/export` (génère le rapport), `GET /reports/<fichier>` (le télécharge) et `GET /api/snapshot?nvr_id=…&channel=…[&save=1]` (image JPEG d'une caméra, affichage ou enregistrement), `GET /snapshots/<date>/<fichier>` (relit une capture). `GET /api/events?days=30&limit=1000` (historique borné à la période) et `GET /api/events.csv?days=30` (export CSV de la période).

Le dashboard propose aussi un bouton **Générer le rapport Excel** qui produit le rapport dans `reports/` sans passer par un terminal.

## Arborescence
```
docs/      spécification, rapport de découverte, modèle Excel maître (CCTV_TEMPLATE.xlsx)
src/       code (un seul point d'entrée) ; discovery.py = outil de découverte (lecture seule)
config/    .env.example (modèle) ; .env réel rempli par l'humain, jamais versionné
data/      base SQLite + réponses brutes de découverte (générées)
logs/      journaux (générés, sans secrets)
reports/   exports Excel/CSV datés (générés)
tests/     tests et scripts d'analyse
```

## Faits vérifiés sur le matériel (14/10)
| IP NVR | deviceName (NVR) | Caméras configurées | En ligne |
|---|---|---|---|
| 172.20.20.90 | WAREHOUSE | 41 | 39 |
| 172.20.20.91 | ADMIN FACTORY | 58 | 57 |
| 172.20.20.92 | SECURITY AREA | 62 | 58 |
| 172.20.20.93 | FACTORY PROD NVR | 57 | 53 |
| 172.20.20.94 | FACTORY PRODUCTION | 63 | 59 |
| **Total** | | **281** | **266** |

Accès ISAPI : HTTP Digest obligatoire. Modèle des NVR : DS-7764NI-M4.
