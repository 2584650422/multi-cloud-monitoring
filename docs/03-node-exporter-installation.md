# Node Exporter Installation

本项目在腾讯测试机部署 Node Exporter，并让它只监听 WireGuard 地址 `10.250.0.101:9100`。

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

当前生产实际 Node Exporter 版本未从原始配置中取得，因此以下固定 `1.9.1` 为可复现安装基线，部署前需要在测试机核对版本和校验和：

```bash
cd /root
curl -fLO https://github.com/prometheus/node_exporter/releases/download/v1.9.1/node_exporter-1.9.1.linux-amd64.tar.gz
tar -xzf node_exporter-1.9.1.linux-amd64.tar.gz
install -o root -g root -m 0755 \
  node_exporter-1.9.1.linux-amd64/node_exporter \
  /usr/local/bin/node_exporter

/usr/local/bin/node_exporter --version
```

TODO：从腾讯测试机执行 `/usr/local/bin/node_exporter --version`，将实际版本和发布包 SHA256 补回文档。

## systemd

把仓库中的 [systemd/node_exporter.service](../systemd/node_exporter.service) 安装到系统：

```bash
install -o root -g root -m 0644 \
  systemd/node_exporter.service \
  /etc/systemd/system/node_exporter.service

systemctl daemon-reload
systemctl start node_exporter
```

关键参数：

```text
--web.listen-address=10.250.0.101:9100
```

不使用 `0.0.0.0:9100`，因为后者会监听 `eth0`、公网映射路径和所有其他接口。精确绑定 wg0 可以把服务暴露面限制在监控 Overlay；腾讯云安全组也不应开放公网 TCP 9100。

`After=wg-quick@wg0.service` 表示如果系统使用该 systemd 单元管理 WireGuard，Node Exporter 应在 wg0 之后启动。它不能替代运行时检查；如果 wg0 未启用，仍应先修复 WireGuard。

## 本机验证

```bash
systemctl status node_exporter --no-pager -l
journalctl -u node_exporter -n 100 --no-pager
ss -lntp | grep 9100
curl -fsS http://10.250.0.101:9100/metrics | head
```

`ss` 应显示 `10.250.0.101:9100`，不应显示 `0.0.0.0:9100` 或公网地址。

## 阿里监控端验证

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

- `cannot assign requested address`：启动时 `10.250.0.101` 不在本机，先恢复 wg0。
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
