# Application Android (APK)

Habillage WebView du dashboard. Ce n'est pas une application native : elle affiche l'interface
web servie par le moniteur. Voir le README principal pour les limites (HTTP en clair, pas de push,
pas de Play Store).

## Reconstruction

Chaîne utilisee sur le poste de developpement (aucun droit administrateur necessaire) :

| Element | Emplacement |
|---|---|
| JDK 17 (Temurin) | `C:\Users\nanga\tools\jdk17\jdk-17.0.20.1+1` |
| Android SDK | `C:\Users\nanga\tools\android-sdk` |
| Plateforme / build-tools | `android-34` / `34.0.0` |

```bat
cd android
build_apk.bat
```

Le script enchaine : `aapt2 compile` -> `aapt2 link` -> `javac` -> `d8` -> `zipalign` -> `apksigner`.
Aucun Gradle, aucun Android Studio.

Pour reinstaller la chaine ailleurs :

```bash
curl -L -o jdk17.zip "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse"
curl -fL -o cmdline-tools.zip "https://dl.google.com/android/repository/commandlinetools-win-13114758_latest.zip"
sdkmanager --sdk_root=<sdk> "platforms;android-34" "build-tools;34.0.0" "platform-tools"
```

## Signature — a sauvegarder

`keystore.jks` et `keystore.properties` ne sont **pas** versionnes. Sans eux, aucune mise a jour
de l'application ne peut remplacer l'installation existante : Android refuse un APK signe avec
une autre cle, il faut desinstaller l'ancienne version.

## Distribution

L'executable sert l'APK sur `/app.apk` des qu'il est pose a cote de lui. Depuis le telephone,
sur le meme reseau : ouvrir `http://<serveur>:8765/` puis le bouton « APK Android ».
