# Multi-Cloud Monitoring

可执行的阿里云中心化、WireGuard 跨云采集监控工程。仓库包含配置、安装手册、值班 Runbook 和真实故障案例；运行数据与密钥不进入 Git。

## Current status

| 状态 | 内容 |
| --- | --- |
| DONE | 两台 CentOS 7 安装并验证 WireGuard |
| DONE | `10.250.0.1` 与 `10.250.0.101` 双向通信 |
| DONE | 腾讯测试节点 Node Exporter 仅监听 `10.250.0.101:9100` |
| DONE | 阿里 Prometheus 成功采集 `10.250.0.101:9100`，`up == 1` |
| DONE | `prom/prometheus:v3.13.2` 的 promtool 配置检查 |
| DONE | Prometheus、Grafana Docker Compose 已运行 |
| DONE | Grafana Prometheus datasource provisioning 自动创建成功 |
| DONE | Grafana Explore 查询 `up` 正常，Node Exporter Full 1860 已导入并显示数据 |
| DONE | Dashboard 1860 已完成 Cloud / Env / Job / Host 级联变量优化 |
| IN PROGRESS | 将生产 `host` 从公网 IP 派生命名改为标准资产名称 |
| PLANNED | 全量节点、Dashboard 标准化、告警、Alertmanager、Blackbox、云监控 API、GitOps/CI |

> 仓库中的 Compose 是根据已确认目录和参数整理的部署基线。生产容器链路已运行验证，但当前工作区没有从生产机直接导出的原始 Compose；仍需逐项核对仓库基线与生产文件是否完全一致。

## Architecture

```text
Grafana --localhost:9090--> Prometheus --wg0/TCP 9100--> Tencent Node Exporter
                                      WireGuard outer transport: UDP 51820
```

Prometheus 与 Grafana 使用 host network。Prometheus 因而直接复用宿主机路由 `10.250.0.101 dev wg0`；Grafana可通过 `127.0.0.1:9090` 连接 Prometheus。

## Quick start

不要直接在生产机执行。先阅读部署文档，核对 `/data/docker/monitoring/prometheus/date` 是否已有数据，再同步仓库配置：

```bash
docker compose config

docker run --rm \
  -v /data/docker/monitoring/prometheus:/etc/prometheus:ro,Z \
  --entrypoint /bin/promtool \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml

docker compose up -d
```

## Documentation

- [当前事实与边界](docs/current-state.md)
- [架构](docs/architecture.md)
- [网络设计](docs/network.md)
- [WireGuard 安装](docs/02-wireguard-installation.md)
- [Node Exporter 安装](docs/03-node-exporter-installation.md)
- [监控栈部署](docs/04-monitoring-stack-deployment.md)
- [Prometheus 配置](docs/05-prometheus-configuration.md)
- [Grafana 配置](docs/06-grafana-configuration.md)
- [Operations Runbook](docs/07-operations-runbook.md)
- [Dashboard 优化](docs/08-dashboard-optimization.md)
- [故障案例库](docs/troubleshooting.md)
- [路线图](docs/roadmap.md)
- [架构决策记录](docs/decisions/)

## Repository layout

```text
docker-compose.yml
prometheus/                   Prometheus 配置、targets、规则示例
grafana/                      Grafana 配置与 provisioning
wireguard/examples/           不含真实密钥的两端配置模板
systemd/                      Node Exporter systemd 单元
alertmanager/                 未实施示例
blackbox/                     未实施示例
docs/                         安装、配置、Runbook、事故案例
```

生产运行数据、日志、Grafana SQLite、插件、`.env` 和 WireGuard 密钥均被 `.gitignore` 排除。
