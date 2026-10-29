# 整合包杀毒接入核对

核对日期：2026-10-26。当前已编写 Defender 优先、ESET 兜底适配；ESET 参数与结果映射通过模拟测试，尚未在安装 ESET 的机器上实测。本机额外扫描开关仍保持关闭。

## 厂商与能力

| 产品/版本范围 | 已核实入口 | 结果与接入决定 |
| --- | --- | --- |
| Microsoft Defender / Windows | `MpCmdRun.exe -Scan -ScanType 3 -File <原包> -DisableRemediation` | 已接入只检测模式；服务停用、执行失败、超时均不能视为通过。 |
| ESET Endpoint Security 12 | `ecls.exe /clean-mode=none /arch /no-symlink <原包>` | 已编写兜底适配，使用标准安装位置并验证签名，捕获报告保存到原包旁。0 未检出，1 检出并清除，10 部分文件无法扫描，50 检出，100 错误，超过100未扫描。不能把1当作完整无告警通过。尚无实机扫描证据。 |
| Kaspersky Endpoint Security 12.9 / Windows | `avp.com SCAN <原包> /i0 /RA:<日志>` | 官方 SCAN 命令中 `/i0` 为通知，`/RA` 为全部事件报告。仅确认此产品文档，不将企业版参数直接承诺适用于所有个人版；尚未实机验证或接入。 |
| 360 杀毒 | 安装目录的 `360sd.exe` | 官方 FAQ 明确支持由下载工具调用扫描；页面仍有 XP/Windows7 等旧说明，未给出可核实的完整参数、只检测保证与结果协议，暂不自动接入。 |
| 火绒个人版6.0 / Windows | 非官方研究使用 `HipsMain.exe -s <原包>` | 尚未找到官方稳定的命令行结果协议。发现的第三方包装器要求开启自动处理，再轮询内部数据库，不采用这种前提。只能作为待验证的界面唤起线索，进程退出不能证明扫描完成。 |
| ClamAV | `clamscan <原包>`（Windows通常为 `clamscan.exe`） | 官方提供单次扫描工具与病毒库更新工具；不传删除或移动参数。可作为自愿安装后的适配候选，不能因命令存在就承诺大整合包内部完整覆盖。尚未接入，不随启动器捆绑。 |
| 腾讯电脑管家等其他个人版 | 本轮未核实官方稳定的文件扫描命令和结果协议 | 保留手动扫描接续；“未核实”不等于产品不存在此能力。 |

命令示例为参数语义记录，非运行时可复制执行的通用脚本。程序接入时使用已核验的安装路径、发布者签名和参数数组，不执行用户或模型提供的命令字符串。

## 火绒本机核对

只读注册表确认安装目录，存在 `HipsMain.exe`，文件版本为 `6,0,0,1`。没有调用未经本机验证的扫描参数，没有修改病毒处理方式、自动处理或安全防护配置。安装路径属于本机信息，不写入通用源码配置。

第三方 huorong-cli-scanner 的说明明确要求“自动处理”，通过 `log.db-wal` 更新时间和内部表 `HrLogV3_60` 提取最近自定义扫描。这既依赖内部结构，也可能把其他同时发生的扫描混进任务结果；不能直接作为 AMCL 的可靠结果协议。未复制或运行其实现。

火绒企业版资料中的 Linux `hrconsole scan` 与 Windows 个人版不是同一接口，不能混用。

## 下载链路中的呈现

目标流程：完整下载原包 → 归档结构检查 → 本机杀软扫描 → 展示结果 → 用户确认导入。Defender 无法执行或未完成时尝试标准位置的 ESET；Defender 告警不会被后续未检出覆盖。其他厂商仍是调研候选。

网盘原包检查窗口和设置中的手工检查共用此适配。未完成、不可用或用户关闭额外扫描时，显示可永久关闭的信息弹窗；威胁告警不进入可忽略弹窗。隐藏提示不会隐藏页面扫描状态或改变导入拦截。

设置 → 系统 → 启动器维护 → “恢复所有‘不再提示’”，立即恢复杀毒接续说明、内存建议、备份提醒、插件推荐记录。不会开启第三方插件、变更杀毒开关或清除 AI 授权设置。启用自动备份时仍按自动备份策略运行。

- 优先调用用户已安装的杀软，不要求同时安装多款实时防护软件。
- 结果区分未检出、发现告警、未完成、无法取得结果；仅唤起窗口时显示“已交给杀软，等待用户查看结果”。
- 只检测优先，不自动开启杀软的清理模式。系统实时防护仍可能独立隔离文件，不能承诺原包绝不受影响。
- 原包保留；加密归档、大小或嵌套限制、超时与跳过项必须明确显示，不能记作完整通过。
- JAR/脚本仍可能执行恶意代码；杀软未检出不是代码审计，也不能覆盖启动后另外下载的内容。
- 不向多引擎网站自动上传整合包，不自动改变样本提交策略。调用现有杀软仍受其自身设置约束。

## 来源

- [Microsoft Defender 命令行](https://learn.microsoft.com/en-us/defender-endpoint/command-line-arguments-microsoft-defender-antivirus)
- [ESET 官方扫描入口说明](https://support.eset.com/en/kb3417-eset-command-line-scanner-parameters-eclsexe-5x-and-later)、[Endpoint Security 12 参数及退出码](https://help.eset.com/ees/12/en-US/advanced_cmd.html)
- [Kaspersky Endpoint Security 12.9 SCAN](https://support.kaspersky.com/kes-for-windows/12.9/181236)
- [360 杀毒官方旧 FAQ](https://sd.360.cn/faq.html)
- [ClamAV 官方扫描说明](https://docs.clamav.net/manual/Usage/Scanning.html)
- [火绒非官方包装器的作者说明](https://github.com/JerryLinLinLin/huorong-cli-scanner/blob/master/README_en_us.md)（非厂商文档，只作为兼容性线索）
- [火绒企业版使用手册](https://www.huorong.cn/Public/Uploads/uploadfile/files/20240304/huorongzhongduananquanguanlixitongV2.0chanpinshiyongshuoming.pdf)
