# Prometheus 告警规则

本章记录已经落地的主机告警策略、验证方式和扩展原则。规则由 Prometheus 每 `30s` 评估；只有持续满足规则中的 `for` 时段后才进入 `Firing` 并投递给 Alertmanager。

真实生产规则可包含资产名称和特殊阈值，因此不进入公共 Git。仓库保留已启用的 [NodeDown 规则](../prometheus/rules/node-down.yml) 与脱敏的 [磁盘规则结构](../prometheus/rules/disk-space.yml.example)。部署前必须将 example 替换为经过审核的本地 `disk-space.yml`，不能直接让带 placeholder 的 example 被 Prometheus 加载。

## 当前已验证策略

| 规则 | 条件 | 持续时间 | 严重级别 | 状态 |
| --- | --- | --- | --- | --- |
| `NodeDown` | `up{job="node-exporter"} == 0` | 2m | `critical` | 已完成 Pending → Firing → 恢复邮件演练。 |
| `DiskSpaceWarning` | 可用空间计算出的使用率大于默认 80% | 10m | `warning` | 已部署并验证邮件通知。 |
| 特殊主机磁盘策略 | 指定 `host` 组使用单独阈值 | 10m | `warning` | 已部署；实际 host 与阈值仅保留在监控 Hub。 |

`severity` 是项目标签，不是 Prometheus 保留关键字。`warning` 表示需要安排处理，`critical` 表示应尽快响应；并非每个规则都必须同时实现两个级别。`NodeDown` 没有自然的“轻微掉线”状态，因此当前仅为 `critical`。

## NodeDown

```yaml
- alert: NodeDown
  expr: up{job="node-exporter"} == 0
  for: 2m
  labels:
    severity: critical
```

停掉批准测试节点的 Node Exporter 后，状态应依次为：

```text
up = 0 → Pending →（2 分钟）→ Firing → Alertmanager FIRING 邮件
恢复 exporter → up = 1 → Prometheus Normal → RESOLVED 邮件
```

`for: 2m` 是防抖窗口，避免一次抓取失败或短暂网络抖动立即产生正式通知。

## 磁盘空间告警

默认规则的计算式为：

```promql
(1 - node_filesystem_avail_bytes / node_filesystem_size_bytes) * 100 > 80
```

它使用 `avail_bytes` 而不是 `free_bytes`，更符合普通用户实际可用空间；规则排除以下伪文件系统或容器文件系统：

```text
tmpfs | devtmpfs | overlay | squashfs | nsfs | ramfs
```

生产策略将默认主机与特殊阈值主机分开：默认规则以 `host!~"..."` 排除特殊资产，特殊规则再以同一组 `host=~"..."` 单独匹配。这样一块磁盘只会命中一条 warning 策略，不会因阈值重叠产生重复邮件。

Prometheus 标签匹配语义：

| 运算符 | 含义 | 本项目用途 |
| --- | --- | --- |
| `=` | 精确匹配 | 单个确定的 `host`。 |
| `=~` | 正则匹配 | 多个特殊主机组成一组。 |
| `!~` | 正则排除 | 从默认策略排除特殊主机。 |

Prometheus 的正则匹配是全量匹配。多台主机可写为 `host=~"host-a|host-b"`；默认规则的 `host!~` 必须使用相同表达式。不要留空、也不要把公共仓库的 `<SPECIAL_HOST_REGEX>` placeholder 当作生产规则。

## 部署、检查与生效

在监控 Hub 上执行。先备份现有规则，再将审核后的本地规则放入已挂载目录：

```bash
install -o root -g root -m 0644 disk-space.yml \
  /data/docker/monitoring/prometheus/rules/disk-space.yml

docker run --rm \
  -v /data/docker/monitoring/prometheus:/etc/prometheus:ro,Z \
  --entrypoint /bin/promtool \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml

curl -fsS -X POST http://127.0.0.1:9090/-/reload
docker compose logs --tail=100 prometheus
```

任何 `promtool` 失败都停止操作；不要 reload。检查规则是否加载：

```bash
curl -fsS http://127.0.0.1:9090/api/v1/rules
curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=ALERTS'
```

## 验收与扩展

磁盘演练应只在批准的测试主机上执行，且必须预留恢复空间；不要为触发告警在生产卷上写满磁盘。验证邮件中应能看到 `host`、`instance`、`mountpoint`、`device`、`fstype`、阈值说明和当前值。

后续如增加 `DiskSpaceCritical`、CPU 或内存规则，应先定义阈值、持续时间和通知渠道。若 warning 与 critical 可同时触发，应再配置 Alertmanager `inhibit_rules`，按相同 `host` 与 `mountpoint` 抑制较低级别 warning，避免重复通知。
