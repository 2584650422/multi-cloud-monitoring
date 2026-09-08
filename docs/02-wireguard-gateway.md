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
| 新增生产节点（已覆盖网段） | 节点服务重启 | 无 | 新增 ipset 成员，验证 Jenkins VPC 直连 |
| 新增生产网段 | 先确认 VPC 路由 | 检查/修改 Jenkins Peer `AllowedIPs`；`wg syncconf` 后补 `ip route replace NET dev wg0` | 保留本地 VPC 路由；将已批准节点加入 ipset |
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

## ipset 模式：维护资产集合，而不是按节点写防火墙规则

初版 Gateway 曾针对每台下游节点分别写三条规则（去程、回程、SNAT）。节点数量增加后，这会造成规则重复、插入顺序难维护，也不利于审计。

当前已验证的方案是：

```text
ipset wg-monitor-targets
        ↓
允许被 Gateway 抓取的下游 Node Exporter 私网 IP 集合
        ↓
三条公共 iptables 规则
```

新增或退役节点时只维护 ipset 成员；不再为每台服务器复制 FORWARD 和 SNAT 规则。

### 安全边界

`wg-monitor-targets` 只用于 Gateway 的监控转发，不代表整个 `172.18.0.0/16` 都能被访问。公共规则仍同时限制：

```text
来源接口      wg0
来源地址      10.250.0.1/32（阿里监控 Hub）
目标/源地址   必须是 ipset 成员
协议与端口    TCP/9100
连接状态      去程 NEW,ESTABLISHED；回程 ESTABLISHED,RELATED
```

因此业务访问、SSH、数据库端口和其他 WireGuard Peer 都不在此放行范围内。

### 首台节点前置验证

先在 Jenkins 证明其能通过腾讯 VPC 直连下游节点。这里以 `172.18.0.10` 为示例，实际执行时替换为已批准节点：

```bash
command -v ipset
rpm -q ipset
curl -fsS http://172.18.0.10:9100/metrics | head
```

若系统尚未安装 `ipset`，先按当前系统的软件源安装该软件包；不要在未验证 Jenkins VPC 直连前添加 FORWARD/SNAT 规则。

保持 `FORWARD` 默认策略为 DROP。以下假设腾讯 VPC 外联接口为 `eth0`、Gateway 私网 IP 为 `172.18.20.16`；执行前用 `ip route` 确认真实接口名。

### 创建集合并添加成员

```bash
ipset create wg-monitor-targets hash:ip family inet -exist
ipset add wg-monitor-targets 172.18.0.10 -exist
ipset list wg-monitor-targets
```

`-exist` 使重复执行安全：集合或成员已存在时不会报错。集合成员必须是下游节点的腾讯 VPC 私网 IP，不能填 Gateway Overlay 地址 `10.250.0.102`。

### 三条公共规则

去程：仅允许阿里 Hub 经 WireGuard 访问 ipset 成员的 Node Exporter。

```bash
iptables -I DOCKER-USER 1 \
  -i wg0 -o eth0 -s 10.250.0.1/32 \
  -m set --match-set wg-monitor-targets dst \
  -p tcp --dport 9100 \
  -m conntrack --ctstate NEW,ESTABLISHED \
  -j ACCEPT
```

回程：只允许 ipset 成员对已建立连接的 TCP/9100 响应返回阿里 Hub；不含 `NEW`，下游不能利用此规则主动发起连接。

```bash
iptables -I DOCKER-USER 2 \
  -i eth0 -o wg0 -d 10.250.0.1/32 \
  -m set --match-set wg-monitor-targets src \
  -p tcp --sport 9100 \
  -m conntrack --ctstate ESTABLISHED,RELATED \
  -j ACCEPT
```

SNAT：目标节点看到的来源改为 Gateway 私网 IP，因此回包按腾讯 VPC 原路径回 Jenkins，而不需要下游节点增加 `10.250.0.0/24` 的路由。

```bash
iptables -t nat -I POSTROUTING 1 \
  -s 10.250.0.1/32 -o eth0 \
  -m set --match-set wg-monitor-targets dst \
  -p tcp --dport 9100 \
  -j SNAT --to-source 172.18.20.16
```

数据流为：

```text
Prometheus 10.250.0.1
  → WireGuard wg0
  → Jenkins DOCKER-USER（目标必须在 wg-monitor-targets）
  → SNAT 为 172.18.20.16
  → 腾讯下游节点私网 IP:9100
```

### 为什么 `iptables -L` 会显示 `0.0.0.0/0`

执行 `iptables -L DOCKER-USER -v -n --line-numbers` 时，公共规则可能显示：

```text
ACCEPT  tcp  wg0  eth0  10.250.0.1  0.0.0.0/0
  match-set wg-monitor-targets dst tcp dpt:9100
```

这不表示 `10.250.0.1` 能访问任意 IPv4 的 9100。`0.0.0.0/0` 只表示 iptables 的普通 destination 字段没有写死单个 `-d` 地址；真正的目标限制在扩展匹配条件：

```text
-m set --match-set wg-monitor-targets dst
```

回程规则同理：普通 source 字段可显示 `0.0.0.0/0`，但 `--match-set wg-monitor-targets src` 仍要求来源是集合成员。应结合整条规则判断，推荐同时查看：

```bash
iptables -S DOCKER-USER
iptables -t nat -S POSTROUTING
ipset list wg-monitor-targets
```

### 日常节点管理

生产 Gateway 已配置持久化服务后，`/etc/wireguard/wg-monitor-targets.list` 是唯一的准入清单。不要只执行临时 `ipset add` 或 `ipset del`：下一次 `systemctl reload wg-monitor-gateway` 或服务器重启会按清单覆盖运行态。

新增已覆盖网段中的一台下游节点：

```bash
# Jenkins Gateway：先确认 VPC 直连，再修改准入清单并原子 reload
curl -fsS http://172.18.0.28:9100/metrics | head
vi /etc/wireguard/wg-monitor-targets.list
# 增加一行：172.18.0.28
systemctl reload wg-monitor-gateway
ipset test wg-monitor-targets 172.18.0.28
```

然后在监控机添加对应 Prometheus target，检查配置并 reload/restart Prometheus。最终验收：

```promql
up{job="node-exporter", instance="172.18.0.28:9100"}
```

预期为 `1`。

节点退出 Gateway 监控时，先在监控机删除 Prometheus target 并 reload/restart Prometheus，再在 Jenkins 从准入清单删除 IP 并 reload；公共 iptables 规则保持不变：

```bash
vi /etc/wireguard/wg-monitor-targets.list
# 删除：172.18.0.28
systemctl reload wg-monitor-gateway
ipset test wg-monitor-targets 172.18.0.28
```

常用检查命令：

```bash
ipset list wg-monitor-targets
ipset list wg-monitor-targets | sed -n '/Members:/,$p'
ipset test wg-monitor-targets 172.18.0.28
iptables -L DOCKER-USER -v -n --line-numbers
iptables -t nat -L POSTROUTING -v -n --line-numbers
```

iptables 计数器增长表示规则正在命中；`ipset test` 可快速确认某个 `up=0` 节点是否已被授权经过 Gateway。`systemctl status wg-monitor-gateway` 显示 `active (exited)` 对该 oneshot 服务是正常状态。

### 撤销 ipset 模式

清空集合会立即中断所有经 Gateway 的 Node Exporter 抓取，应仅在维护窗口使用：

```bash
ipset flush wg-monitor-targets
```

如果持久化服务已启用，先停止并禁用服务。`stop` 会删除三条公共规则和集合；只执行 `disable` 不会改变当前运行态：

```bash
systemctl stop wg-monitor-gateway
systemctl disable wg-monitor-gateway
```

未使用持久化服务时，完整撤销必须先删除引用集合的三条规则，再删除集合；不要依赖行号，按完整规则内容删除：

```bash
iptables -D DOCKER-USER \
  -i wg0 -o eth0 -s 10.250.0.1/32 \
  -m set --match-set wg-monitor-targets dst \
  -p tcp --dport 9100 \
  -m conntrack --ctstate NEW,ESTABLISHED \
  -j ACCEPT

iptables -D DOCKER-USER \
  -i eth0 -o wg0 -d 10.250.0.1/32 \
  -m set --match-set wg-monitor-targets src \
  -p tcp --sport 9100 \
  -m conntrack --ctstate ESTABLISHED,RELATED \
  -j ACCEPT

iptables -t nat -D POSTROUTING \
  -s 10.250.0.1/32 -o eth0 \
  -m set --match-set wg-monitor-targets dst \
  -p tcp --dport 9100 \
  -j SNAT --to-source 172.18.20.16

ipset destroy wg-monitor-targets
```

`ipset destroy` 在仍有 iptables 规则引用集合时会失败，这是保护机制。若需回退为旧的单节点写死规则，必须先添加并验证旧规则，再删除 ipset 公共规则与集合，避免监控中断。

### 持久化状态

**状态：已配置（CONFIGURED），待服务器重启验证（PENDING REBOOT VALIDATION）。** 当前已经验证服务启动和既有采集链路未被破坏；尚未实际重启 Jenkins，因此不能将“自动恢复”标记为已完成。

不使用 `iptables-save > /etc/sysconfig/iptables` 或 `iptables-services` 保存整张表。Jenkins 同时运行 Docker 与 SafeLine，`DOCKER`、DNAT、MASQUERADE 等规则由它们根据容器状态动态维护；全表恢复可能在重启后写回过期容器规则。

本项目仅持久化自有的四部分：

```text
wg-quick@wg0                         WireGuard 接口
/etc/sysctl.d/99-wg-monitor-gateway.conf  net.ipv4.ip_forward = 1
/etc/wireguard/wg-monitor-targets.list    Gateway 准入清单
wg-monitor-gateway.service           ipset + 两条 FORWARD + 一条 SNAT
```

启动顺序必须为：

```text
network-online
  → Docker 创建 DOCKER-USER
  → wg-quick@wg0 创建 wg0
  → wg-monitor-gateway 载入清单并恢复三条公共规则
```

仓库提供不含真实资产清单的恢复脚本 [wg-monitor-gateway-fw](../scripts/wg-monitor-gateway-fw)、systemd 单元 [wg-monitor-gateway.service](../systemd/wg-monitor-gateway.service) 与清单模板 [wg-monitor-targets.list.example](../wireguard/examples/wg-monitor-targets.list.example)。部署到 Jenkins 前，应核对脚本顶部的 `LAN_IF`、`MONITOR_IP`、`SNAT_IP` 是否与实际 Gateway 一致。

### 配置步骤

先让 WireGuard 自启动；若当前 `wg0` 是通过 `wg-quick up wg0` 手工创建的，只 enable，不要立刻 `start`，以免报 `wg0 already exists`：

```bash
chmod 600 /etc/wireguard/wg0.conf
systemctl enable wg-quick@wg0
systemctl is-enabled wg-quick@wg0
```

持久化内核转发：

```bash
install -d -m 0755 /etc/sysctl.d
printf 'net.ipv4.ip_forward = 1\n' > /etc/sysctl.d/99-wg-monitor-gateway.conf
sysctl net.ipv4.ip_forward
```

从已验证的运行态导出真实准入清单。该清单包含真实私网资产，不进入 Git：

```bash
ipset save wg-monitor-targets \
  | awk '$1 == "add" {print $3}' \
  | sort -V \
  > /etc/wireguard/wg-monitor-targets.list
chown root:root /etc/wireguard/wg-monitor-targets.list
chmod 600 /etc/wireguard/wg-monitor-targets.list
```

安装仓库模板并启用服务：

```bash
install -o root -g root -m 0700 \
  scripts/wg-monitor-gateway-fw \
  /usr/local/sbin/wg-monitor-gateway-fw

install -o root -g root -m 0644 \
  systemd/wg-monitor-gateway.service \
  /etc/systemd/system/wg-monitor-gateway.service

systemctl daemon-reload
systemctl enable wg-monitor-gateway
systemctl start wg-monitor-gateway
systemctl status wg-monitor-gateway --no-pager
```

恢复脚本采用 `wg-monitor-targets-new` 临时集合加载清单，并通过 `ipset swap` 原子替换正式集合；reload 过程中不会先清空正式集合。脚本还使用 `iptables -C` 检查规则，避免服务重复启动后出现重复规则。

### 重启验证清单（待维护窗口执行）

重启后按顺序检查：

```bash
systemctl status wg-quick@wg0 --no-pager
wg show
ip -br addr show wg0

systemctl status wg-monitor-gateway --no-pager
ipset list wg-monitor-targets
iptables -L DOCKER-USER -v -n --line-numbers
iptables -t nat -L POSTROUTING -v -n --line-numbers
```

预期：`wg0` 有 `10.250.0.102/32`、WireGuard 有新的 handshake、`wg-monitor-gateway` 为 `active (exited)`、ipset 成员存在、两条 `DOCKER-USER` 规则与一条 SNAT 规则存在。最后在阿里 Hub 复核：

```bash
curl -fsS http://TARGET_PRIVATE_IP:9100/metrics | head
```

并在 Prometheus 验证所有腾讯生产 target 的 `up` 恢复为 `1`。完成这次演练后，才能将持久化状态更新为 `DONE`。

## 排错证据

```bash
wg show
ss -lunp | grep 51820
ip route get 172.18.0.10
iptables -L DOCKER-USER -v -n --line-numbers
iptables -t nat -L POSTROUTING -v -n --line-numbers
iptables -S DOCKER-USER
iptables -t nat -S POSTROUTING
ipset list wg-monitor-targets
ipset test wg-monitor-targets 172.18.0.10
tcpdump -ni wg0 host 10.250.0.1 and port 9100
tcpdump -ni eth0 host 172.18.0.10 and port 9100
```
