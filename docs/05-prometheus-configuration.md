# Prometheus Configuration

实际仓库配置为 [prometheus/prometheus.yml](../prometheus/prometheus.yml)。目标清单仅保存脱敏模板 [prometheus/targets/tencent-node.yml.example](../prometheus/targets/tencent-node.yml.example)；监控机上的真实 `*-node.yml` 不进入 Git。

## 主配置结构

```yaml
global:
  scrape_interval: 30s
  evaluation_interval: 30s
```

- `scrape_interval`：默认每 30 秒抓取一次目标。
- `evaluation_interval`：默认每 30 秒评估记录规则和告警规则。

```yaml
rule_files:
  - /etc/prometheus/rules/*.yml
```

这里只加载真正以 `.yml` 结尾的规则。仓库中的 `node-down.yml` 已启用 `NodeDown` 规则。

## alerting

当前 Alertmanager 运行在同一监控 Hub，并仅监听 loopback：

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - 127.0.0.1:9093
```

Prometheus 在规则变为 `Firing` 后将告警推送给 Alertmanager；恢复时也会发送恢复状态。该链路以及 SMTP 的 FIRING/RESOLVED 邮件已通过 NodeDown 演练验证。Alertmanager 配置、邮件路由和 reload 步骤见 [Alertmanager 配置](08-alertmanager-configuration.md)。

## scrape_configs

Prometheus 自监控：

```yaml
- job_name: prometheus
  static_configs:
    - targets:
        - 127.0.0.1:9090
```

腾讯 Node Exporter 使用 file_sd：

```yaml
- job_name: node-exporter
  file_sd_configs:
    - files:
        - /etc/prometheus/targets/*-node.yml
```

`job_name` 会成为 `job` 标签。file_sd 把节点清单与采集策略分开，新增主机时不必继续扩大主配置。

## 脱敏 Target 模板与标签

```yaml
- targets:
    - "<TENCENT_NODE_PRIVATE_IP>:9100"
  labels:
    cloud: "tencent"
    env: "prod"
    private_ip: "<TENCENT_NODE_PRIVATE_IP>"
    host: "tc-prod-node-01"
```

- `targets` 写 Prometheus 实际访问的 endpoint：点对点使用 WireGuard 地址；Gateway 下游使用节点腾讯 VPC 私网地址。
- `private_ip` 保存该节点的 VPC 私网地址，用于资产识别和排障。
- `cloud`、`env`：用于 Grafana 过滤和告警路由。
- `host`：给人阅读的稳定资产名称。按资产命名规范维护，不使用公网 IP 或临时 hostname。

`instance` 不在 target labels 中手工覆盖。Prometheus 自动把真实采集 endpoint 写入 `instance`；`host` 承担可读名称。不要把公网 IP 当作 `host`。

当前标准标签只保留：

```text
host        人类可读的资产名称
cloud       aliyun / tencent
env         prod / test
private_ip  云 VPC 私网地址
```

`wg_ip` 已能从 `instance` 得到，`public_ip` 不参与 Dashboard 筛选且可能变化，`instance_name` 与 `host` 重复，因此不保留。Node Exporter 的 `nodename` 是操作系统 hostname，也不替代资产名称。

## 增加 Target

按采集拓扑选择 target 地址。点对点节点先规划新的、不冲突的 WireGuard `/32` 地址并完成隧道与 Node Exporter 验证；Gateway 下游节点则使用自己的腾讯 VPC 私网地址。

### 点对点节点

```yaml
- targets:
    - 10.250.0.103:9100
  labels:
    cloud: tencent
    env: prod
    private_ip: 10.0.8.15
    host: tc-prod-node-01
```

### Gateway 下游节点

```yaml
- targets:
    - 172.18.0.28:9100
  labels:
    cloud: tencent
    env: prod
    private_ip: 172.18.0.28
    host: tc-prod-node-28
```

`10.250.0.102` 是 Gateway 自身的 Overlay 地址，不是下游节点的 target。Gateway 路由、FORWARD 与 SNAT 的配置顺序见 [WireGuard Gateway 部署](02-wireguard-gateway.md)。

在监控机上从模板创建本地 target 文件（名称必须匹配 `*-node.yml`），填写真实私网 IP 与资产名后再检查配置：

```bash
cp /data/docker/monitoring/prometheus/targets/tencent-node.yml.example \
  /data/docker/monitoring/prometheus/targets/tencent-node.yml
vi /data/docker/monitoring/prometheus/targets/tencent-node.yml
```

不要把生成的真实 `*-node.yml` 回传到公共 Git 仓库。

## promtool 检查

生产目录的完整检查命令：

```bash
docker run --rm \
  -v /data/docker/monitoring/prometheus:/etc/prometheus:ro,Z \
  --entrypoint /bin/promtool \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml
```

成功输出应包含：

```text
Checking /etc/prometheus/prometheus.yml
 SUCCESS: /etc/prometheus/prometheus.yml is valid prometheus config file syntax
```

如果启用了规则，还会逐个检查 rule 文件并显示成功。任何 `FAILED` 都应阻止 reload/restart。

## Reload

Compose 启用了 `--web.enable-lifecycle`，并让 Prometheus 只监听本机。因此在监控宿主机执行：

```bash
curl -fsS -X POST http://127.0.0.1:9090/-/reload
```

reload 不重启进程，也不重放 WAL，适合主配置、rules 和 target 变更。操作后检查：

```bash
docker compose logs --tail=100 prometheus
curl -fsS http://127.0.0.1:9090/-/ready
curl -fsS 'http://127.0.0.1:9090/api/v1/targets?state=active'
```

file_sd target 文件会自动重新发现，但仍应先执行 promtool，并通过 API 验证发现结果。

如果 lifecycle 未启用或 reload 返回 403/404，核对 Compose 实际 command；必要时在变更窗口执行：

```bash
docker compose restart prometheus
```

## Target 和查询验证

```bash
curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=up'
curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=up%7Bjob%3D%22node-exporter%22%7D'
curl -fsS 'http://127.0.0.1:9090/api/v1/targets?state=active'
```

健康 target 应返回 `up == 1`。若为 0，检查 API 中 `lastError`，再验证宿主机到对应 target 的 `curl`、`ip route get` 和 `wg show`；点对点节点使用 WireGuard 地址，Gateway 下游节点使用 VPC 私网地址。

## 数据位置

容器内 `/prometheus` 对应：

```text
/data/docker/monitoring/prometheus/data
```

其中包含 WAL、block 和元数据。不要手工编辑这些文件，也不要在运行中用普通文件复制冒充一致性备份。
