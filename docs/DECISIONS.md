# Décisions validées par l'humain

## 14/10/2026
1. **Nom des NVR = `deviceName` configuré dans le NVR**, lu par `/ISAPI/System/deviceInfo` à chaque cycle :
   .90 SITE-A · .91 SITE-B · .92 SITE-C · .93 SITE-D · .94 SITE-E.
   Le nom inscrit dans `config/.env` sert seulement d'identifiant de secours quand le NVR est injoignable. Dans ce cas, on affiche le dernier deviceName connu, enregistré en base.
2. **Nom des caméras = nom affiché dans le NVR**, tel quel (y compris « Camera 01 »). Aucun renommage ni nom de remplacement. La caméra est identifiée de façon unique par NVR + n° de canal, et le canal est toujours affiché à côté du nom.
3. **Modèle Excel maître = `docs/CCTV_TEMPLATE.xlsx`** (copie de « CCTV DETAILS OCTOBER 2026.xlsx »). Il n'est jamais modifié : chaque export produit une copie datée dans `reports/`.

## Constats sur le classeur (14/10)
- 5 feuilles conformes à la spec. Un logo est présent sur 4 feuilles ; un test a montré qu'il est conservé après enregistrement avec openpyxl.
- Summary : 8 formules (`E = C + D`, totaux ligne 7) à conserver. Les totaux de l'onglet recoupent ceux des enregistreurs : les anciens libellés étaient attribués aux mauvaises IP.
- Camera Performance : 203 lignes saisies à la main (division Ogun-Mowe). Seuls **10 emplacements sur 203** correspondent exactement à un nom de caméra du NVR, ce qui empêche un remplissage automatique fiable caméra par caméra.
- Daily Monitoring Log : 359 lignes de rondes humaines, à ne pas noyer sous des lignes automatiques.
