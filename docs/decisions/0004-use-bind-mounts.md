# ADR 0004：使用 bind mount

- 状态：Accepted，路径待核实

## 决策

Compose 服务使用 bind mount，使宿主机上的配置和持久化数据路径可见、可审计。

## 影响

宿主机目录权限、SELinux 标签和备份策略需显式管理。生产根目录计划为 `/data/docker/monitoring/`；Prometheus 数据子目录究竟是 `data/` 还是现存的 `date/`，必须先在生产机核实，不能自动改动。
