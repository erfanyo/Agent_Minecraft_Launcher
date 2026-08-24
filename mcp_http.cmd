@echo off
rem AMCL MCP 服务(HTTP 传输)—— 双击运行,客户端用 http://127.0.0.1:8766/mcp 连接
chcp 65001 >nul
echo.
echo 正在启动 AMCL MCP(HTTP)...
echo 地址: http://127.0.0.1:8766/mcp
echo 在 MCP 客户端选 http 并填入上面地址;按 Ctrl+C 停止。
echo.
"E:\Agent_Minecraft_Launcher 0.0.1\.venv\Scripts\python.exe" "E:\Agent_Minecraft_Launcher 0.0.1\main.py" --mcp-http 8766
pause
