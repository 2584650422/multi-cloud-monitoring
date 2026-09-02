# Gateway 试点记录

> 此文件记录实施状态，不是 Gateway 部署步骤。可复用操作见 [WireGuard Gateway 部署](../02-wireguard-gateway.md)。

## 已记录事实

- Gateway 地址规划：Overlay `10.250.0.102/32`，腾讯 VPC 私网 `172.18.20.16`。
- 阿里 Hub 与 Jenkins Gateway 的 WireGuard Overlay 连通已记录为成功。
- Gateway 下游节点采用自身 VPC 私网 `IP:9100` 监听 Node Exporter；`10.250.0.101:9100` 只适用于原点对点测试节点。

## 待完成的端到端验证

生产网段 `172.18.0.0/16` 的 Node Exporter 转发、FORWARD、SNAT 与 Prometheus 抓取尚未作为整体落地结论归档。验证时按以下顺序收集证据：

1. Jenkins：`curl http://TARGET_IP:9100/metrics`，确认 VPC 直连和 Node Exporter 正常。
2. 阿里 Hub：`ip route get TARGET_IP`，确认目标经 `wg0`。
3. Jenkins：检查 `DOCKER-USER` 与 `POSTROUTING` 规则计数。
4. 阿里 Hub：`curl http://TARGET_IP:9100/metrics`。
5. Prometheus：确认 target `up == 1`。

常见遗漏是仅更新阿里 Peer 的 `AllowedIPs` 而没有执行 `ip route replace NET dev wg0`，或只允许 FORWARD 而遗漏 SNAT。实际 Root Cause 与 Resolution 必须以抓包、路由和规则计数证据补充，不能预先写成故障结论。
