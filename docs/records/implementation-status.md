# 实施状态快照

更新时间：2026-09-11

本文是根据实施对话整理的状态快照，不替代仓库中的部署手册，也不替代生产主机的实时审计结果。

## 已确认的里程碑

- 阿里监控 Hub、Prometheus、Grafana 和 Grafana datasource provisioning 已可用。
- Jenkins Gateway 的 WireGuard Overlay 已建立；Gateway 使用 `10.250.0.102/32` 与腾讯 VPC 私网地址 `172.18.20.16`。
- Gateway 到腾讯生产网段的路由、基于 `wg-monitor-targets` ipset 的 FORWARD/SNAT 公共规则以及 Prometheus 端到端抓取已经完成验证。
- Gateway 持久化已配置：`wg-quick@wg0` 已 enable，`ip_forward` 有独立 sysctl 配置，`wg-monitor-gateway` systemd 服务负责从准入清单原子恢复 ipset 与三条公共规则。该服务已在当前运行态启动，既有采集链路保持正常；oneshot 服务显示 `active (exited)` 属于预期状态。
- 当前纳管的 Node Exporter target 已完成接入并由 Prometheus 采集；`up` 查询可区分 UP 与 DOWN。
- Grafana Host 变量基于即时 `up` 查询：仍配置的故障节点会保留在下拉列表，已从 targets 删除的节点不会作为当前资产显示。
- 原点对点验证曾使用 `10.250.0.101:9100`；Gateway 下游节点使用各自腾讯 VPC 私网 `IP:9100`。
- NodeDown 规则已启用并完成演练：停止 Node Exporter 后规则状态经历 `Pending -> Firing`；恢复后在 Prometheus 规则页回到 `Normal`。规则已重构为通用邮件 annotations（`summary`、`metric_name`、`current_value`、`condition`），移除冗余 `description`。
- 磁盘告警已完成正式验证并重构：两级规则统一为 `DiskSpaceUsageHigh`，以 `severity=warning|critical` 区分；默认阈值为 80% / 90%，两组特殊主机分别为 90% / 95% 与 95% / 98%，持续时间分别为 10m / 5m。规则保持 Warning、Critical 各一条，通过 `label_replace()` 为命中分支添加实际 `threshold`，不再使用 `policy` 标签或六规则拆分。
- Alertmanager 的磁盘 `inhibit_rules` 已验证：同一 `alertname`、`host`、`mountpoint` 的 Critical 会抑制 Warning 通知；Critical 恢复且 Warning 仍 Firing 时，Warning 可解除抑制并单独通知。由于 `group_by` 不含 severity，降级邮件可同时展示 Warning Firing 与 Critical Resolved，属预期行为。
- Alertmanager 已部署并被 Prometheus 识别；NodeDown 与 DiskSpaceUsageHigh 的 SMTP `FIRING` / `RESOLVED` 邮件链路已通过受控演练验证。规则页面变化后约 1～2 分钟收到邮件，是 evaluation、`for`、`group_wait`、`group_interval` 共同造成的预期等待，不是网络异常。
- 中文 HTML 模板已重构并完成实测：FIRING / RESOLVED 共用单条告警布局，按告警、实例、时间、技术信息分区展示；`public_ip` 缺失时显示“无”。邮件时间的东八区展示使用 `tz "Asia/Shanghai"` + `date` 显式转换；Compose 中 Prometheus、Alertmanager、Grafana 均保留 `/etc/localtime:/etc/localtime:ro`，两者分别解决模板展示层和容器运行环境层的时区问题。
- MemoryUsageHigh 已新增：使用 `MemAvailable / MemTotal` 计算实际可用内存后的使用率，Warning 为 >85% 持续 10m，Critical 为 >95% 持续 5m；规则与邮件数据契约已落库。端到端触发、抑制与恢复邮件演练尚未在本快照记录。

## 尚未作为完成项归档

- Blackbox Exporter、云厂商指标和全量节点接入尚未完成。
- 钉钉/Webhook、CPU 等额外规则尚未完成；内存规则已配置，待补充端到端演练记录。
- Grafana Dashboard JSON 尚未导出为 provisioning 文件。
- Prometheus TSDB 的一致性备份与恢复演练尚未完成。
- Gateway 自动恢复重启演练尚未完成；当前状态为 `CONFIGURED / PENDING REBOOT VALIDATION`，不得标记为 DONE。

## 仓库与运行环境待对齐

仓库的 [prometheus/prometheus.yml](../../prometheus/prometheus.yml) 已按实际模型使用 `job_name: node-exporter` 和 `/etc/prometheus/targets/*-node.yml`。真实 target 清单含私网地址与资产名称，因此不进入 Git；仓库只保留 [脱敏模板](../../prometheus/targets/tencent-node.yml.example)。

每次新增或调整节点，都应在监控机修改本地 `*-node.yml`，执行 `promtool check config`，再通过 Prometheus API 与 Grafana 验证；不要把真实 target 文件推送到公共 GitHub 仓库。
