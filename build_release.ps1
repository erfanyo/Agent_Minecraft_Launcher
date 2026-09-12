# -*- coding: utf-8 -*-
<#
Agent Minecraft Launcher 一键发布脚本:测试 + 准备组件 + 打包 + 成品启动检查 + GPG 签名。
用法(在项目根):
    .\build_release.ps1                    # 打包 + 签名
    .\build_release.ps1 -NoSign            # 只打包不签名
    .\build_release.ps1 -GpgExe "C:\...\gpg.exe"   # 指定 gpg 路径

流程:
  1) PyInstaller 按 AgentMinecraftLauncher.spec 打包 → dist\AgentMinecraftLauncher.exe
  2) 用你的 GPG 密钥对 exe 做 detached 装甲签名 → dist\AgentMinecraftLauncher.exe.sig
  3) 生成 SHA256 校验码 + 打印公钥指纹(供 RELEASE_NOTES / README 记录)

前提:
  - 正式构建固定使用 Python 3.14.7；推荐创建 .venv-release 并安装 requirements-release.txt
  - 已生成 ed25519 密钥(身份 erfanyo / 2933038076@qq.com)
  - gpg 在 PATH 或通过 -GpgExe 指定(注:Git 自带 gpg 不完整,建议用独立 GnuPG 2.5.x)
#>
[CmdletBinding()]
param(
    [string]$GpgExe = "",                 # 覆盖 gpg 路径;留空则从 PATH 找
    [switch]$NoSign,                      # 跳过签名(仅打包)
    [switch]$SkipTests,                   # CI 已单独跑完整测试时使用
    [string]$KeyId = "erfanyo",           # 用于签名的密钥 id/uid
    [string]$PythonExe = "",              # 留空:优先项目 .venv-release,其次 .venv/PATH；随后强制检查 3.14.7
    [string]$OutputDir = ""               # 留空输出到 dist;验证时可用 .tmp\release-validation
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ExeName = "AgentMinecraftLauncher.exe"
Set-Location $Root
if (-not $OutputDir) {
    $OutputDir = Join-Path $Root "dist"
} elseif (-not [System.IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir = Join-Path $Root $OutputDir
}
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

if (-not $PythonExe) {
    $releasePython = Join-Path $Root ".venv-release\Scripts\python.exe"
    $devPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $releasePython) {
        $PythonExe = $releasePython
    } elseif (Test-Path $devPython) {
        $PythonExe = $devPython
    } else {
        $PythonExe = (Get-Command python -ErrorAction Stop).Source
    }
}
if (-not (Test-Path $PythonExe)) { throw "找不到 Python: $PythonExe" }
$PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path

# ---- 1) 定位 gpg ----
function Find-Gpg {
    if ($GpgExe -and (Test-Path $GpgExe)) { return $GpgExe }
    $cmd = Get-Command gpg -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    # 回退:本项目装过的便携目录
    $candidates = @(
        "$Root\.tmp\gpg4win\gpginstall\bin\gpg.exe",
        "C:\Program Files\GnuPG\bin\gpg.exe",
        "C:\Program Files (x86)\GnuPG\bin\gpg.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    throw "找不到 gpg。做法:安装 GnuPG 或设 -GpgExe <gpg.exe 路径>"
}

# ---- 2) 测试与准备打包输入 ----
if (-not $SkipTests) {
    Write-Host "==> 1/5 完整自动测试 ==" -ForegroundColor Cyan
    $env:QT_QPA_PLATFORM = "offscreen"
    & $PythonExe -m unittest discover -v
    if ($LASTEXITCODE -ne 0) { throw "自动测试失败" }
}

Write-Host "==> 2/5 准备并验证内置组件 ==" -ForegroundColor Cyan
& $PythonExe tools\fetch_llamacpp.py
if ($LASTEXITCODE -ne 0) { throw "llama.cpp 准备失败" }
& $PythonExe tools\fetch_bridge_mod_jars.py
if ($LASTEXITCODE -ne 0) { throw "bridge-mod 准备失败" }
& $PythonExe tools\verify_release_inputs.py
if ($LASTEXITCODE -ne 0) { throw "正式打包输入检查失败" }

# ---- 3) 打包 ----
Write-Host "==> 3/5 PyInstaller 打包 (spec) ==" -ForegroundColor Cyan
# 只让 PyInstaller 从 Python 与 Windows 系统目录解析动态库。开发终端可能把
# Poppler、Git、Java 等工具目录加入 PATH；其中同名 ICU/MSVC DLL 会被误收进成品，
# 覆盖 Windows/Qt 应使用的运行库并导致 QtCore 启动失败。
$originalPath = $env:Path
$pythonDir = Split-Path -Parent $PythonExe
$windowsDir = $env:SystemRoot
$env:Path = @(
    $pythonDir,
    (Join-Path $pythonDir "Scripts"),
    (Join-Path $windowsDir "System32"),
    $windowsDir
) -join ";"
try {
    & $PythonExe -m PyInstaller --noconfirm --clean --distpath $OutputDir AgentMinecraftLauncher.spec
    if ($LASTEXITCODE -ne 0) { throw "打包失败" }
} finally {
    $env:Path = $originalPath
}
$exe = Join-Path $OutputDir $ExeName
if (-not (Test-Path $exe)) { throw "未找到产物: $exe" }
Write-Host "  产物: $exe" -ForegroundColor Green

Write-Host "==> 4/5 成品启动检查 ==" -ForegroundColor Cyan
# Windows runner 可以使用 qwindows；冻结包没有收集开发环境的 offscreen 插件。
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$smokeReport = Join-Path $OutputDir "smoke-report.txt"
Remove-Item -LiteralPath $smokeReport -Force -ErrorAction SilentlyContinue
$env:AMCL_CI_SMOKE_REPORT = $smokeReport
$smoke = Start-Process -FilePath $exe -ArgumentList "--amcl-ci-smoke" -PassThru -WindowStyle Hidden
try {
    Wait-Process -Id $smoke.Id -Timeout 90 -ErrorAction Stop
} catch {
    # PyInstaller 单文件程序会先启动解包父进程，再启动真正的应用子进程。
    # 超时时必须结束整棵进程树，否则子进程会继续占用 exe，导致下次打包无法覆盖。
    & "$env:SystemRoot\System32\taskkill.exe" /PID $smoke.Id /T /F 2>$null | Out-Null
    Get-Process -Name ([System.IO.Path]::GetFileNameWithoutExtension($ExeName)) -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $exe } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    throw "成品启动检查超过 90 秒，已停止测试进程"
}
$smoke.Refresh()
if ($smoke.ExitCode -ne 0) {
    $detail = if (Test-Path $smokeReport) { (Get-Content -LiteralPath $smokeReport -Raw).Trim() } else { "未生成检查报告" }
    throw "成品启动检查失败，退出码 $($smoke.ExitCode)：$detail"
}
Remove-Item -LiteralPath $smokeReport -Force -ErrorAction SilentlyContinue
Remove-Item Env:AMCL_CI_SMOKE_REPORT -ErrorAction SilentlyContinue
Write-Host "  exe 可启动，且内置组件完整" -ForegroundColor Green

# ---- 4) 签名(可跳过) ----
if ($NoSign) {
    Write-Host "==> 已跳过签名 (-NoSign)" -ForegroundColor Yellow
} else {
    Write-Host "==> 5/5 GPG 签名 ==" -ForegroundColor Cyan
    $gpg = Find-Gpg
    Write-Host "  gpg: $gpg" -ForegroundColor DarkGray
    # 装甲 detach 签名 → 显式输出到 <exe>.sig(文本,便于 GitHub 展示/用户粘贴)
    $sig = "$exe.sig"
    & $gpg --batch --yes --armor --detach-sign --output $sig --local-user $KeyId $exe
    if ($LASTEXITCODE -ne 0) { throw "GPG 签名失败(密钥 $KeyId)" }
    if (-not (Test-Path $sig)) { throw "未生成签名文件: $sig" }
    Write-Host "  签名: $sig" -ForegroundColor Green

    # 显示公钥指纹(供记录)
    Write-Host "  公钥指纹:" -ForegroundColor DarkGray
    & $gpg --list-keys --fingerprint $KeyId 2>$null | Select-String "D2D|ed25519"
}

# ---- 5) SHA256 校验码 ----
Write-Host "==> SHA256 ==" -ForegroundColor Cyan
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash
Write-Host "  SHA256: $hash" -ForegroundColor Green
$hashLine = "$($hash.ToLower())  $ExeName"
Set-Content -LiteralPath (Join-Path $OutputDir "SHA256SUMS.txt") -Value $hashLine -Encoding ascii
Write-Host ""
Write-Host "======== 发布清单 ($OutputDir) ========" -ForegroundColor Cyan
Get-ChildItem $OutputDir -File | Where-Object { $_.Name -in @($ExeName, "$ExeName.sig", "SHA256SUMS.txt") } |
    Select-Object Name, Length
Write-Host ""
Write-Host "发布(可选,需 gh 登录):" -ForegroundColor DarkGray
Write-Host "  gh release create <tag> dist\$ExeName dist\$ExeName.sig erfanyo.asc --notes-file RELEASE_NOTES.md"
