@echo off
REM ============================================================================
REM Animus - Peer Installation Kit (Windows .bat wrapper)
REM ----------------------------------------------------------------------------
REM Use this when you cannot pipe `irm | iex` (e.g. ZIP download, restricted
REM execution policy, or you just want to double-click an installer).
REM
REM What it does:
REM   1. Re-launches itself elevated (UAC prompt) so the script can install
REM      Python/Git via winget and register a Scheduled Task.
REM   2. Runs install-peer.ps1 sitting next to it, with ExecutionPolicy bypass.
REM
REM How to use:
REM   1. Download the repo as ZIP (from the hub UI: "Recruit a New Assassin"
REM      tab "Windows (ZIP + .bat)").
REM   2. Extract.
REM   3. Open the extracted folder, navigate to `scripts\`, double-click this
REM      file. Approve the UAC prompt. Enter the shared secret when asked.
REM ============================================================================

setlocal

REM Force the working directory to where this .bat lives (UAC re-launch
REM otherwise drops us into C:\Windows\System32).
cd /d "%~dp0"

set "PS1_FILE=%~dp0install-peer.ps1"

if not exist "%PS1_FILE%" (
    echo [ERROR] install-peer.ps1 nao foi encontrado em:
    echo         %PS1_FILE%
    echo.
    echo Voce extraiu o ZIP por completo? Esta .bat deve ficar em ZIP\scripts\.
    echo.
    pause
    exit /b 1
)

REM ── Self-elevate (UAC) ─────────────────────────────────────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Solicitando privilegios de administrador (UAC)...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

echo.
echo  ===============================================================
echo   Animus - Peer Installation Kit (Windows .bat wrapper)
echo  ===============================================================
echo.
echo  Esta janela vai pedir o secret compartilhado do hub.
echo  Cole o valor revelado em https://animus.datano.com.br/admin/peers
echo  (botao "Recruit a New Assassin"  ^>  "Reveal" ).
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1_FILE%"
set "RC=%errorlevel%"

echo.
if %RC% equ 0 (
    echo [OK] Instalacao concluida.
) else (
    echo [ERRO] PowerShell saiu com codigo %RC%. Veja a saida acima.
)
echo.
pause
exit /b %RC%
