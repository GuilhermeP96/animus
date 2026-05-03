@echo off
REM ============================================================================
REM Animus Peer Installer Kit — Windows double-click entry point
REM ----------------------------------------------------------------------------
REM Self-elevates (UAC) and runs install.ps1 sitting next to it. peer.env in
REM the same folder provides hub_url + secret + node_id automatically.
REM ============================================================================
setlocal
cd /d "%~dp0"

set "PS1_FILE=%~dp0install.ps1"
if not exist "%PS1_FILE%" (
    echo [ERROR] install.ps1 nao encontrado em "%PS1_FILE%".
    echo Voce extraiu o ZIP por completo? install.bat, install.ps1 e peer.env
    echo precisam ficar na MESMA pasta.
    pause
    exit /b 1
)

REM ── Self-elevate (UAC) ─────────────────────────────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Solicitando privilegios de administrador (UAC)...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
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
