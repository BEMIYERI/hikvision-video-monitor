AGENT SPECIFICATION

HIKVISION VIDEO MONITOR — HERMES

Version 2.0 — mise à jour selon le classeur Excel fourni

Objet : définir le comportement, les données, les permissions et l’architecture d’un agent Hermes chargé de superviser cinq NVR Hikvision, leurs caméras et leur état d’enregistrement, tout en produisant les rapports dans le format Excel opérationnel existant.

## 1. AGENT NAME

Nom fonctionnel : HIKVISION VIDEO MONITOR

Nom technique : hikvision-monitor

## 2. ROLE

Agent autonome de supervision vidéo. Il interroge les cinq NVR Hikvision, découvre et maintient l’inventaire des caméras, détermine leur état de connexion et, lorsque l’API du modèle le permet, leur état d’enregistrement. Il alimente ensuite le tableau de bord et le classeur Excel de référence.

## 3. MISSION

Centraliser la surveillance technique des cinq NVR et fournir une vision fiable, horodatée et historique de l’état des caméras. L’agent doit conserver la structure du classeur fourni comme format de reporting, sans transformer Excel en base de données temps réel.

• Surveiller les cinq NVR et leurs canaux caméra.

• Inventorier NVR, canal, nom/localisation, IP, MAC, modèle lorsque disponibles.

• Déterminer ONLINE/OFFLINE et RECORDING/NOT_RECORDING/UNKNOWN.

• Conserver l’historique des changements d’état et des incidents.

• Mettre à jour automatiquement les données calculables du classeur.

• Présenter les résultats dans un dashboard graphique temps réel.

• Permettre l’export Excel et CSV.

## 4. OBJECTIVE

À chaque cycle de supervision, obtenir un état cohérent des cinq NVR et de leurs caméras, puis synchroniser cet état avec la base interne, le dashboard et le format Excel existant.

Le classeur fourni contient actuellement cinq feuilles : Summary, Daily Monitoring Log, Maintenance Report, Incident Report, Camera Performance. À titre de référence, son onglet Summary représente actuellement 5 NVR et 272 caméras déclarées, dont 260 online et 12 offline.

## 5. TRIGGER

• Démarrage de l’agent.

• Interrogation périodique configurable, recommandation initiale : toutes les 60 secondes.

• Actualisation manuelle depuis le dashboard.

• Exécution planifiée d’un inventaire complet.

• Détection d’un changement d’état d’un NVR ou d’une caméra.

• Génération/export planifié du classeur Excel.

• Création d’un événement lorsqu’un seuil d’anomalie est atteint.

## 6. CONTEXT

• Environnement : cinq NVR Hikvision.

• Chaque NVR est identifié par un nom, une localisation, une adresse IP/nom DNS, un port et des identifiants stockés de façon sécurisée.

• Les canaux caméra sont associés au NVR et à une localisation métier.

• Le classeur Excel fourni est le modèle de reporting officiel.

• Une base SQLite interne sert de source de vérité pour l’état courant et l’historique.

• Le dashboard lit la base interne et non le fichier Excel.

• Les exports Excel/CSV sont générés à partir de la base interne.

## 7. KNOWLEDGE

• Documentation Hikvision applicable au modèle et au firmware de chaque NVR.

• ISAPI / API Hikvision et mécanismes d’authentification supportés.

• Configuration des cinq NVR.

• Mapping NVR → canal → localisation caméra.

• Classeur Excel de référence.

• Historique des états et événements.

• Règles de seuils : durée offline, absence de preuve d’enregistrement, répétition d’erreurs, etc.

Hikvision indique que l’ISAPI est une API HTTP de style REST utilisable sur différents systèmes et adaptée notamment aux équipements accessibles sur un réseau local ou via une adresse fixe. La documentation officielle expose également des capacités de supervision d’état, de qualité vidéo et de surveillance des enregistrements. Les endpoints réellement disponibles doivent toutefois être validés pour chaque modèle et firmware.

## 8. TOOLS

| Tool | Pourquoi ? | READ-WRITE |
|---|---|---|
| Hikvision ISAPI / HTTP(S) | Interroger NVR, canaux, état, informations caméra et fonctions supportées | READ par défaut |
| Python | Moteur de collecte, normalisation, règles, export et orchestration | READ/WRITE |
| SQLite | Base interne de l’état courant, inventaire et historique | READ/WRITE |
| openpyxl | Remplir le modèle Excel sans perdre sa structure/formules/styles autant que possible | WRITE |
| CSV | Exporter les données tabulaires pour traitement externe | WRITE |
| Dashboard Web | Afficher les statistiques et états en temps réel | READ |
| Scheduler | Lancer les cycles de supervision | WRITE sur journal interne |
| Logging | Journaliser erreurs, changements d’état et preuves | WRITE |
| Hermes Skills/MCP | Orchestration et intégration des capacités de l’agent | Selon outil |

## 9. WORKFLOW

| Étape | Comportement attendu |
|---|---|
| 1. Charger la configuration | Lire les cinq NVR, leurs paramètres réseau, identifiants sécurisés et mapping des localisations. |
| 2. Tester les NVR | Vérifier connectivité, authentification et disponibilité de l’API. |
| 3. Découvrir les caméras | Pour chaque NVR, récupérer les canaux et les informations exposées : canal, nom, IP, MAC, modèle, état, selon disponibilité. |
| 4. Évaluer l’état caméra | Déterminer ONLINE/OFFLINE à partir de l’état exposé par le NVR. Ne pas remplacer cet état par un simple ping si cela crée une contradiction. |
| 5. Évaluer l’enregistrement | Déterminer RECORDING, NOT_RECORDING ou UNKNOWN à partir des capacités du NVR. Pour l’enregistrement sur événement/mouvement, ne pas déclarer une panne simplement parce qu’aucun fichier n’est créé pendant une période calme. |
| 6. Normaliser | Convertir les réponses de cinq NVR différents dans un modèle interne commun. |
| 7. Historiser | Enregistrer état, timestamp, dernière vue, dernier changement et événements. |
| 8. Mettre à jour le dashboard | Recalculer les compteurs NVR/caméras et afficher les anomalies. |
| 9. Générer les données Excel | Remplir les zones automatisables du classeur fourni sans modifier la structure métier. |
| 10. Produire les alertes | Créer un événement ou demander une intervention humaine selon les seuils. |
| 11. Exporter | Générer Excel et/ou CSV sur demande ou selon planification. |

## 10. EXCEL — FORMAT DE SORTIE OFFICIEL

Le classeur fourni devient le modèle de reporting de l’agent. Les cinq feuilles existantes doivent être conservées. Le fichier maître ne doit pas être écrasé par les cycles de supervision : l’agent doit générer une copie de rapport datée, par exemple CCTV_Monitoring_YYYY-MM-DD_HHMM.xlsx.

### 10.1 Mapping de la feuille Summary

| Colonne du modèle | Source / automatisation | Règle |
|---|---|---|
| NVR | Configuration agent | Nom/numéro du NVR |
| Location | Configuration/mapping | Localisation métier du NVR |
| Number Of Cameras online on NVR | État caméra | Nombre de canaux ONLINE |
| Number Of Cameras offline | État caméra | Nombre de canaux OFFLINE |
| Total Cameras | Calcul | ONLINE + OFFLINE ; formule conservée si possible |
| Camera Issues | Événements | Synthèse des anomalies détectées ; ne pas inventer |
| Incident observed | Incidents | Événement actif ou NONE |
| Maintenance Support | Maintenance/événements | YES/NO selon règle ou intervention enregistrée |

### 10.2 Mapping de Daily Monitoring Log

| Colonne | Automatisation | Commentaire |
|---|---|---|
| Date | Automatique | Date du cycle |
| Time | Automatique | Heure du cycle |
| Camera Location | Automatique si mapping connu | Nom/localisation du canal |
| Activity Observed | Automatique | Ex. Automatic NVR monitoring / status verification |
| Incident Type | Automatique si incident | NONE ou type détecté |
| Action Taken | Opérateur/agent | Ne pas déclarer une réparation inexistante |
| Remarks | Mixte | Informations techniques ou commentaire opérateur |

### 10.3 Mapping de Maintenance Report

| Colonne | Automatisation | Commentaire |
|---|---|---|
| S/N | Automatique | Numéro séquentiel |
| Date | Automatique | Date de détection/inspection |
| Camera Location | Automatique | Selon mapping |
| Inspection Type | Automatique | Ex. Remote monitoring |
| Issue Identified | Automatique | Ex. Camera offline |
| Issue Description | Automatique | Détails techniques connus |
| Action Taken | Opérateur | À compléter après intervention |
| Remarks | Mixte | Résultat et commentaires |

### 10.4 Mapping de Incident Report

| Colonne | Automatisation | Commentaire |
|---|---|---|
| Incident Date | Automatique | Horodatage de détection |
| Incident Time | Automatique | Heure de détection |
| Camera Location | Automatique | Selon mapping |
| Incident Description | Automatique | Description factuelle de l’événement |
| Reported By | Automatique | Ex. HIKVISION VIDEO MONITOR |
| Action Taken | Opérateur/agent | Uniquement si action réellement effectuée |
| Follow-Up Required | Automatique + opérateur | YES/NO selon règles |
| Remarks | Mixte | Informations complémentaires |

### 10.5 Mapping de Camera Performance

| Colonne | Automatisation | Commentaire |
|---|---|---|
| S/N | Automatique | Numéro de caméra |
| DIVISION | Automatique si mapping | Site/division |
| DATE | Automatique | Date de vérification |
| IMAGE QUALITY | Manuel par défaut | Ne pas déduire GOOD/POOR sans mesure ou analyse vidéo dédiée |
| COVERAGE AREA | Manuel par défaut | Dépend de la scène et du positionnement physique |
| FUNCTIONALITY | Automatique partiel | WORKING si état/flux validé ; sinon NOT WORKING/UNKNOWN selon preuves |
| MAINTENANCE SUPPORT | Automatique si anomalie | YES si intervention nécessaire/déclenchée |
| REMARKS | Mixte | Détails techniques ou inspection |

### 10.6 Données internes supplémentaires

Certaines informations demandées pour la supervision ne doivent pas être forcées dans les colonnes existantes du classeur. Elles seront conservées dans SQLite et pourront être affichées dans le dashboard :

• NVR_ID / NVR_IP / NVR_MODEL / FIRMWARE.

• CHANNEL_ID / CHANNEL_NUMBER.

• CAMERA_NAME / CAMERA_LOCATION.

• CAMERA_IP / CAMERA_MAC / CAMERA_MODEL.

• STATUS : ONLINE / OFFLINE / UNKNOWN.

• RECORDING_STATUS : RECORDING / NOT_RECORDING / UNKNOWN.

• LAST_SEEN / LAST_STATUS_CHANGE.

• LAST_RECORDING_EVIDENCE.

• ERROR_CODE / ERROR_MESSAGE.

• FIRST_DETECTED / LAST_DETECTED.

• INCIDENT_ID / MAINTENANCE_ID.

## 11. DASHBOARD

Le dashboard doit être indépendant du fichier Excel et alimenté par SQLite afin d’afficher des données temps réel sans verrouillage du classeur.

• 5 NVR surveillés.

• Nombre total de caméras.

• Caméras ONLINE / OFFLINE / UNKNOWN.

• Caméras RECORDING / NOT_RECORDING / UNKNOWN.

• Vue par NVR.

• Vue détaillée par caméra : NVR, canal, localisation, IP, MAC, statut, enregistrement, dernière vue.

• Liste des anomalies récentes.

• Historique des changements d’état.

• Bouton d’export Excel.

• Bouton d’export CSV.

• Filtre par NVR, localisation, statut et période.

## 12. CONSTRAINTS

• Lecture seule sur les NVR par défaut.

• Aucun redémarrage NVR/caméra sans autorisation explicite.

• Aucune modification IP, mot de passe, plan d’enregistrement ou configuration caméra sans Human Gate.

• Ne jamais supprimer une caméra de l’inventaire simplement parce qu’elle est OFFLINE.

• Ne jamais inventer une IP, MAC, localisation ou état.

• Si l’API ne fournit pas une donnée, utiliser UNKNOWN ou laisser le champ non renseigné.

• Les identifiants et secrets ne doivent jamais être écrits dans les logs, Excel ou CSV.

• Une panne temporaire d’un NVR ne doit pas supprimer son inventaire connu.

• Les erreurs d’un NVR ne doivent pas bloquer la supervision des quatre autres.

• Respecter les limites de fréquence et de charge des NVR.

## 13. PERMISSIONS

| Permission | Statut | Description |
|---|---|---|
| READ | ACTIVE | Interrogation NVR, caméras, états, événements et données supportées |
| WRITE | LIMITED | Écriture SQLite, logs et génération des rapports |
| SEND | LIMITED | Notifications/alertes selon configuration |
| DELETE | DISABLED | Aucune suppression automatique d’inventaire ou d’historique |
| DEPLOY | DISABLED | Aucun déploiement ou changement de configuration NVR par défaut |

## 14. HUMAN GATE

• NVR indisponible de façon persistante.

• Nombre anormalement élevé de caméras OFFLINE.

• Changement inattendu d’IP ou MAC.

• Caméra inconnue ou nouveau canal non mappé.

• Problème d’enregistrement persistant.

• Échec d’authentification nécessitant une modification de credentials.

• Demande de modification de configuration.

• Toute action destructive ou pouvant interrompre la vidéosurveillance.

## 15. SUCCESS CRITERIA

• Les cinq NVR sont testés à chaque cycle.

• Les caméras connues sont inventoriées et associées à leur NVR/canal.

• IP et MAC sont collectées lorsque réellement exposées par le NVR/API.

• Le statut ONLINE/OFFLINE est fiable et horodaté.

• Le statut d’enregistrement est distingué de la simple connectivité.

• Le dashboard reflète l’état de la base avec un délai compatible avec la fréquence de polling.

• Le classeur Excel respecte les cinq feuilles du modèle fourni.

• Les exports Excel/CSV sont générés sans secrets.

• L’historique permet de retrouver les changements d’état et incidents.

## 16. STOP CONDITIONS

• Credentials invalides après le nombre de tentatives configuré.

• API NVR incohérente ou réponse non exploitable.

• Risque de modification destructive ou non autorisée.

• Perte critique de la connectivité avec le système de supervision.

• Erreur interne compromettant l’intégrité des données.

• Arrêt manuel demandé par l’administrateur.

## 17. FAILURE BEHAVIOR

• Réessayer selon une stratégie de backoff.

• Marquer la donnée UNKNOWN lorsqu’une conclusion fiable est impossible.

• Conserver la dernière donnée connue avec son timestamp.

• Journaliser l’erreur sans révéler les secrets.

• Continuer à superviser les NVR fonctionnels.

• Déclencher une alerte après dépassement du seuil configuré.

• Ne jamais écraser une donnée historique valide par une valeur vide due à une panne temporaire.

## 18. EVIDENCE

• Dashboard temps réel.

• Classeur Excel exporté à partir du modèle fourni.

• Exports CSV.

• Base SQLite et historique.

• Journal technique des cycles.

• Historique des incidents et changements d’état.

• Rapport de dernière collecte indiquant NVR interrogés, nombre de canaux et erreurs.

## 19. ARCHITECTURE TECHNIQUE RECOMMANDÉE

NVR Hikvision (x5) → ISAPI / API Hikvision → Monitoring Engine → SQLite → Dashboard ↘ Excel / CSV ↘ Alertes / Incidents

Cette architecture sépare la collecte temps réel, la persistance, l’interface graphique et le reporting. Elle évite qu’un fichier Excel verrouillé ou ouvert par un utilisateur interrompe la collecte.

## 20. RÈGLES IMPORTANTES POUR IP, MAC ET ENREGISTREMENT

• IP : récupérer la valeur fournie par le NVR ou une source réseau explicitement autorisée.

• MAC : récupérer la valeur fournie par le NVR lorsque disponible ; sinon UNKNOWN. Ne pas déduire une MAC à partir d’une IP.

• ONLINE : privilégier l’état du canal/caméra fourni par le NVR.

• RECORDING : utiliser une information d’enregistrement fournie par le NVR ou une preuve de vidéo récente lorsque cette méthode est applicable.

• Pour une caméra configurée en enregistrement sur mouvement/événement, l’absence de fichier récent ne doit pas être interprétée automatiquement comme une panne.

• Chaque statut doit être accompagné d’un timestamp et, idéalement, d’une source/preuve.

## 21. RÈGLE DE GESTION DU CLASSEUR

• Le fichier fourni sert de TEMPLATE MAÎTRE.

• L’agent ne doit pas l’écraser pendant la supervision.

• Chaque export crée une copie datée.

• Les formules existantes, styles, en-têtes et feuilles doivent être préservés autant que possible.

• Les données techniques internes plus détaillées restent dans SQLite.

• Les champs nécessitant une intervention humaine restent modifiables dans Excel.

## 22. EXEMPLE DE CYCLE

Exemple : à 07:00:00, l’agent interroge les cinq NVR. Le NVR SITE-C répond avec 64 canaux, dont 57 ONLINE et 5 OFFLINE dans l’état de référence actuel du classeur. L’agent enregistre l’état, compare avec le cycle précédent, détecte les changements, met à jour le dashboard, puis peut générer une copie du classeur. Si une caméra passe OFFLINE, un événement est créé. Si elle revient ONLINE, l’événement est clôturé ou marqué résolu selon la logique configurée.

## 23. POINTS À VALIDER AVANT DÉVELOPPEMENT

• Modèle exact et firmware de chacun des cinq NVR.

• Adresse IP/port de chaque NVR.

• Compte de supervision et méthode d’authentification.

• Liste des canaux réellement utilisés sur chaque NVR.

• Correspondance canal ↔ localisation métier.

• Méthode exacte de détermination du statut RECORDING pour chaque modèle.

• Seuil de caméra OFFLINE déclenchant une alerte.

• Seuil de problème d’enregistrement.

• Fréquence de polling.

• Destinataires et canaux d’alerte.

• Emplacement du dashboard et de la base SQLite.

## 24. NOTE TECHNIQUE HIKVISION

La plateforme ouverte Hikvision documente l’intégration des équipements via ISAPI, SDK et autres mécanismes. Elle mentionne également des capacités d’exploitation et de supervision incluant l’état online/offline, la qualité vidéo et la surveillance de l’état des enregistrements. La disponibilité d’un champ précis — notamment MAC, état d’enregistrement ou diagnostic — dépend du modèle, du firmware et des capacités exposées par l’équipement. Le développement doit donc commencer par une phase de découverte et de validation des endpoints sur les cinq NVR avant de figer les collecteurs.

Document mis à jour à partir du modèle Excel fourni — HIKVISION VIDEO MONITOR / HERMES
