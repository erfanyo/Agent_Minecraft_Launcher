# 陶瓦公共节点

陶瓦 0.4.2 的 HTTP IPC 支持创建、加入时通过重复的 `public_nodes` 查询参数传入额外 EasyTier 节点。AMCL 的陶瓦页面单独保存 `terracotta_public_nodes`，不复用独立 EasyTier 页面的配置。原版陶瓦会追加自身默认节点，并不会替换它们。

## 2026-10-12 探测

Windows WiFi，使用陶瓦释放的 EasyTier v2.5.0-terracotta.2，独立随机网络、无 TUN，每个候选探测 25 秒。

| 地址 | 结果 |
| --- | --- |
| tcp://us01.225284.xyz:11010 | 完成握手，记录 new peer connection added / new peer added |
| tcp://dreamlife.indevs.in:11010 | 完成握手，记录 new peer connection added / new peer added |
| tcp://et-hk.clickor.click:11010 | 超时，暂不作为预设 |

此结果只证明当前网络下单端可接入节点，不保证跨端发现、打洞、中继或游戏连接成功。房主和访客应选择同一组节点；已有大厅需退出并重新创建或加入才能应用新配置。

来源：
- 美国、香港运营者发布：https://github.com/orgs/EasyTier/discussions/1848
- 上海运营者：https://easytier.dreamlife.indevs.in/
- IPC 实现：https://github.com/burningtnt/Terracotta/blob/v0.4.2/src/server/states.rs
- 原有节点追加逻辑：https://github.com/burningtnt/Terracotta/blob/v0.4.2/src/easytier/publics.rs

公共节点由第三方运营，可用性可能变化；后续维护应重新握手验证，不能仅凭网页“在线”状态判断。
