# Prometheus Configuration

实际仓库配置为 [prometheus/prometheus.yml](../prometheus/prometheus.yml)，腾讯测试节点清单为 [prometheus/targets/tencent-node.yml](../prometheus/targets/tencent-node.yml)。Compose 迁移仍为 IN PROGRESS。

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

这里只加载真正以 `.yml` 结尾的规则。当前 `node-down.yml.example` 不会被加载，因为 Alertmanager 和告警链路尚未实施。

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
- job_name: tencent-node
  file_sd_configs:
    - files:
        - /etc/prometheus/targets/tencent-node.yml
      refresh_interval: 1m
```

`job_name` 会成为 `job` 标签。file_sd 把节点清单与采集策略分开，新增主机时不必继续扩大主配置。

## 当前 Target 与标签

```yaml
- targets:
    - 10.250.0.101:9100
  labels:
    cloud: tencent
    env: test
    private_ip: 172.18.0.6
    host: tc-test-node-01
```

- `10.250.0.101`：WireGuard Overlay 地址，Prometheus 实际通过它采集。
- `172.18.0.6`：腾讯 VPC 中真实私网地址，只作为识别标签，不参与这次路由。
- `cloud`、`env`：用于 Grafana 过滤和告警路由。
- `host`：给人阅读的稳定资产名称。当前名称是脱敏基线，TODO：用生产资产清单中的真实规范名称替换。

`instance` 不在 target labels 中手工覆盖。Prometheus 自动把真实采集 endpoint 写成 `instance="10.250.0.101:9100"`；`host` 承担可读名称。不要把公网 IP 当作 `host`。

当前标准标签只保留：

```text
host        人类可读的资产名称
cloud       aliyun / tencent
env         prod / test
private_ip  云 VPC 私网地址
```

`wg_ip` 已能从 `instance` 得到，`public_ip` 不参与 Dashboard 筛选且可能变化，`instance_name` 与 `host` 重复，因此不保留。Node Exporter 的 `nodename` 是操作系统 hostname，也不替代资产名称。

## 增加腾讯 Target

先规划新的、不冲突的 WireGuard `/32` 地址并完成隧道和 Node Exporter 验证，再编辑 `prometheus/targets/tencent-node.yml`：

```yaml
- targets:
    - 10.250.0.102:9100
  labels:
    cloud: tencent
    env: prod
    private_ip: 10.0.8.15
    host: tc-prod-node-01
```

部署到宿主机后，先检查完整配置，不要直接重启。

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

file_sd target 文件会按 `refresh_interval` 自动重新读取，但仍应先执行 promtool，并通过 API 验证发现结果。

如果 lifecycle 未启用或 reload 返回 403/404，核对 Compose 实际 command；必要时在变更窗口执行：

```bash
docker compose restart prometheus
```

## Target 和查询验证

```bash
curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=up'
curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=up%7Bjob%3D%22tencent-node%22%7D'
curl -fsS 'http://127.0.0.1:9090/api/v1/targets?state=active'
```

当前已验证目标应返回 `up == 1`。若为 0，检查 API 中 `lastError`，再验证宿主机 `curl http://10.250.0.101:9100/metrics`、`ip route get` 和 `wg show`。

## 数据位置

容器内 `/prometheus` 对应：

```text
/data/docker/monitoring/prometheus/data
```

其中包含 WAL、block 和元数据。不要手工编辑这些文件，也不要在运行中用普通文件复制冒充一致性备份。
