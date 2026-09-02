# WireGuard Gateway 部署

本文是腾讯 VPC 内 WireGuard Gateway 的部署手册。适用于一台 Gateway 能通过腾讯私网访问多个下游 Node Exporter 的场景；它不改变下游业务节点默认路由，也不把隧道扩展成通用生产 VPN。

## 目标与地址

```text
Alibaba Prometheus / Hub       Jenkins Gateway              Tencent VPC
172.16.90.17                   172.18.20.16                172.18.0.0/16
wg0 10.250.0.1  <==== UDP ===> wg0 10.250.0.102  ----->  node:9100
```

- `10.250.0.1/32`：阿里监控 Hub。
- `10.250.0.102/32`：Jenkins Gateway 的 Overlay 地址。
- `172.18.20.16`：Gateway 的腾讯 VPC 私网地址，用于出站和 SNAT。
- `172.18.0.0/16`：腾讯生产网段示例；首次变更仅接一台已批准节点。

Gateway 不成为腾讯生产网默认出口，只转发阿里到 Node Exporter 的 TCP/9100。

## Gateway 模式下 Node Exporter 监听地址

点对点测试时，腾讯节点本身是 WireGuard Peer，所以使用 `10.250.0.101:9100` 监听是正确的。切换到 Gateway 后，下游生产节点通常不安装 WireGuard；它们仍使用原有腾讯 VPC 私网地址，例如 `172.18.0.28`。因此下游 Node Exporter 应改为：

```ini
ExecStart=/usr/local/bin/node_exporter --web.listen-address=172.18.0.28:9100
```

Prometheus target 也写 `172.18.0.28:9100`，不能写 Gateway 的 `10.250.0.102:9100`。`10.250.0.102` 只是 Jenkins 的 Overlay 地址，不是下游节点的代理地址。

不要把监听地址放宽到 `0.0.0.0:9100`：它会在所有 IPv4 接口（包括公网接口）监听，扩大服务暴露面。绑定节点私网 IP，并在腾讯安全组中只允许 Jenkins `172.18.20.16/32` 访问 TCP/9100，才是此架构的安全边界。

下游修改 Node Exporter 后，先在 Jenkins 执行 `curl http://TARGET_IP:9100/metrics`；成功后再进行阿里 Hub 的 WireGuard 热加载、路由更新、FORWARD/SNAT 和 Prometheus target 变更。详见 [Node Exporter 安装](03-node-exporter-installation.md)。

## 配置模板

使用 [`jenkins-gateway-wg0.conf`](../wireguard/examples/jenkins-gateway-wg0.conf)。真实私钥、公网 IP 不进 Git。

阿里 Hub 上对应 Jenkins 的 Peer：

```ini
[Peer]
PublicKey = <JENKINS_PUBLIC_KEY>
AllowedIPs = 10.250.0.102/32, 172.18.0.0/16
```

Jenkins 上对应阿里 Hub 的 Peer 保持：

```ini
AllowedIPs = 10.250.0.1/32
```

生产节点回包经 Jenkins VPC 地址 `172.18.20.16` 返回；不要在 Jenkins Peer 上把 `172.18.0.0/16` 指向 WireGuard，避免覆盖本地 VPC 路由。

## 首次建立（冷启动）

```bash
chmod 600 /etc/wireguard/wg0.conf
wg-quick up wg0
wg show
ip route
```

预期 Jenkins 至少有 `10.250.0.1 dev wg0`。阿里 Hub 把生产网段交给 Jenkins Peer 后，补充：

```bash
ip route replace 172.18.0.0/16 dev wg0
ip route get 172.18.0.10
```

预期为 `172.18.0.10 dev wg0`；测试地址必须替换为已批准的生产节点。

## 下游新增后的上游动作

| 变更 | 下游动作 | 阿里 Hub | Jenkins |
| --- | --- | --- | --- |
| 新增 Node Exporter | 监听节点私网 `IP:9100`，安全组只允许 `172.18.20.16/32` | 无 | `curl http://TARGET:9100/metrics` |
| 新增生产节点 | 节点服务重启 | 检查/修改 Jenkins Peer `AllowedIPs` | 加精确 FORWARD/SNAT |
| 新增网段 | 先确认 VPC 路由 | `wg syncconf` 后仍需 `ip route replace NET dev wg0` | 保留本地 VPC 路由 |
| 修改公钥/Endpoint | 双端配置变更 | `wg syncconf` | `wg syncconf` |

### 热加载（不中断接口）

```bash
wg syncconf wg0 <(wg-quick strip wg0)
wg show
```

`syncconf` 会更新 Peer/AllowedIPs/Endpoint，但不会执行 `wg-quick` 的路由脚本。因此新增网段后必须另行执行 `ip route replace NET dev wg0`。

### 冷启动/重建

仅在接口不存在、地址/ListenPort 需要重建或热加载无法应用时，在维护窗口执行：

```bash
wg-quick down wg0
wg-quick up wg0
```

这会短暂中断隧道；完成后重新检查 `wg show`、路由和 Ping。

## 按节点实施转发

先在 Jenkins 证明 VPC 直连：

```bash
curl -fsS http://172.18.0.10:9100/metrics | head
```

保持 `FORWARD` 默认策略为 DROP，仅放行一台节点：

以下假设外联接口为 `eth0`；执行前用 `ip route` 确认真实接口名，若不同请替换命令中的 `eth0`。

```bash
TARGET_IP=172.18.0.10
GATEWAY_IP=172.18.20.16

iptables -I DOCKER-USER 1 -i wg0 -o eth0 \
  -s 10.250.0.1/32 -d ${TARGET_IP}/32 -p tcp --dport 9100 \
  -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT
iptables -I DOCKER-USER 2 -i eth0 -o wg0 \
  -s ${TARGET_IP}/32 -d 10.250.0.1/32 -p tcp --sport 9100 \
  -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -t nat -I POSTROUTING 1 -s 10.250.0.1/32 \
  -d ${TARGET_IP}/32 -o eth0 -p tcp --dport 9100 \
  -j SNAT --to-source ${GATEWAY_IP}
```

验证顺序：Jenkins `curl` → 阿里 `curl http://TARGET:9100/metrics` → Prometheus `up == 1`。首台节点通过前，不要扩大到整个 `/16` 或持久化规则。

## 排错证据

```bash
wg show
ss -lunp | grep 51820
ip route get 172.18.0.10
iptables -L DOCKER-USER -v -n --line-numbers
iptables -t nat -L POSTROUTING -v -n --line-numbers
tcpdump -ni wg0 host 10.250.0.1 and port 9100
tcpdump -ni eth0 host 172.18.0.10 and port 9100
```
