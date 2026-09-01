# 网络设计

## 已验证地址与端口

| 用途 | 地址或端口 | 状态 |
| --- | --- | --- |
| 阿里端 WireGuard | `10.250.0.1` | DONE |
| 腾讯测试端 WireGuard | `10.250.0.101` | DONE |
| WireGuard 外层传输 | UDP 51820 | DONE |
| Node Exporter 隧道内服务 | TCP 9100 | DONE |

UDP 51820 是公网之间的加密隧道传输端口；TCP 9100 是隧道内部的指标服务端口，两者不可混淆。

```text
Prometheus
  -> TCP 9100
  -> wg0
  -> WireGuard encryption
  -> UDP 51820 over Internet
  -> WireGuard decryption
  -> TCP 9100
  -> Node Exporter
```

Node Exporter 的 9100 端口不直接暴露公网。未来其他 VPC 采用逐节点接入还是网关模式，目前仍为 PLANNED。

## 路由与 host network

阿里监控端应看到精确主机路由：

```text
10.250.0.101 dev wg0
```

Prometheus 容器使用 host network 后与宿主机共享路由表，因此请求 `10.250.0.101:9100` 会交给 `wg0`。如果改为 Docker bridge，需要额外验证容器 namespace 的路由、FORWARD、NAT 和 Docker iptables，复杂度与故障面更大。
