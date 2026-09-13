# 在 WSL 中测试

建议在 WSL 的 Linux 主目录里单独克隆项目，避免 Linux 与 Windows 版 llama.cpp
运行库写入同一个工作区。下面以 Ubuntu 和 WSLg 为例。

## 首次准备

```bash
sudo apt update
sudo apt install -y git python3 python3-venv libegl1 libgl1 libxkbcommon0 libxkbcommon-x11-0 libdbus-1-3 libfontconfig1
cd ~
git clone https://github.com/erfanyo/Agent_Minecraft_Launcher.git amcl-wsl-test
cd amcl-wsl-test
```

如果目录已经存在，进入目录后执行 `git pull` 即可。

## 自动测试

```bash
bash tools/test_wsl.sh
```

看到 `WSL TEST OK` 表示源码加载、编译和完整自动测试都通过。测试数据会写入
`~/.cache/amcl-wsl-test-data`，不会接触 Windows 的 `.minecraft`。

## WSLg 界面测试

```bash
bash tools/test_wsl.sh --gui
```

界面出现后，先测试页面切换、设置保存、版本列表和资源搜索。要测试 Linux 下实际启动
Minecraft，请在 WSL 内另建测试游戏目录并安装 Linux JDK；不要直接选
`/mnt/c/.../.minecraft`，以免把 Windows 与 Linux 的 Java、原生库和实例设置混在一起。

## 验收 CI 生成的 Linux 包

在 GitHub Actions 页面手动运行 `CI`。任务完成后下载
`AgentMinecraftLauncher-linux-x86_64` artifact，把其中的压缩包放进 WSL 主目录，执行：

```bash
mkdir -p ~/amcl-package-test
tar -xzf AgentMinecraftLauncher-linux-x86_64.tar.gz -C ~/amcl-package-test
cd ~/amcl-package-test/AgentMinecraftLauncher
./AgentMinecraftLauncher
```

不要直接在 `/mnt/c` 或 `/mnt/e` 中运行包；Linux 权限、文件监听和读写性能在 Windows
挂载盘上与真实 Linux 不同。缺少 Qt/XCB 运行库时先安装：

```bash
sudo apt update
sudo apt install -y libegl1 libgl1 libxkbcommon0 libxkbcommon-x11-0 libdbus-1-3 libfontconfig1 libxcb-cursor0
```

验收时至少检查首次启动、设置保存、版本列表、Java 下载、原版实例启动，以及关闭后
再次打开。测试数据默认落在解压目录旁；整个 `~/amcl-package-test` 可在测试后删除。
