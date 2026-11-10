param([string]$OutputDirectory)
$ErrorActionPreference='Stop'
# ASCII source, explicit UTF-8 C# compiler input; no configuration enters build.
$root=Split-Path $PSScriptRoot -Parent
if(-not $OutputDirectory){$OutputDirectory=Join-Path $root 'dist\desktop'}
[IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
$compiler=Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if(-not (Test-Path -LiteralPath $compiler)){throw '.NET Framework C# compiler required'}
$source=Join-Path $root 'desktop\windows\AnimusDesktop.cs'
$target=Join-Path $OutputDirectory 'Animus.exe'
$icon=Join-Path $OutputDirectory 'animus.ico'
$references=@('/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.Web.Extensions.dll')
& $compiler /nologo /target:winexe /optimize+ /codepage:65001 /platform:anycpu "/out:$target" @references $source
if($LASTEXITCODE -ne 0){throw 'Desktop compilation failed'}
$export=Start-Process -FilePath $target -ArgumentList @('--export-icon',('"'+$icon+'"')) -WindowStyle Hidden -Wait -PassThru
if($export.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $icon)){throw 'Icon creation failed'}
& $compiler /nologo /target:winexe /optimize+ /codepage:65001 /platform:anycpu "/out:$target" "/win32icon:$icon" @references $source
if($LASTEXITCODE -ne 0){throw 'Desktop compilation failed'}
Copy-Item -LiteralPath (Join-Path $root 'LICENSE'),(Join-Path $root 'NOTICE') -Destination $OutputDirectory
Get-FileHash -LiteralPath $target -Algorithm SHA256 | Select-Object Hash,Path
