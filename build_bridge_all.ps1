# build_bridge_all.ps1 — 把 bridge-mod 全部支持版本统一编译为 0.2.0,并收进 bridge-mod/dist。
#
# 背景/踩坑:
# - 每个变体的 Gradle/JDK 要求都不同(见下表),不能混用:
#     fabric  -> Loom 1.6.11,必须 Gradle 8.10.x(Loom 1.6 与 Gradle 8.13 的 Problems API 不兼容)
#     forge   -> ForgeGradle 6,Gradle 8.10.x + JDK 17
#     1.18.2/1.19.2 -> ForgeGradle 5.1,Gradle 7.6.4 + JDK 17
#     1.16.5  -> ForgeGradle 5.1,Gradle 7.6.4 运行于 JDK 17,编译任务使用 JDK 8
#     1.12.2  -> ForgeGradle 2.3,Gradle 4.10.3 + JDK 8
#     neoforge-> ModDevGradle 2.0.91,Gradle 8.13 + JDK 21
# - 必须 clean 编译:共享源码(bridge-mod/common)改动后,增量编译可能判定 UP-TO-DATE,
#   于是产出的 jar 里还是旧 class(实测 1.18.2 就踩到了,jar 里没有 socket 修复)。
#
# 用法:
#   pwsh -File build_bridge_all.ps1                 # 全部
#   pwsh -File build_bridge_all.ps1 -Only forge-1.18.2,forge-1.19.2
param([string[]]$Only = @())

# -File 传参时逗号不会在 shell 层拆分,这里自己拆一次(支持 -Only a,b 或 -Only a b)
$Only = @($Only | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$ErrorActionPreference = 'Continue'
$Root  = Split-Path -Parent $MyInvocation.MyCommand.Path
$BM    = Join-Path $Root 'bridge-mod'
$Dist  = Join-Path $BM 'dist'
$LogDir = Join-Path $Root '.tmp\bridge-build-logs'
$GDir  = Join-Path $Root '.tmp\gradle-dist'
$JDK8  = 'C:\Program Files\Eclipse Adoptium\jdk-8.0.504.1-hotspot'
$JDK17 = Join-Path $Root '.tmp\jdk\jdk-17.0.20.1+1'
$JDK21 = Join-Path $Root '.tmp\jdk\jdk-21.0.12.1+1'

$V = [ordered]@{}
$V['fabric-1.20.1'] = @{ proj = $BM; gradle = '8.10.2'; jdk = $JDK17; mcEnv = '1.20.1';
                         tasks = @(':fabric:clean', ':fabric:build');
                         src = "$BM\fabric\build\libs\fabric-0.2.0.jar";
                         out = 'agentmc-bridge-fabric-1.20.1-0.2.0.jar' }
$V['fabric-1.21.1'] = @{ proj = $BM; gradle = '8.10.2'; jdk = $JDK21; mcEnv = '1.21.1';
                         tasks = @(':fabric:clean', ':fabric:build');
                         src = "$BM\fabric\build\libs\fabric-0.2.0.jar";
                         out = 'agentmc-bridge-fabric-1.21.1-0.2.0.jar' }
$V['forge-1.20.1'] = @{ proj = $BM; gradle = '8.10.2'; jdk = $JDK17; mcEnv = '1.20.1';
                        tasks = @(':forge:clean', ':forge:build');
                        src = "$BM\forge\build\libs\agentmc-bridge-forge-1.20.1-0.2.0.jar";
                        out = 'agentmc-bridge-forge-1.20.1-0.2.0.jar' }
$V['forge-1.18.2'] = @{ proj = "$BM\forge-1.18.2"; gradle = '7.6.4'; jdk = $JDK17; mcEnv = '';
                        tasks = @('clean', 'build');
                        src = "$BM\forge-1.18.2\build\libs\agentmc-bridge-forge-1.18.2-0.2.0.jar";
                        out = 'agentmc-bridge-forge-1.18.2-0.2.0.jar' }
$V['forge-1.19.2'] = @{ proj = "$BM\forge-1.19.2"; gradle = '7.6.4'; jdk = $JDK17; mcEnv = '';
                        tasks = @('clean', 'build');
                        src = "$BM\forge-1.19.2\build\libs\agentmc-bridge-forge-1.19.2-0.2.0.jar";
                        out = 'agentmc-bridge-forge-1.19.2-0.2.0.jar' }
$V['forge-1.16.5'] = @{ proj = "$BM\forge-1.16.5"; gradle = '7.6.4'; jdk = $JDK17; mcEnv = '';
                        tasks = @('clean', 'build');
                        src = "$BM\forge-1.16.5\build\libs\agentmc-bridge-forge-1.16.5-0.2.0.jar";
                        out = 'agentmc-bridge-forge-1.16.5-0.2.0.jar' }
$V['forge-1.12.2'] = @{ proj = "$BM\forge-1.12.2"; gradle = '4.10.3'; jdk = $JDK8; mcEnv = '';
                        tasks = @('clean', 'build');
                        src = "$BM\forge-1.12.2\build\libs\agentmc-bridge-forge-1.12.2-0.2.0.jar";
                        out = 'agentmc-bridge-forge-1.12.2-0.2.0.jar' }
$V['neoforge-1.21.1'] = @{ proj = "$BM\neoforge"; gradle = '8.13'; jdk = $JDK21; mcEnv = '1.21.1';
                           tasks = @('clean', 'build');
                           src = "$BM\neoforge\build\libs\agentmc-bridge-neoforge-1.21.1-0.2.0.jar";
                           out = 'agentmc-bridge-neoforge-1.21.1-0.2.0.jar' }

if (-not (Test-Path $Dist)) { New-Item -ItemType Directory -Path $Dist | Out-Null }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$okList = @()
$failList = @()
foreach ($name in $V.Keys) {
    if ($Only.Count -gt 0 -and ($Only -notcontains $name)) { continue }
    $c = $V[$name]
    Write-Host ""
    Write-Host "==================== $name ===================="
    $env:JAVA_HOME = $c['jdk']
    $env:PATH = "$($c['jdk'])\bin;$env:PATH"
    if ($c['mcEnv']) { $env:BRIDGE_MC_VERSION = $c['mcEnv'] }
    else { Remove-Item env:BRIDGE_MC_VERSION -ErrorAction SilentlyContinue }
    $gradle = Join-Path $GDir "gradle-$($c['gradle'])\bin\gradle.bat"
    if (-not (Test-Path $gradle)) { Write-Host "!! missing gradle $gradle"; $failList += $name; continue }
    $extra = @()
    if ($c.ContainsKey('extra')) { $extra = @($c['extra']) }
    $log = Join-Path $LogDir "$name.log"
    & $gradle -p $c['proj'] @($c['tasks']) @extra -x test --console=plain --no-daemon 2>&1 |
        Tee-Object -FilePath $log |
        Select-String -Pattern 'BUILD SUCCESSFUL|BUILD FAILED|What went wrong|error:|错误:|cannot find symbol|����' |
        Select-Object -Last 12 | ForEach-Object { Write-Host "   $_" }
    $buildExit = $LASTEXITCODE
    if ($buildExit -eq 0 -and (Test-Path $c['src'])) {
        Copy-Item $c['src'] (Join-Path $Dist $c['out']) -Force
        Write-Host "   => dist\$($c['out'])  ($((Get-Item $c['src']).Length) bytes)"
        $okList += $name
    } else {
        Write-Host "   !! 构建未完成(退出码 $buildExit),日志: $log"
        $failList += $name
    }
}

Write-Host ""
Write-Host "==================== 汇总 ===================="
Write-Host "成功 ($($okList.Count)): $($okList -join ', ')"
Write-Host "失败 ($($failList.Count)): $($failList -join ', ')"
if ($failList.Count -gt 0) { exit 1 }
