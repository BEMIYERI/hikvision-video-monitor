@echo off
setlocal
set JAVA_HOME=C:\Users\nanga\tools\jdk17\jdk-17.0.20.1+1
set SDK=C:\Users\nanga\tools\android-sdk
set BT=%SDK%\build-tools\34.0.0
set AJAR=%SDK%\platforms\android-34\android.jar
set PROJ=%~dp0
set OUT=%PROJ%build
set PATH=%JAVA_HOME%\bin;%PATH%

if not exist "%PROJ%dist" mkdir "%PROJ%dist"
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"
mkdir "%OUT%\gen"
mkdir "%OUT%\classes"

echo [1/6] compilation des ressources
"%BT%\aapt2.exe" compile --dir "%PROJ%res" -o "%OUT%\res.zip"
if errorlevel 1 goto err

echo [2/6] APK de base
"%BT%\aapt2.exe" link -o "%OUT%\base.apk" -I "%AJAR%" --manifest "%PROJ%AndroidManifest.xml" -R "%OUT%\res.zip" --java "%OUT%\gen" --min-sdk-version 24 --target-sdk-version 34 --version-code 1 --version-name 1.0
if errorlevel 1 goto err

echo [3/6] compilation Java
dir /s /b "%OUT%\gen\*.java" > "%OUT%\sources.txt"
dir /s /b "%PROJ%src\*.java" >> "%OUT%\sources.txt"
"%JAVA_HOME%\bin\javac.exe" -nowarn -source 8 -target 8 -bootclasspath "%AJAR%" -classpath "%AJAR%" -d "%OUT%\classes" @"%OUT%\sources.txt"
if errorlevel 1 goto err

echo [4/6] conversion en dex
"%JAVA_HOME%\bin\jar.exe" cf "%OUT%\classes.jar" -C "%OUT%\classes" .
call "%BT%\d8.bat" --lib "%AJAR%" --min-api 24 --output "%OUT%" "%OUT%\classes.jar"
if errorlevel 1 goto err

echo [5/6] assemblage et alignement
copy /y "%OUT%\base.apk" "%OUT%\unsigned.apk" >nul
"%JAVA_HOME%\bin\jar.exe" uf "%OUT%\unsigned.apk" -C "%OUT%" classes.dex
call "%BT%\zipalign.exe" -p -f 4 "%OUT%\unsigned.apk" "%OUT%\aligned.apk"
if errorlevel 1 goto err

echo [6/6] signature
for /f "tokens=1,* delims==" %%a in ('findstr "storePassword" "%PROJ%keystore.properties"') do set KS=%%b
if not exist "%PROJ%keystore.jks" (
  "%JAVA_HOME%\bin\keytool.exe" -genkeypair -keystore "%PROJ%keystore.jks" -alias hikvision -keyalg RSA -keysize 2048 -validity 10000 -storepass %KS% -keypass %KS% -dname "CN=Hikvision Monitor, OU=Local, O=Qualissc, L=Yaounde, C=CM"
  if errorlevel 1 goto err
)
call "%BT%\apksigner.bat" sign --ks "%PROJ%keystore.jks" --ks-pass pass:%KS% --key-pass pass:%KS% --ks-key-alias hikvision --out "%PROJ%dist\HikvisionMonitor.apk" "%OUT%\aligned.apk"
if errorlevel 1 goto err
call "%BT%\apksigner.bat" verify --print-certs "%PROJ%dist\HikvisionMonitor.apk"

echo.
echo APK pret : %PROJ%dist\HikvisionMonitor.apk
exit /b 0

:err
echo.
echo ECHEC a l'etape precedente.
exit /b 1
