# Multi-Cloud Monitoring

一个可复现的多云基础设施监控工程：阿里云监控中心运行 Prometheus 与 Grafana；腾讯云节点通过 WireGuard 点对点连接或 VPC 内 WireGuard Gateway 暴露 Node Exporter 指标。仓库保存配置即代码、部署手册、运维 Runbook 和已解决故障案例；密钥与运行数据不进入 Git。

## 适用架构

```text
                         +-- 点对点：WireGuard Peer -> Node Exporter
Alibaba monitoring hub --+
                         +-- Gateway：WireGuard -> VPC Gateway -> Node Exporter
```

- 点对点模式适合少量独立节点：Node Exporter 监听该节点的 WireGuard 地址。
- Gateway 模式适合同一腾讯 VPC 可达的一组节点：只有 Gateway 安装 WireGuard；下游 Node Exporter 监听各自 VPC 私网地址。
- Prometheus 和 Grafana 通过 Docker Compose 使用宿主机网络，Prometheus 直接复用宿主机的 WireGuard 路由。

## 部署顺序

1. 按 [WireGuard 安装](docs/02-wireguard-installation.md) 建立点对点隧道，或按 [WireGuard Gateway 部署](docs/02-wireguard-gateway.md) 建立网关路径。
2. 按 [Node Exporter 安装](docs/03-node-exporter-installation.md) 安装 exporter，并依据所选网络模式绑定正确监听地址。
3. 按 [监控栈部署](docs/04-monitoring-stack-deployment.md) 创建目录、权限并部署 Compose。
4. 按 [Prometheus 配置](docs/05-prometheus-configuration.md) 增加 target、检查配置、reload 并验证 `up`。
5. 按 [Grafana 配置](docs/06-grafana-configuration.md) 验证 datasource provisioning 和 Dashboard。

## 文档

### 部署与配置

- [架构](docs/architecture.md)
- [网络设计](docs/network.md)
- [WireGuard 安装（CentOS 7）](docs/02-wireguard-installation.md)
- [WireGuard Gateway 部署](docs/02-wireguard-gateway.md)
- [Node Exporter 安装](docs/03-node-exporter-installation.md)
- [监控栈部署](docs/04-monitoring-stack-deployment.md)
- [Prometheus 配置](docs/05-prometheus-configuration.md)
- [Grafana 配置](docs/06-grafana-configuration.md)

### 运行与维护

- [Operations Runbook](docs/07-operations-runbook.md)
- [故障案例库](docs/troubleshooting.md)
- [路线图](docs/roadmap.md)
- [架构决策记录](docs/decisions/)

### 实施记录（不作为部署步骤）

- [记录说明](docs/records/README.md)
- [当前实施状态](docs/records/implementation-status.md)
- [Gateway 试点记录](docs/records/gateway-pilot.md)
- [Dashboard 1860 优化记录](docs/records/dashboard-1860-optimization.md)

## 使用前检查

不要直接用仓库配置覆盖运行中的生产目录。先确认生产数据目录、镜像版本、端口占用、SELinux 状态和现有 WireGuard 配置；随后执行：

```bash
docker compose config

docker run --rm \
  -v /data/docker/monitoring/prometheus:/etc/prometheus:ro,Z \
  --entrypoint /bin/promtool \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml
```

## 仓库结构

```text
docker-compose.yml
prometheus/                   Prometheus 主配置、targets、规则示例
grafana/                      Grafana 配置与 provisioning
wireguard/examples/           不含真实密钥的 WireGuard 模板
systemd/                      点对点 Node Exporter systemd 单元
docs/                         部署、配置、Runbook、故障案例
docs/records/                 实施过程与实时状态记录
```

生产运行数据、日志、Grafana SQLite、插件、`.env` 和 WireGuard 私钥均由 `.gitignore` 排除。
