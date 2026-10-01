@echo off
setlocal EnableExtensions
rem Upload workshop\content\ to the Steam Workshop with SteamCMD.
rem Run sync-from-modkit.bat first, and update "changenote" in workshop\HeaterDefaults.vdf.

set "STEAM_USER=pienirinkula"
if not defined STEAMCMD set "STEAMCMD=E:\modding\steamcmd\steamcmd.exe"

set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "VDF=%REPO%\workshop\HeaterDefaults.vdf"

if not exist "%STEAMCMD%" (
  echo ERROR: SteamCMD not found at %STEAMCMD%
  goto :fail
)
if not exist "%REPO%\workshop\content\HeaterDefaults.pak" (
  echo ERROR: workshop\content\HeaterDefaults.pak missing - run sync-from-modkit.bat first.
  goto :fail
)

echo Uploading with account %STEAM_USER% ...
echo (SteamCMD asks for the password and Steam Guard code if it has no saved login.)
echo.
"%STEAMCMD%" +login %STEAM_USER% +workshop_build_item "%VDF%" +quit
if errorlevel 1 (
  echo.
  echo Upload failed - see the SteamCMD output above.
  goto :fail
)

echo.
echo Done. On the first upload SteamCMD writes the new item id into
echo "publishedfileid" in workshop\HeaterDefaults.vdf - commit that change.
echo New items start private: make it public on its Workshop page.
pause
exit /b 0

:fail
pause
exit /b 1
