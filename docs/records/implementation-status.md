# 实施状态快照

更新时间：2026-09-03

本文是根据实施对话整理的状态快照，不替代仓库中的部署手册，也不替代生产主机的实时审计结果。

## 已确认的里程碑

- 阿里监控 Hub、Prometheus、Grafana 和 Grafana datasource provisioning 已可用。
- Jenkins Gateway 的 WireGuard Overlay 已建立；Gateway 使用 `10.250.0.102/32` 与腾讯 VPC 私网地址 `172.18.20.16`。
- Gateway 到腾讯生产网段的路由、精确 FORWARD、SNAT 以及 Prometheus 端到端抓取已经完成验证。
- 阿里监控机与腾讯侧至少两个 Node Exporter target 已被 Prometheus 采集；`up` 查询可区分 UP 与 DOWN。
- Grafana Host 变量基于即时 `up` 查询：仍配置的故障节点会保留在下拉列表，已从 targets 删除的节点不会作为当前资产显示。
- 原点对点验证曾使用 `10.250.0.101:9100`；Gateway 下游节点使用各自腾讯 VPC 私网 `IP:9100`。
- NodeDown 规则已启用并完成演练：停止 Node Exporter 后规则状态经历 `Pending -> Firing`；恢复后在 Prometheus 规则页回到 `Normal`。
- Alertmanager 已部署并被 Prometheus 识别；NodeDown 的 SMTP `FIRING` 与 `RESOLVED` 邮件均已通过受控演练验证。

## 尚未作为完成项归档

- Blackbox Exporter、云厂商指标和全量节点接入尚未完成。
- 邮件内容模板优化、钉钉/Webhook 等额外通知渠道尚未完成。
- Grafana Dashboard JSON 尚未导出为 provisioning 文件。
- Prometheus TSDB 的一致性备份与恢复演练尚未完成。

## 仓库与运行环境待对齐

仓库的 [prometheus/prometheus.yml](../../prometheus/prometheus.yml) 已按实际模型使用 `job_name: node-exporter` 和 `/etc/prometheus/targets/*-node.yml`。真实 target 清单含私网地址与资产名称，因此不进入 Git；仓库只保留 [脱敏模板](../../prometheus/targets/tencent-node.yml.example)。

每次新增或调整节点，都应在监控机修改本地 `*-node.yml`，执行 `promtool check config`，再通过 Prometheus API 与 Grafana 验证；不要把真实 target 文件推送到公共 GitHub 仓库。
