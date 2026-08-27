# -*- coding: utf-8 -*-
<#
Agent Minecraft Launcher 一键发布脚本:打包 + GPG 签名。
用法(在项目根):
    .\build_release.ps1                    # 打包 + 签名
    .\build_release.ps1 -NoSign            # 只打包不签名
    .\build_release.ps1 -GpgExe "C:\...\gpg.exe"   # 指定 gpg 路径

流程:
  1) PyInstaller 按 AgentMinecraftLauncher.spec 打包 → dist\AgentMinecraftLauncher.exe
  2) 用你的 GPG 密钥对 exe 做 detached 装甲签名 → dist\AgentMinecraftLauncher.exe.sig
  3) 生成 SHA256 校验码 + 打印公钥指纹(供 RELEASE_NOTES / README 记录)

前提:
  - 已生成 ed25519 密钥(身份 erfanyo / 29330387076@qq.com)
  - gpg 在 PATH 或通过 -GpgExe 指定(注:Git 自带 gpg 不完整,建议用独立 GnuPG 2.5.x)
#>
[CmdletBinding()]
param(
    [string]$GpgExe = "",                 # 覆盖 gpg 路径;留空则从 PATH 找
    [switch]$NoSign,                      # 跳过签名(仅打包)
    [string]$KeyId = "erfanyo"            # 用于签名的密钥 id/uid
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ExeName = "AgentMinecraftLauncher.exe"

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

# ---- 2) 打包 ----
Write-Host "==> 1/3 PyInstaller 打包 (spec) ==" -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean AgentMinecraftLauncher.spec
if ($LASTEXITCODE -ne 0) { throw "打包失败" }
$exe = Join-Path $Root "dist\$ExeName"
if (-not (Test-Path $exe)) { throw "未找到产物: $exe" }
Write-Host "  产物: $exe" -ForegroundColor Green

# ---- 3) 签名(可跳过) ----
if ($NoSign) {
    Write-Host "==> 已跳过签名 (-NoSign)" -ForegroundColor Yellow
} else {
    Write-Host "==> 2/3 GPG 签名 ==" -ForegroundColor Cyan
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

# ---- 4) SHA256 校验码 ----
Write-Host "==> 3/3 SHA256 ==" -ForegroundColor Cyan
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash
Write-Host "  SHA256: $hash" -ForegroundColor Green
Write-Host ""
Write-Host "======== 发布清单 (dist\ 下) ========" -ForegroundColor Cyan
Get-ChildItem "$Root\dist" -Filter "$ExeName*" | Select-Object Name, Length
Write-Host ""
Write-Host "发布(可选,需 gh 登录):" -ForegroundColor DarkGray
Write-Host "  gh release create <tag> dist\$ExeName dist\$ExeName.sig erfanyo.asc --notes-file RELEASE_NOTES.md"
