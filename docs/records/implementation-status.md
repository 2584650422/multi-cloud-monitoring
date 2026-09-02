# 已验证现状

更新时间：2026-09-02

本文只记录对话中明确执行并验证成功的事实，不代表当前生产机的实时审计结果。

## 环境

- 阿里云北京：监控中心位于单一 VPC，监控机私网地址为 `172.16.90.17`。
- 腾讯云北京：服务器分布在多个 VPC；当前仅验证一台测试机 `172.18.0.6`。
- 两台测试相关主机均为 CentOS 7。

## 已验证

1. 两端 WireGuard 已安装并建立连接。
2. Overlay 地址为阿里端 `10.250.0.1`、腾讯测试端 `10.250.0.101`。
3. 两端 Overlay 地址双向 Ping 正常。
4. WireGuard 外层传输使用 UDP 51820。
5. 腾讯测试机上的 Node Exporter `1.11.1` 可通过隧道地址 `10.250.0.101:9100` 访问，未直接对公网开放 9100。
6. Prometheus 已采集该 Target，`up == 1`。
7. `prom/prometheus:v3.13.2` 镜像已成功拉取。
8. 主配置 `/etc/prometheus/prometheus.yml` 已通过 `promtool check config`。
9. 曾因主配置副本误放进 `rules/` 导致规则校验失败，原因已定位。
10. Prometheus 与 Grafana Compose 已运行，Grafana 可以登录。
11. Prometheus datasource 已通过 Grafana provisioning 自动创建。
12. Grafana Explore 查询 `up` 正常。
13. Node Exporter Full Dashboard 1860 已导入并正常显示。
14. Dashboard 已建立 `Cloud -> Env -> Job -> Host` 级联变量。
15. 隐藏变量 `node` 已把所选 Host 映射回 `10.250.0.101:9100`，原 1860 Panel 恢复数据。

## Gateway 最新进度

- Jenkins Gateway 试点地址规划为 Overlay `10.250.0.102/32`、腾讯 VPC 私网 `172.18.20.16`。
- 阿里 Hub ↔ Jenkins 的 WireGuard 隧道已按对话记录建立并完成 Overlay 连通验证。
- 生产网段 `172.18.0.0/16` 的转发、FORWARD、SNAT 和生产 Node Exporter 采集尚未完成端到端验证。
- Gateway 模式下已明确：生产节点 Node Exporter 应监听各自 VPC 私网 `IP:9100`；`10.250.0.101:9100` 仅代表已验证的点对点测试模式。
- 尚未对生产安全组、iptables 或 Node Exporter 执行变更；仓库只保存脱敏模板和试点步骤。

## 已纳入仓库但尚未生产验证

- 根据已确认参数整理的 `docker-compose.yml` 基线。
- Prometheus 主配置、腾讯测试 target 与 Grafana datasource provisioning 基线。
- WireGuard 无密钥配置模板与 Node Exporter systemd 单元。

这些文件是可审阅、可验证的工程输入，不代表已经在生产容器中运行。

## 尚未验证

- 当前生产机上的原始 `docker-compose.yml` 与仓库基线是否完全一致。
- Prometheus、Grafana 容器是否已正式启动并稳定运行。
- 生产 Prometheus 当前返回的 `host` 仍由腾讯公网 IP 派生；为避免在 Git 中保存公网地址，此处不记录原值。需改为稳定资产名称。
- Grafana 持久化恢复是否已验证。
- Prometheus 数据目录实际使用 `data/` 还是误写的 `date/`。
- 其余阿里云、腾讯云服务器是否已接入。
- Alertmanager、Blackbox Exporter 和云厂商指标采集。

以上内容在获得生产机文件或执行结果前，均不得标记为 DONE。
