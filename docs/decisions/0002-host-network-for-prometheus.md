# ADR 0002：Prometheus 容器使用 host network

- 状态：Accepted，尚待容器运行验证

## 背景

宿主机已有 `wg0` 及通往 WireGuard Overlay 的路由。

## 决策

计划让 Prometheus 容器使用 host network，直接复用宿主机网络栈和 `wg0` 路由。

## 原因与影响

这样可减少额外的 Docker NAT、转发与路由配置。代价是网络隔离降低，服务端口直接占用宿主机端口。
