# Kit de présentation — Hikvision Video Monitor

| Fichier | Usage |
|---|---|
| `hikvision-video-monitor-presentation.mp4` | vidéo de présentation, 1 min 35, 1080p, voix off FR + sous-titres |
| `couverture-1600x900.png` | image de couverture (pitch, dossier, écran) |
| `couverture-1200x630.png` | format réseaux sociaux / OG |
| `capture-01..03` | captures du dashboard, données anonymisées |
| `capture-05-rapport-synthese.png` | feuille Summary du rapport Excel |
| `capture-06-rapport-cameras.png` | feuille Camera Performance |
| `capture-07-journal-quotidien.png` | feuille Daily Monitoring Log |
| `narration.md`, `sous-titres.srt` | texte et sous-titres réutilisables |

## Provenance des données

Les images Excel sont des captures du **vrai fichier produit par l'application** (modèle du client),
avec les logos du modèle et la référence interne du document retirés, et les données du jeu anonyme.

Toutes les captures proviennent d'un **jeu de démonstration anonyme** :
16 NVR (Site 1 à Site 16), 1 024 caméras (Caméra 01 à Caméra 64), adresses en `10.0.xxx.xxx`.
Aucun nom de site, de caméra ni aucune adresse réelle n'y figure.
Les chiffres affichés (1 007 en ligne, 32 399 changements sur 30 jours) sont ceux de ce jeu,
pas ceux d'un parc client.

## Régénérer

```bash
python outils/seed_demo.py <dossier>      # base de démonstration
python marketing/video/build_video.py     # voix + montage + sous-titres
```
Les plans sont les fichiers `marketing/video/scenes/*.html`, rendus en 1920×1080.
