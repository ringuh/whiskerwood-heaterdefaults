@echo off
setlocal EnableExtensions
rem Copy the HeaterDefaults mod from the modkit into this repo and stage the
rem built pak for a Workshop upload.
rem
rem   sync-from-modkit.bat
rem
rem Modkit location can be overridden:  set MODKIT=D:\path\Whiskerwood-Project

set "MOD_NAME=HeaterDefaults"
if not defined MODKIT set "MODKIT=E:\modding\Whiskerwood-Project"

set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "SRC=%MODKIT%\Content\Mods\%MOD_NAME%"
set "DST=%REPO%\Mod\%MOD_NAME%"
set "PAK=%LOCALAPPDATA%\Whiskerwood\Saved\mods\%MOD_NAME%\%MOD_NAME%.pak"
set "OUT=%REPO%\workshop\content"

if not exist "%SRC%\" (
  echo ERROR: modkit mod folder not found: %SRC%
  echo Set MODKIT=path\to\Whiskerwood-Project if it lives elsewhere.
  goto :fail
)
if not exist "%PAK%" (
  echo ERROR: %PAK% not found - run Cook ^& Install in the modkit first.
  goto :fail
)

rem --- source assets ------------------------------------------------------------
if not exist "%DST%\" mkdir "%DST%"
echo Copying assets from %SRC%
rem /PURGE only touches *.uasset, so the repo's HeaterDefaults.uplugin is kept.
robocopy "%SRC%" "%DST%" *.uasset /PURGE /NJH /NJS /NDL /NP
if errorlevel 8 (
  echo ERROR: copying assets failed.
  goto :fail
)
rem The repo's HeaterDefaults.uplugin (description, version) is the one that ships;
rem it is not overwritten from the modkit.

rem --- release files --------------------------------------------------------------
if not exist "%OUT%\" mkdir "%OUT%"
copy /Y "%PAK%" "%OUT%\" >nul || goto :fail
copy /Y "%DST%\%MOD_NAME%.uplugin" "%OUT%\" >nul || goto :fail

echo.
echo Staged for Workshop upload in workshop\content\:
dir /B "%OUT%"
for %%F in ("%PAK%") do echo Pak built: %%~tF  - make sure that is your latest Cook ^& Install.
echo.
echo Done. Review with: git status
pause
exit /b 0

:fail
pause
exit /b 1
