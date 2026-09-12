@echo off
REM ============================================================================
REM Animus Peer Installer Kit — Windows double-click entry point
REM ----------------------------------------------------------------------------
REM Runs install.ps1 without administrator privileges. Python 3.13 and Git are
REM installed for the current user when needed. peer.env provides configuration.
REM ============================================================================
setlocal
cd /d "%~dp0"

set "PS1_FILE=%~dp0install.ps1"
REM Older ZIPs contained an extra animus-peer-* directory. Prefer the complete
REM nested kit when Explorer extracted one ZIP-named folder into another.
for /d %%D in ("%~dp0animus-peer-*") do (
    if exist "%%~fD\install.ps1" if exist "%%~fD\peer.env" set "PS1_FILE=%%~fD\install.ps1"
)
if not exist "%PS1_FILE%" (
    echo [ERROR] install.ps1 nao encontrado em "%PS1_FILE%".
    echo Voce extraiu o ZIP por completo? install.bat, install.ps1 e peer.env
    echo precisam ficar na MESMA pasta.
    pause
    exit /b 1
)

echo.
echo  ===============================================================
echo   Animus Peer Installer Kit
echo  ===============================================================
echo.
echo  peer.env (com hub URL, secret e node_id) sera lido
echo  automaticamente — voce NAO precisa colar o secret.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1_FILE%"
set "RC=%errorlevel%"

echo.
if %RC% equ 0 (
    echo [OK] Instalacao concluida.
) else (
    echo [ERRO] PowerShell saiu com codigo %RC%. Veja a saida acima.
    echo Tambem disponivel: COPILOT.md  ^(passos manuais para o GitHub Copilot^).
)
echo.
pause
exit /b %RC%
