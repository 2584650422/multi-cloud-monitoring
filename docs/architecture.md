# 架构

本项目以阿里云监控 Hub 为中心采集多云 Linux 主机指标。WireGuard 只承载跨云监控流量；Node Exporter 的 TCP/9100 不直接暴露公网。

## 组件与职责

| 组件 | 部署位置 | 职责 |
| --- | --- | --- |
| WireGuard | 宿主机 | 建立跨云加密 Overlay，并提供到腾讯目标的路由 |
| Node Exporter | 被监控主机宿主机 | 暴露 Linux 主机指标 |
| Prometheus | 阿里监控 Hub 的 Docker Compose | 抓取、存储与查询指标 |
| Alertmanager | 阿里监控 Hub 的 Docker Compose | 对告警分组、去重、路由并投递邮件通知 |
| Grafana | 阿里监控 Hub 的 Docker Compose | 展示与查询 Prometheus 数据 |
| WireGuard Gateway | 腾讯 VPC 内指定主机 | 将 WireGuard 监控流量转发到 VPC 下游节点 |

Prometheus、Alertmanager 和 Grafana 使用 `network_mode: host`。Prometheus 因此共享宿主机路由表，直接经 `wg0` 访问跨云 target；Prometheus 与 Alertmanager 分别只监听 `127.0.0.1:9090`、`127.0.0.1:9093`。Grafana 通过 `http://127.0.0.1:9090` 访问 Prometheus。

## 两种采集拓扑

### 点对点

适合少量、分散或无法通过同一 VPC Gateway 覆盖的节点。

```text
Alibaba monitoring Hub                 Tencent node
Prometheus                              Node Exporter
wg0 10.250.0.1 ===== UDP 51820 =====>  wg0 10.250.0.101
                                             └─ 10.250.0.101:9100
```

腾讯节点本身安装 WireGuard，Node Exporter 绑定该节点的 WireGuard 地址。Prometheus target 是 `10.250.0.101:9100`。

### Gateway

适合同一腾讯 VPC 或可由一个 VPC 节点访问的一组主机。

```text
Alibaba monitoring Hub             Tencent VPC Gateway              Downstream node
Prometheus                         wg0 10.250.0.102                 Node Exporter
wg0 10.250.0.1 ===== UDP 51820 ==> eth0 172.18.20.16 === VPC ===>   172.18.0.28:9100
                                     FORWARD + SNAT
```

下游节点不需要 WireGuard，也不分配 `10.250.0.x`。Prometheus target 使用下游节点的 VPC 私网地址；Gateway 仅允许阿里 Hub 到指定节点 TCP/9100 的转发，并将源地址 SNAT 为 Gateway 私网 IP。

## 端口与流量

```text
Prometheus -> TCP/9100 -> wg0 -> WireGuard 加密 -> UDP/51820 Internet
           -> Gateway（仅 Gateway 模式） -> TCP/9100 -> Node Exporter
```

- UDP/51820 是 WireGuard 外层传输端口，安全组需开放 UDP，而不是 TCP。
- TCP/9100 是内部指标端口；点对点模式仅在 WireGuard 地址监听，Gateway 模式仅在节点 VPC 私网地址监听。
- `0.0.0.0:9100` 会监听所有 IPv4 接口，不作为本项目的默认安全策略。

部署细节见 [网络设计](network.md)、[WireGuard 安装](02-wireguard-installation.md)、[Gateway 部署](02-wireguard-gateway.md) 和 [Node Exporter 安装](03-node-exporter-installation.md)。
