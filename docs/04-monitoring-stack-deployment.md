# Monitoring Stack Deployment

本章给出 Prometheus、Alertmanager 与 Grafana 的 Compose 部署基线。执行前必须与生产机现有文件逐项比较，尤其是数据目录和已占用端口。

## 1. 生产目录

```bash
mkdir -p /data/docker/monitoring/prometheus/rules
mkdir -p /data/docker/monitoring/prometheus/targets
mkdir -p /data/docker/monitoring/prometheus/data

mkdir -p /data/docker/monitoring/alertmanager/data

mkdir -p /data/docker/monitoring/grafana/provisioning/datasources
mkdir -p /data/docker/monitoring/grafana/provisioning/dashboards
mkdir -p /data/docker/monitoring/grafana/provisioning/alerting
mkdir -p /data/docker/monitoring/grafana/provisioning/plugins
mkdir -p /data/docker/monitoring/grafana/data
mkdir -p /data/docker/monitoring/grafana/logs
```

已知历史上可能创建了：

```text
/data/docker/monitoring/prometheus/date
```

先检查：

```bash
find /data/docker/monitoring/prometheus -maxdepth 1 -type d -ls
du -sh /data/docker/monitoring/prometheus/date 2>/dev/null
du -sh /data/docker/monitoring/prometheus/data 2>/dev/null
```

迁移保护：确认 `date/` 是否含现有 TSDB 数据后，再制定迁移窗口。不要直接 `mv`、删除或让两个目录互相覆盖。仓库 Compose 使用正确目标 `data/`。

## 2. 同步配置

以下命令示意从仓库根目录复制配置。执行前先备份生产文件：

```bash
install -o root -g root -m 0644 prometheus/prometheus.yml \
  /data/docker/monitoring/prometheus/prometheus.yml
install -o root -g root -m 0644 prometheus/targets/tencent-node.yml.example \
  /data/docker/monitoring/prometheus/targets/tencent-node.yml.example
install -o root -g root -m 0644 prometheus/rules/node-down.yml \
  /data/docker/monitoring/prometheus/rules/node-down.yml

install -o root -g root -m 0644 alertmanager/alertmanager.yml.example \
  /data/docker/monitoring/alertmanager/alertmanager.yml.example

install -o root -g root -m 0644 grafana/grafana.ini \
  /data/docker/monitoring/grafana/grafana.ini
install -o root -g root -m 0644 grafana/provisioning/datasources/prometheus.yml \
  /data/docker/monitoring/grafana/provisioning/datasources/prometheus.yml

install -o root -g root -m 0644 docker-compose.yml \
  /data/docker/monitoring/docker-compose.yml
```

从 target 模板创建仅保留在监控机本地的真实清单：

```bash
cp /data/docker/monitoring/prometheus/targets/tencent-node.yml.example \
  /data/docker/monitoring/prometheus/targets/tencent-node.yml
vi /data/docker/monitoring/prometheus/targets/tencent-node.yml
```

从 Alertmanager 模板创建只存在于监控机的真实配置，并填入 SMTP 信息与收件人：

```bash
cp /data/docker/monitoring/alertmanager/alertmanager.yml.example \
  /data/docker/monitoring/alertmanager/alertmanager.yml
vi /data/docker/monitoring/alertmanager/alertmanager.yml
```

`tencent-node.yml` 含私网地址和资产名称；`alertmanager.yml` 含 SMTP 凭据和收件人地址。两者必须保持在 Git 忽略列表中。NodeDown 规则已作为 `prometheus/rules/node-down.yml` 随仓库部署。

## 3. UID、GID 与权限

仓库 Compose 显式使用：

```text
Prometheus: 65534:65534
Alertmanager: 65534:65534
Grafana:    472:0
```

部署前用镜像确认，避免未来镜像改变：

```bash
docker run --rm --entrypoint /bin/sh prom/prometheus:v3.13.2 -c 'id'
docker run --rm --entrypoint /bin/sh prom/alertmanager:v0.28.0 -c 'id'
docker run --rm --entrypoint /bin/sh grafana/grafana:13.2.0 -c 'id'
```

配置由 root 管理、容器只读：

```bash
chown -R root:root /data/docker/monitoring/prometheus/rules
chown -R root:root /data/docker/monitoring/prometheus/targets
chown root:root /data/docker/monitoring/prometheus/prometheus.yml
chmod 0755 /data/docker/monitoring/prometheus/rules
chmod 0755 /data/docker/monitoring/prometheus/targets
chmod 0644 /data/docker/monitoring/prometheus/prometheus.yml

chown -R root:root /data/docker/monitoring/grafana/provisioning
chown root:root /data/docker/monitoring/grafana/grafana.ini
find /data/docker/monitoring/grafana/provisioning -type d -exec chmod 0755 {} \;
find /data/docker/monitoring/grafana/provisioning -type f -exec chmod 0644 {} \;
chmod 0644 /data/docker/monitoring/grafana/grafana.ini
```

运行数据必须允许容器身份写入：

```bash
chown -R 65534:65534 /data/docker/monitoring/prometheus/data
chmod 0750 /data/docker/monitoring/prometheus/data

# Alertmanager runs as 65534:65534 and must be able to read this secret file.
chown root:65534 /data/docker/monitoring/alertmanager/alertmanager.yml
chmod 0640 /data/docker/monitoring/alertmanager/alertmanager.yml
chown -R 65534:65534 /data/docker/monitoring/alertmanager/data
chmod 0750 /data/docker/monitoring/alertmanager/data

chown -R 472:0 /data/docker/monitoring/grafana/data
chown -R 472:0 /data/docker/monitoring/grafana/logs
chmod 0750 /data/docker/monitoring/grafana/data
chmod 0750 /data/docker/monitoring/grafana/logs
```

不要 `chmod -R 777`：它让任意本机用户和受攻陷进程修改 TSDB、Grafana SQLite、插件或配置，掩盖真正的所有权问题。

CentOS SELinux 开启时，Compose 的 `:Z` 会为单个容器私有使用重新标记 bind mount，使容器进程可访问；`:ro` 则在容器侧强制只读。`/etc/localtime` 不需要写权限，保持 `:ro`。

## 4. Compose 字段解释

实际文件为 [docker-compose.yml](../docker-compose.yml)：

- `image`：固定版本，避免无意跟随 `latest`。
- `container_name`：让 Runbook 中 `docker exec prometheus|alertmanager|grafana` 稳定可用；代价是不能直接横向扩容同名服务。
- `restart: unless-stopped`：进程或 Docker 恢复后自动拉起，但人工停止后保持停止。
- `network_mode: host`：容器直接共享宿主机网络栈。
- `user`：不以容器 root 运行，并与 bind mount 所有权匹配。
- `depends_on`：Compose 启动时先创建 Alertmanager，再创建 Prometheus；它不替代 `/-/ready` 健康检查，Prometheus 仍会在 Alertmanager 暂不可用时重试投递。
- `volumes`：配置只读，数据可写，所有关键内容在宿主机可见。
- `command`：固定各组件的配置路径、数据路径、监听和 lifecycle 参数。
- `environment`：显式固定 Grafana paths，便于排查 provisioning 和持久化。
- `logging`：`json-file` 单文件 50 MiB、最多 5 个，避免 Docker 日志无限增长。

主配置文件和 `/etc/localtime` 使用 bind long syntax，并设置 `create_host_path: false`。这样源文件拼错或缺失时 Compose 直接失败，不会静默创建一个同名目录；目录型挂载则由前面的目录创建步骤显式准备。

### 为什么使用 host network

宿主机 WireGuard 建立后，路由表包含：

```text
10.250.0.101 dev wg0
```

Prometheus 需要经宿主机 `wg0` 到达腾讯 VPC Gateway，再访问下游节点的私网 `IP:9100`。host network 让容器的路由查询直接命中宿主机 `wg0`，不需要在 bridge namespace 中额外处理路由、NAT、FORWARD 和 Docker iptables。

取舍是容器网络隔离更弱、端口直接占用宿主机。Prometheus 与 Alertmanager 因而显式只监听 `127.0.0.1:9090`、`127.0.0.1:9093`；Grafana 监听宿主机 3000，仍需由安全组、防火墙或后续反向代理限制访问。

Grafana 也使用 host network，因此 datasource 可访问同一网络命名空间内的 `http://127.0.0.1:9090`。在 bridge 网络中，容器自己的 `127.0.0.1` 不是 Prometheus 容器。

## 5. 每个 bind mount

| 宿主机路径 | 容器路径 | 模式 | 目的 |
| --- | --- | --- | --- |
| `prometheus.yml` | `/etc/prometheus/prometheus.yml` | `ro,Z` | 主配置 |
| `rules/` | `/etc/prometheus/rules` | `ro,Z` | 告警规则；当前包含 `NodeDown` |
| `targets/` | `/etc/prometheus/targets` | `ro,Z` | file_sd 节点清单 |
| `prometheus/data/` | `/prometheus` | `Z` | TSDB/WAL 持久化 |
| `alertmanager.yml` | `/etc/alertmanager/alertmanager.yml` | `ro,Z` | 告警分组、路由与 SMTP 配置 |
| `alertmanager/data/` | `/alertmanager` | `Z` | silences、通知状态等持久化数据 |
| `grafana.ini` | `/etc/grafana/grafana.ini` | `ro,Z` | Grafana 主配置 |
| provisioning 子目录 | `/etc/grafana/provisioning/*` | `ro,Z` | 声明式资源 |
| `grafana/data/` | `/var/lib/grafana` | `Z` | SQLite、session、插件 |
| `grafana/logs/` | `/var/log/grafana` | `Z` | 文件日志 |
| `/etc/localtime` | `/etc/localtime` | `ro` | 与宿主机时区一致 |

## 6. 启动前检查

```bash
cd /data/docker/monitoring
docker compose config

docker run --rm \
  -v /data/docker/monitoring/prometheus:/etc/prometheus:ro,Z \
  --entrypoint /bin/promtool \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml

docker run --rm \
  -v /data/docker/monitoring/alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro,Z \
  --entrypoint /bin/amtool \
  prom/alertmanager:v0.28.0 \
  check-config /etc/alertmanager/alertmanager.yml
```

还要确认端口未被旧二进制服务占用：

```bash
ss -lntp | grep -E ':9090|:3000'
systemctl status prometheus grafana grafana-server --no-pager 2>/dev/null
```

如果旧 Prometheus/Grafana 正在运行，必须另行制定切换窗口；不要直接启动 Compose 争抢端口。

## 7. 启动与验证

在批准的变更窗口执行：

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=100 prometheus
docker compose logs --tail=100 alertmanager
docker compose logs --tail=100 grafana
```

这不是本次仓库整理过程中执行的操作。停止、迁移旧服务和生产切换均需单独审批。
