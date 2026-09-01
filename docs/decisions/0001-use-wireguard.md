# ADR 0001：使用 WireGuard 连接跨云监控链路

- 状态：Accepted

## 背景

Prometheus 位于阿里云，需安全采集腾讯云主机指标；Node Exporter 不应直接暴露公网。

## 决策

使用 WireGuard 建立跨云 Overlay 网络，通过隧道地址采集 Node Exporter。

## 原因与影响

该方案暴露面小、链路加密且配置相对直接，但需要维护 Peer、路由、密钥和 UDP 51820 的安全组规则。
