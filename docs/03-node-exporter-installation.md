# Node Exporter Installation

本项目在腾讯测试机部署 Node Exporter `1.11.1`。当前仓库中的 systemd 单元对应已经验证的**点对点 WireGuard 模式**：Node Exporter 只监听 WireGuard 地址 `10.250.0.101:9100`。

引入 Jenkins WireGuard Gateway 模式后，Gateway 后面的生产节点通常不安装 WireGuard，也没有 `10.250.0.x` 地址。为让阿里 Prometheus 经 Gateway 访问这些节点，Node Exporter 必须改为监听各节点自己的腾讯 VPC 私网 IP。这个监听地址调整是 Gateway 模式下的优化，不代表修改了原有点对点测试结论。

## 监听地址：点对点与 Gateway

| 部署模式 | Node Exporter 监听 | Prometheus target 示例 | 说明 |
| --- | --- | --- | --- |
| 点对点（当前测试） | `10.250.0.101:9100` | `10.250.0.101:9100` | 节点自身是 WireGuard Peer，指标只经 wg0 提供 |
| Gateway | 节点私网 `172.18.x.x:9100` | `172.18.x.x:9100` | 节点不需要安装 WireGuard，由 Gateway 转发并 SNAT |

不要把 Gateway 自己的 `10.250.0.102` 写成所有下游节点的 target；它只是 Jenkins Gateway 的 Overlay 地址。Gateway 模式下，Prometheus target 应写被监控节点自己的 VPC 私网地址。

监听地址的安全边界：

```text
127.0.0.1:9100       仅本机回环可访问，远端 Prometheus/Gateway 无法访问
172.18.0.28:9100     仅绑定该节点私网接口，适合 Gateway 采集
10.250.0.101:9100    仅绑定点对点模式的 wg0 地址
0.0.0.0:9100         所有 IPv4 接口监听，暴露面最大，不是首选
```

不应为了“让远端能访问”而直接改成 `0.0.0.0:9100`。即使云安全组暂时拦住公网 TCP/9100，服务层仍会在公网接口上监听；更稳妥的做法是绑定节点私网 IP，并在安全组和主机防火墙中只允许 Gateway `172.18.20.16/32`。

## 前置检查

```bash
ip -br addr show wg0
ping -c 2 10.250.0.1
uname -m
```

必须先确认 `wg0` 已拥有 `10.250.0.101/32`。如果服务启动时该地址不存在，Node Exporter 会因无法 bind 而退出。

## 创建非登录用户

```bash
useradd --system --no-create-home --shell /sbin/nologin node_exporter
id node_exporter
```

Node Exporter 只需要读取系统公开统计信息，不应以 root 常驻。

## 下载和安装二进制

本项目腾讯测试机实际采用并验证的 Node Exporter 版本为 `1.11.1`。安装前后都应执行版本检查；发布包的 SHA256 仍应以下载来源提供的校验值为准，不把未核对的值写入仓库：

```bash
cd /root
curl -fLO https://github.com/prometheus/node_exporter/releases/download/v1.11.1/node_exporter-1.11.1.linux-amd64.tar.gz
tar -xzf node_exporter-1.11.1.linux-amd64.tar.gz
install -o root -g root -m 0755 \
  node_exporter-1.11.1.linux-amd64/node_exporter \
  /usr/local/bin/node_exporter

/usr/local/bin/node_exporter --version
```

预期输出应包含：

```text
node_exporter, version 1.11.1
```

如果输出不是 `1.11.1`，先停止继续部署，核对下载包、解压目录和 `/usr/local/bin/node_exporter` 是否仍是旧文件。

## systemd

把仓库中的 [systemd/node_exporter.service](../systemd/node_exporter.service) 安装到系统：

```bash
install -o root -g root -m 0644 \
  systemd/node_exporter.service \
  /etc/systemd/system/node_exporter.service

systemctl daemon-reload
systemctl start node_exporter
```

关键参数（点对点测试单元）：

```text
--web.listen-address=10.250.0.101:9100
```

不使用 `0.0.0.0:9100`，因为后者会监听 `eth0`、公网映射路径和所有其他接口。精确绑定 `10.250.0.101` 可以把点对点测试服务限制在监控 Overlay；腾讯云安全组也不应开放公网 TCP 9100。

`After=wg-quick@wg0.service` 表示如果系统使用该 systemd 单元管理 WireGuard，Node Exporter 应在 wg0 之后启动。它不能替代运行时检查；如果 wg0 未启用，仍应先修复 WireGuard。

### Gateway 节点改为监听私网 IP

Gateway 后的生产节点以自身私网地址为例（假设为 `172.18.0.28`）修改服务：

```bash
cp -a /etc/systemd/system/node_exporter.service \
  /etc/systemd/system/node_exporter.service.bak.$(date +%Y%m%d%H%M%S)
vi /etc/systemd/system/node_exporter.service
```

将 `ExecStart` 改为：

```ini
ExecStart=/usr/local/bin/node_exporter --web.listen-address=172.18.0.28:9100
```

然后重新加载并验证：

```bash
systemctl daemon-reload
systemctl restart node_exporter
ss -lntp | grep 9100
curl -fsS http://172.18.0.28:9100/metrics | head
```

在 Jenkins Gateway 上验证 VPC 直连：

```bash
curl -fsS http://172.18.0.28:9100/metrics | head
```

确认 Jenkins 直连成功后，才继续配置阿里 Hub 的 `AllowedIPs`、路由、FORWARD 和 SNAT；完整顺序见 [WireGuard Gateway 部署](02-wireguard-gateway.md)。不要先把监听改成 `0.0.0.0` 来绕过路由或防火墙问题。

## 本机验证（点对点测试）

```bash
systemctl status node_exporter --no-pager -l
journalctl -u node_exporter -n 100 --no-pager
ss -lntp | grep 9100
curl -fsS http://10.250.0.101:9100/metrics | head
```

点对点测试应显示 `10.250.0.101:9100`，不应显示 `0.0.0.0:9100` 或公网地址。Gateway 生产节点则应显示该节点私网 `IP:9100`。

## 阿里监控端验证（点对点测试）

```bash
ip route get 10.250.0.101
curl -fsS http://10.250.0.101:9100/metrics | head
```

路由应指向 `wg0`。成功响应应包含以 `# HELP`、`# TYPE`、`node_` 开头的指标。

## 常见启动失败

```bash
systemctl status node_exporter --no-pager -l
journalctl -u node_exporter -b --no-pager
ip addr show wg0
ss -lntp | grep 9100
```

- `cannot assign requested address`：点对点模式下通常是 `10.250.0.101` 尚未出现在 wg0；Gateway 模式下则检查配置中的节点私网 IP 是否实际存在于本机。
- `address already in use`：已有进程占用 9100，使用 `ss -lntp` 找出进程。
- 阿里端 curl 超时：先验证 `wg show`、路由和双向 Ping，再检查本机防火墙；不要通过开放公网 9100 绕过问题。

## 升级与回滚

升级前保存当前版本：

```bash
/usr/local/bin/node_exporter --version
cp -a /usr/local/bin/node_exporter /usr/local/bin/node_exporter.previous
```

将新二进制安装为临时路径，先执行 `--version`，再于变更窗口替换并重启：

```bash
install -o root -g root -m 0755 node_exporter /usr/local/bin/node_exporter.new
mv /usr/local/bin/node_exporter.new /usr/local/bin/node_exporter
systemctl restart node_exporter
```

若验证失败：

```bash
cp -a /usr/local/bin/node_exporter.previous /usr/local/bin/node_exporter
systemctl restart node_exporter
```
