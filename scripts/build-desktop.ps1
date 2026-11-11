param([string]$OutputDirectory)
$ErrorActionPreference='Stop'
# ASCII source, explicit UTF-8 C# compiler input; no configuration enters build.
$root=Split-Path $PSScriptRoot -Parent
if(-not $OutputDirectory){$OutputDirectory=Join-Path $root 'dist\desktop'}
[IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
$compiler=Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if(-not (Test-Path -LiteralPath $compiler)){throw '.NET Framework C# compiler required'}
$source=Join-Path $root 'desktop\windows\AnimusDesktop.cs'
$knowledgeSource=Join-Path $root 'desktop\windows\AnimusKnowledge.cs'
$previewSource=Join-Path $root 'desktop\windows\AnimusMarkdownPreview.cs'
$windows=Join-Path $root 'desktop\windows'
$sdk=Join-Path $windows 'vendor\webview2'
$dependencyLock=Get-Content -LiteralPath (Join-Path $windows 'preview-deps.lock.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach($entry in $dependencyLock.files.PSObject.Properties){
    $file=Join-Path $windows $entry.Name
    if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $entry.Value){throw ('Preview dependency checksum mismatch: '+$entry.Name)}
}
Copy-Item -LiteralPath (Join-Path $sdk 'Microsoft.Web.WebView2.Core.dll'),(Join-Path $sdk 'Microsoft.Web.WebView2.WinForms.dll') -Destination $OutputDirectory
Copy-Item -LiteralPath (Join-Path $sdk 'runtimes'),(Join-Path $windows 'preview') -Destination $OutputDirectory -Recurse -Force
$licenses=Join-Path $OutputDirectory 'licenses';[IO.Directory]::CreateDirectory($licenses) | Out-Null
Copy-Item -LiteralPath (Join-Path $sdk 'LICENSE.txt') -Destination (Join-Path $licenses 'WebView2-LICENSE.txt')
Copy-Item -LiteralPath (Join-Path $sdk 'package-signature.p7s') -Destination $licenses
Copy-Item -LiteralPath (Join-Path $windows 'preview-deps.lock.json'),(Join-Path $windows 'THIRD-PARTY-NOTICES.md') -Destination $OutputDirectory
$target=Join-Path $OutputDirectory 'Animus.exe'
$icon=Join-Path $OutputDirectory 'animus.ico'
$references=@('/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.Web.Extensions.dll','/r:System.Xml.dll',('/r:'+(Join-Path $sdk 'Microsoft.Web.WebView2.Core.dll')),('/r:'+(Join-Path $sdk 'Microsoft.Web.WebView2.WinForms.dll')))
$brandResource='/resource:'+(Join-Path $root 'desktop\windows\assets\datano.png')+',AnimusDesktop.Datano.png'
& $compiler /nologo /target:winexe /optimize+ /codepage:65001 /platform:anycpu "/out:$target" $brandResource @references $source $knowledgeSource $previewSource
if($LASTEXITCODE -ne 0){throw 'Desktop compilation failed'}
$export=Start-Process -FilePath $target -ArgumentList @('--export-icon',('"'+$icon+'"')) -WindowStyle Hidden -Wait -PassThru
if($export.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $icon)){throw 'Icon creation failed'}
& $compiler /nologo /target:winexe /optimize+ /codepage:65001 /platform:anycpu "/out:$target" "/win32icon:$icon" $brandResource @references $source $knowledgeSource $previewSource
if($LASTEXITCODE -ne 0){throw 'Desktop compilation failed'}
Copy-Item -LiteralPath (Join-Path $root 'LICENSE'),(Join-Path $root 'NOTICE') -Destination $OutputDirectory
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install-desktop.ps1') -Destination $OutputDirectory
Copy-Item -LiteralPath (Join-Path $root 'desktop\README.md') -Destination (Join-Path $OutputDirectory 'README.md')
$outputRoot=[IO.Path]::GetFullPath($OutputDirectory).TrimEnd('\','/')
$lines=Get-ChildItem -LiteralPath $outputRoot -File -Recurse | Where-Object {$_.Name -ne 'SHA256SUMS'} | Sort-Object FullName | ForEach-Object {
    (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()+'  '+$_.FullName.Substring($outputRoot.Length+1).Replace('\','/')
}
[IO.File]::WriteAllText((Join-Path $outputRoot 'SHA256SUMS'),(($lines -join "`n")+"`n"),[Text.UTF8Encoding]::new($false))
Get-FileHash -LiteralPath $target -Algorithm SHA256 | Select-Object Hash,Path
