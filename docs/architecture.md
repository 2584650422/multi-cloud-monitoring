# 当前架构

## 目标

以阿里云监控机作为中心，通过 WireGuard 加密隧道采集腾讯云主机指标，避免直接向公网暴露 Node Exporter。

## 已验证架构

```text
Alibaba Cloud                         Tencent Cloud

Prometheus                            Test host
172.16.90.17                          172.18.0.6
     |                                     |
     | wg0: 10.250.0.1                     | wg0: 10.250.0.101
     +========= WireGuard UDP 51820 =======+
                                           |
                                           +-- Node Exporter TCP 9100
```

数据方向：

```text
Prometheus -> wg0 -> WireGuard -> 10.250.0.101:9100 -> Node Exporter
```

## 组件职责

- WireGuard：提供跨云加密 Overlay 网络。
- Node Exporter：导出腾讯测试主机的 Linux 系统指标。
- Prometheus：主动抓取并存储指标。

## 容器化迁移设计（IN PROGRESS）

```text
Host network namespace

Grafana :3000
    |
    | http://127.0.0.1:9090
    v
Prometheus :9090
    |
    | route: 10.250.0.101 dev wg0
    v
WireGuard -> Node Exporter :9100
```

Prometheus 使用 host network 是为了直接复用宿主机 `wg0` 路由，避免在 Docker bridge 中额外维护 NAT、FORWARD 和路由。Grafana 同样使用 host network，才能用 loopback 访问只监听 `127.0.0.1:9090` 的 Prometheus。代价是端口直接占用宿主机且网络隔离降低。

## 当前边界

Prometheus/Grafana Compose、datasource provisioning、Explore 查询和 Dashboard 1860 已验证。Dashboard 标签与变量标准化正在实施；告警系统、探测系统和云厂商 API 仍为 PLANNED。
