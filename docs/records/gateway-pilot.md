# Gateway 试点记录

> 此文件记录实施结果，不是 Gateway 部署步骤。可复用操作见 [WireGuard Gateway 部署](../02-wireguard-gateway.md)。

## 已完成验证

- Gateway 地址：Overlay `10.250.0.102/32`，腾讯 VPC 私网 `172.18.20.16`。
- 阿里 Hub 与 Jenkins Gateway 的 WireGuard Overlay 连通正常。
- 阿里 Hub 到腾讯生产网段的路由、Jenkins 基于 `wg-monitor-targets` ipset 的 `DOCKER-USER` FORWARD 公共规则和 SNAT 已完成端到端验证。
- Jenkins 已配置 `wg-monitor-gateway` 持久化服务：从 `/etc/wireguard/wg-monitor-targets.list` 原子恢复 ipset，并确保三条公共规则不重复添加。
- Prometheus 已经经 Gateway 成功采集至少两个腾讯侧 Node Exporter 私网 target。
- 下游 Node Exporter 监听各自 VPC 私网 `IP:9100`；`10.250.0.101:9100` 仅属于早期点对点测试路径。

## 继续扩展时的固定验证顺序

每增加一台下游节点，都按以下顺序留存证据：

1. Jenkins：`curl http://TARGET_IP:9100/metrics`，确认 VPC 直连和 Node Exporter 正常。
2. 阿里 Hub：`ip route get TARGET_IP`，确认目标经 `wg0`。
3. Jenkins：确认目标 IP 属于 `wg-monitor-targets`，并确认公共 `DOCKER-USER` 与 `POSTROUTING` 规则存在且计数增长。
4. 阿里 Hub：`curl http://TARGET_IP:9100/metrics`。
5. Prometheus：确认 target `up == 1`；Grafana 中确认该 Host 可选且指标可见。

新增网段时，除更新阿里 Peer 的 `AllowedIPs` 外，还必须执行 `ip route replace NET dev wg0`；热加载 `wg syncconf` 不会自动创建该路由。

## 待补充的运行事实

- 当前已采集两台节点的脱敏 target 文件与标签清单。
- Jenkins 重启后的 WireGuard、ipset、iptables/SNAT 自动恢复演练（持久化已配置，待维护窗口验证）。
- 批量接入更多节点前的变更模板与回滚记录。
