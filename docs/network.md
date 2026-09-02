# 网络设计

## 地址与端口规划

以下是本项目的 Overlay 与 Gateway 地址规划。每个 WireGuard Peer 使用一个 `/32`；它们不是所有腾讯业务节点的新地址。

| 用途 | 地址或端口 | 说明 |
| --- | --- | --- |
| 阿里监控 Hub WireGuard | `10.250.0.1/32` | Prometheus 所在端的 Overlay 地址 |
| 腾讯点对点测试 Peer | `10.250.0.101/32` | 点对点测试节点的 Overlay 地址 |
| 腾讯 Gateway | `10.250.0.102/32` | Gateway 的 Overlay 地址 |
| Gateway VPC 地址 | `172.18.20.16` | Gateway 转发与 SNAT 使用的私网地址 |
| WireGuard 外层传输 | UDP/51820 | 公网安全组开放此 UDP 端口 |
| Node Exporter | TCP/9100 | 仅在 Overlay 或 VPC 私网中提供指标 |

例如，`10.250.0.101 dev wg0` 的 `dev` 是 Linux 的 network device，表示流量从 `wg0` 接口发送，不表示开发环境。

## 流量路径

```text
Prometheus
  -> TCP/9100
  -> wg0
  -> WireGuard encryption
  -> UDP/51820 over Internet
  -> WireGuard decryption
  -> 点对点 Node Exporter，或 Gateway -> VPC Node Exporter
```

UDP/51820 与 TCP/9100 是不同层的端口。仅开放 TCP/51820 不能建立 WireGuard handshake；也不应开放公网 TCP/9100 来绕过路由、FORWARD 或 SNAT 问题。

## Node Exporter 监听边界

| 模式 | 监听地址 | 原因 |
| --- | --- | --- |
| 点对点 | WireGuard 地址，如 `10.250.0.101:9100` | 节点自身是 Peer，指标仅通过 Overlay 提供 |
| Gateway | 节点 VPC 私网地址，如 `172.18.0.28:9100` | 下游节点没有 wg0，由 Gateway 访问与转发 |
| 不采用 | `127.0.0.1:9100` | 仅本机可访问，Gateway 和 Prometheus 均无法抓取 |
| 不采用 | `0.0.0.0:9100` | 所有 IPv4 接口监听，扩大暴露面 |

Gateway 模式下，腾讯安全组和主机防火墙只允许 Gateway VPC 地址（例如 `172.18.20.16/32`）到下游节点 TCP/9100。

## 路由、热加载与冷启动

点对点 target 的路由通常是精确主机路由：

```text
10.250.0.101 dev wg0
```

Gateway 模式新增下游网段时，阿里 Hub 上 Jenkins Peer 的 `AllowedIPs` 需包含该网段。热加载 Peer 配置后还必须补路由：

```bash
wg syncconf wg0 <(wg-quick strip wg0)
ip route replace 172.18.0.0/16 dev wg0
ip route get 172.18.0.28
```

`wg syncconf` 会更新 WireGuard Peer 参数，但不会执行 `wg-quick` 创建路由的脚本。只有接口不存在、地址或 ListenPort 需要重建时，才在维护窗口用 `wg-quick down wg0` 和 `wg-quick up wg0` 冷启动。

## 容器网络

Prometheus 容器使用 host network 后与宿主机共享路由表，因此跨云 target 会命中宿主机 `wg0`。若使用 Docker bridge，则需额外维护容器 namespace 路由、NAT、FORWARD 和 Docker iptables；这与本项目直接复用宿主机 WireGuard 路由的目标不符。
