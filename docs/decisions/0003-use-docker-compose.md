# ADR 0003：使用 Docker Compose 管理监控服务

- 状态：Accepted，迁移进行中

## 决策

WireGuard 与 Node Exporter 保持宿主机部署；Prometheus、Grafana 以及后续服务计划由 Docker Compose 管理。

## 影响

配置和运行数据需要明确分离；容器启动、持久化与恢复验证的执行事实记录在 `docs/records/`，不写入本 ADR。
