# WireGuard Installation on CentOS 7

本文记录本项目在 CentOS Linux 7 上实际采用的 WireGuard 安装路径。CentOS 7 与 EPEL 7 已 EOL，普通活动仓库无法再找到所需包。

## 已验证环境

| 角色 | 主机私网地址 | 内核 | wg0 地址 |
| --- | --- | --- | --- |
| 阿里监控端 | `172.16.90.17` | `3.10.0-1160.119.1.el7.x86_64` | `10.250.0.1/32` |
| 腾讯测试端 | `172.18.0.6` | `3.10.0-1160.114.2.el7.x86_64` | `10.250.0.101/32` |

安装前确认：

```bash
cat /etc/os-release
uname -r
ip -br addr
ip route
```

不要在承载业务的 CentOS 7 主机上顺手执行 `yum update`、替换内核或重启。

## 为什么不用普通 yum

实际执行以下命令时，活动仓库已无法提供 EL7 历史包：

```bash
yum install -y kmod-wireguard wireguard-tools
```

错误为：

```text
No package kmod-wireguard available.
No package wireguard-tools available.
```

最终使用固定归档 RPM：

- `wireguard-tools-1.0.20210914-1.el7.x86_64`
- `kmod-wireguard-1.0.20220627-1.el7_9.elrepo.x86_64`

## 下载并检查归档 RPM

两台主机分别执行：

```bash
mkdir -p /root/wireguard-rpms
cd /root/wireguard-rpms

curl -fLo wireguard-tools-1.0.20210914-1.el7.x86_64.rpm \
  https://mirrors.aliyun.com/epel-archive/7/x86_64/Packages/w/wireguard-tools-1.0.20210914-1.el7.x86_64.rpm

curl -fLo kmod-wireguard-1.0.20220627-1.el7_9.elrepo.x86_64.rpm \
  https://mirror.rc.usf.edu/elrepo/archive/elrepo/el7/x86_64/RPMS/kmod-wireguard-1.0.20220627-1.el7_9.elrepo.x86_64.rpm
```

归档站可能变化。若下载失败，应先寻找可信的 EPEL/ELRepo 官方归档镜像，并核对包名、签名和哈希；不要从不明 RPM 网站下载，也不要使用 `--nodeps`。

安装前检查：

```bash
ls -lh *.rpm
file *.rpm
rpm -qpi wireguard-tools-1.0.20210914-1.el7.x86_64.rpm
rpm -qpi kmod-wireguard-1.0.20220627-1.el7_9.elrepo.x86_64.rpm
rpm -qpR wireguard-tools-1.0.20210914-1.el7.x86_64.rpm
rpm -qpR kmod-wireguard-1.0.20220627-1.el7_9.elrepo.x86_64.rpm
```

这些命令分别确认文件确实为 RPM、查看包元数据并检查依赖，避免把 HTML 错误页或不匹配的软件包装进系统。

## 安装

```bash
yum localinstall -y \
  ./kmod-wireguard-1.0.20220627-1.el7_9.elrepo.x86_64.rpm \
  ./wireguard-tools-1.0.20210914-1.el7.x86_64.rpm
```

使用 `yum localinstall` 是为了让 yum 从仍可用的系统仓库解析依赖；不要执行 `rpm -ivh --nodeps`。

## 验证工具与内核模块

```bash
rpm -qa | grep -E 'wireguard|elrepo'
wg --version
modprobe wireguard
lsmod | grep wireguard
modinfo wireguard
```

- `wg --version`：确认用户态管理工具已安装。
- `modprobe wireguard`：请求内核加载 WireGuard 模块；成功通常没有输出。
- `lsmod`：确认模块当前已经加载。
- `modinfo`：确认模块文件、版本、依赖和 vermagic 可被系统识别。

最后做不修改现有路由的临时接口测试：

```bash
ip link add wg-test type wireguard
ip -br link show wg-test
ip link del wg-test
```

这验证 Linux 能实际创建 WireGuard 类型网卡。测试接口删除后，不应改变 `eth0` 或默认路由。

## 密钥

两端分别生成自己的密钥：

```bash
install -d -m 700 /etc/wireguard
cd /etc/wireguard
umask 077
wg genkey | tee private.key | wg pubkey > public.key
chmod 600 private.key public.key
```

只有 `public.key` 可以交换。不要把 `private.key` 放入 Git、聊天、工单或普通备份目录。

## 地址规划

`10.250.0.0/24` 是监控专用 WireGuard Overlay，不属于阿里或腾讯 VPC：

- `.1`：阿里监控 Hub。
- `.101`：腾讯第一台测试 Spoke。
- 后续腾讯节点可从 `.102` 顺序规划，但当前仍为 PLANNED。

双方使用 `/32`，AllowedIPs 也只包含对端明确地址，因此不会接管 `0.0.0.0/0` 默认路由。

## 配置阿里监控端

复制 [阿里模板](../wireguard/examples/alibaba-wg0.conf) 到 `/etc/wireguard/wg0.conf`，只在目标主机替换 placeholder：

```ini
[Interface]
Address = 10.250.0.1/32
ListenPort = 51820
PrivateKey = <ALI_PRIVATE_KEY>

[Peer]
PublicKey = <TENCENT_PUBLIC_KEY>
AllowedIPs = 10.250.0.101/32
```

## 配置腾讯测试端

复制 [腾讯模板](../wireguard/examples/tencent-wg0.conf)：

```ini
[Interface]
Address = 10.250.0.101/32
PrivateKey = <TENCENT_PRIVATE_KEY>

[Peer]
PublicKey = <ALI_PUBLIC_KEY>
Endpoint = <ALI_PUBLIC_IP>:51820
AllowedIPs = 10.250.0.1/32
PersistentKeepalive = 25
```

`PersistentKeepalive = 25` 让腾讯端定期向 Hub 发包，维持 NAT/状态防火墙映射。两端都执行：

```bash
chmod 600 /etc/wireguard/wg0.conf
```

## 云安全组

阿里监控机入方向只允许：

```text
protocol: UDP
destination port: 51820
source: 腾讯测试机公网 IP/32
```

不要误选 TCP，也不要开放 `0.0.0.0/0`。腾讯端通常无需开放 51820 入站，因为它主动连接阿里 Hub；如果出方向受限，应允许到阿里公网 IP/32 的 UDP 51820。

腾讯公网安全组不要开放 TCP 9100。Node Exporter 流量在 WireGuard 隧道内部传输。

## 首次启动与验证

先阿里，后腾讯：

```bash
wg-quick up wg0
ip -br addr show wg0
ip route
wg show
```

腾讯端触发流量：

```bash
ping -c 4 10.250.0.1
wg show
```

阿里端反向验证：

```bash
ping -c 4 10.250.0.101
wg show
```

成功时 `wg show` 应包含类似结构，密钥和公网地址会不同：

```text
interface: wg0
  listening port: 51820

peer: <REDACTED_PUBLIC_KEY>
  endpoint: <PEER_PUBLIC_IP>:<UDP_PORT>
  allowed ips: 10.250.0.101/32
  latest handshake: 8 seconds ago
  transfer: 1.20 KiB received, 1.10 KiB sent
```

判断标准是 `latest handshake` 持续更新且收发字节均非 0；同时应出现精确路由：

```text
10.250.0.101 dev wg0
```

本项目已经完成上述通信验证。开机自启策略需要结合生产变更窗口单独确认。
