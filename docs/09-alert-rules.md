# Prometheus 告警规则：NodeDown、磁盘与内存

本章记录 NodeDown、磁盘与内存告警策略。真实资产名称、私网地址和 SMTP 凭据不进入 Git；仓库中的 [磁盘规则示例](../prometheus/rules/disk-space.yml.example) 使用脱敏主机名，但规则结构、阈值层级、告警名称和标签模型与当前运行配置一致。

Prometheus 每个 `evaluation_interval` 执行一次规则评估；表达式持续满足规则的 `for` 时间后，告警才进入 `Firing` 并投递给 Alertmanager。

## 当前策略与验证状态

| 规则 | 条件 | 持续时间 | 严重级别 | 状态 |
| --- | --- | --- | --- | --- |
| `NodeDown` | `up{job="node-exporter"} == 0` | 2m | `critical` | 已完成 Pending → Firing → Normal，以及 FIRING / RESOLVED 邮件演练。 |
| `DiskSpaceUsageHigh` / Warning | 按主机组计算的磁盘使用率超过 Warning 阈值 | 10m | `warning` | 已完成独立 Warning 通知演练。 |
| `DiskSpaceUsageHigh` / Critical | 按主机组计算的磁盘使用率超过 Critical 阈值 | 5m | `critical` | 已完成受控触发和通知演练。 |
| Critical 抑制 Warning | 同一告警、主机、挂载点存在 Critical | 即时生效于通知层 | — | 已验证：Critical 正常通知，Warning 被抑制。 |
| `MemoryUsageHigh` / Warning | 内存使用率 >85% | 10m | `warning` | 已配置；端到端告警演练尚未在本仓库记录。 |
| `MemoryUsageHigh` / Critical | 内存使用率 >95% | 5m | `critical` | 已配置；端到端告警演练尚未在本仓库记录。 |

`severity` 是项目标签，不是 Prometheus 保留关键字。它表示同一个问题的严重程度：`warning` 需要安排处理，`critical` 需要尽快响应。NodeDown 没有自然的“轻微掉线”状态，因此只使用 `critical`。

## NodeDown

```yaml
- alert: NodeDown
  expr: up{job="node-exporter"} == 0
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "{{ $labels.host }} 节点采集失败"
    metric_name: "节点采集状态"
    current_value: "不可用"
    condition: "Prometheus 连续 2 分钟无法采集该节点"
```

停掉批准测试节点的 Node Exporter 后，状态应依次为：

```text
up = 0 → Pending →（2 分钟）→ Firing → Alertmanager FIRING 邮件
恢复 exporter → up = 1 → Prometheus Normal → RESOLVED 邮件
```

`for: 2m` 是防抖窗口，避免一次抓取失败或短暂网络抖动立即产生正式通知。

NodeDown 已统一到邮件模板的通用 annotations 契约，删除了会重复主机、采集地址和条件信息的 `description`。它只保留 `critical`：目标不可采集是明确可用性事件，不需要先发 Warning。

## 内存告警模型

[node-memory.yml](../prometheus/rules/node-memory.yml) 使用 `MemAvailable` 计算内存使用率：

```promql
(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100
```

不要用 `MemFree` 作为告警依据。Linux 的可回收 page cache 等并不等同于实际内存压力；`MemAvailable` 更适合判断仍可分配的内存。

当前统一阈值如下，暂不为单独主机引入特殊策略：

| 级别 | 条件 | 持续时间 |
| --- | --- | --- |
| Warning | 内存使用率 >85% | 10m |
| Critical | 内存使用率 >95% | 5m |

两个规则共用 `alert: MemoryUsageHigh`，以 `severity` 和 `threshold` 区分。annotations 与磁盘、NodeDown 使用同一契约：

```yaml
annotations:
  summary: "{{ $labels.host }} 内存使用率过高"
  metric_name: "内存使用率"
  current_value: '{{ printf "%.1f" $value }}%'
  condition: '内存使用率 > {{ $labels.threshold }}%，持续 10 分钟'
```

内存不是文件系统级指标，因此不带 `mountpoint`、`device`、`fstype`。通用邮件模板会自动隐藏这些磁盘专属行。

## 磁盘告警模型

当前磁盘规则的两级告警**共享同一个 alertname**：

```yaml
alert: DiskSpaceUsageHigh
labels:
  severity: warning     # 或 critical
```

这是当前实现的关键点。它让 Alertmanager 能把 `alertname + host + mountpoint` 识别为同一个磁盘告警对象，并在 Critical 存在时抑制 Warning 通知。

规则使用：

```promql
(1 - node_filesystem_avail_bytes / node_filesystem_size_bytes) * 100
```

它使用 `avail_bytes` 而不是 `free_bytes`，更接近普通用户可实际使用的空间。所有层级均排除：

```text
tmpfs | devtmpfs | overlay | squashfs | nsfs | ramfs
```

### 当前阈值层级

真实主机名已脱敏。示例文件使用 `demo-db-*` 和 `demo-storage-*` 代表两组特殊策略。

| 主机组 | Warning | Critical |
| --- | --- | --- |
| 默认主机 | >80%，持续 10m | >90%，持续 5m |
| 特殊组 A | >90%，持续 10m | >95%，持续 5m |
| 特殊组 B | >95%，持续 10m | >98%，持续 5m |

规则文件在每个 severity 内部用 `or` 组合默认组和两组特殊主机。默认组必须通过 `host!~` 排除所有特殊主机，特殊组再通过 `host=~` 单独匹配。这样一块磁盘在同一严重级别只命中一套阈值。

每个分支外层都使用 `label_replace()` 写入实际命中的 `threshold` 标签。例如默认 Warning 分支写入 `threshold="80"`，特殊组 A Warning 分支写入 `threshold="90"`。因此规则仍只有 Warning、Critical 两条，不需要为展示阈值拆成六条规则，也不使用 `policy` 标签。

```promql
label_replace(
  (node:metric > 80),
  "threshold", "80", "host", ".*"
)
```

这不会改变样本值；它只向命中的 alert 实例补充 `threshold`，供 `condition` annotation 和邮件模板准确显示该资产实际适用的阈值。

磁盘规则的 annotations 已收敛为：

```yaml
annotations:
  summary: "{{ $labels.host }} 磁盘使用率过高"
  metric_name: "磁盘使用率"
  current_value: '{{ printf "%.1f" $value }}%'
  condition: '磁盘使用率 > {{ $labels.threshold }}%，持续 10 分钟'
```

`description` 已移除：主机、挂载点、设备、文件系统和阈值均已有单独字段，再重复拼接成长描述会使模板冗余。

### 标签匹配的细微调整

| 运算符 | 含义 | 本项目用途 |
| --- | --- | --- |
| `=` | 精确匹配 | 固定 job：`job="node-exporter"`。 |
| `=~` | 正则匹配 | 一组特殊主机。 |
| `!~` | 正则排除 | 从默认策略排除特殊主机。 |

`label_replace()` 在本规则中不是筛选器，而是给每个 `or` 分支命中的结果追加 `threshold` 标签。

固定 job 不要写成 `job=~"node-exporter"`：两者当前结果相同，但 `=` 的语义更准确，也避免把固定值误当成模式。

Prometheus 正则采用完整匹配。多台特殊主机可写为：

```promql
host=~"demo-db-01|demo-db-02"
```

若 host 标签本身包含 IP 地址，点号必须按正则字面量转义。例如：

```promql
host=~"node-198\\.51\\.100\\.10|node-198\\.51\\.100\\.11"
```

默认规则的 `host!~` 必须使用相同的完整主机集合；否则特殊节点会同时命中默认阈值与特殊阈值。

## Critical 抑制 Warning

[Alertmanager 示例配置](../alertmanager/alertmanager.yml.example) 已包含：

```yaml
inhibit_rules:
  # Disk：同主机、同挂载点
  - source_matchers:
      - alertname="DiskSpaceUsageHigh"
      - severity="critical"
    target_matchers:
      - alertname="DiskSpaceUsageHigh"
      - severity="warning"
    equal:
      - host
      - mountpoint

  # Memory：同主机
  - source_matchers:
      - alertname="MemoryUsageHigh"
      - severity="critical"
    target_matchers:
      - alertname="MemoryUsageHigh"
      - severity="warning"
    equal:
      - host
```

含义是：同一 `DiskSpaceUsageHigh`、同一台主机、同一挂载点的 Critical 正在 Firing 时，Alertmanager 不发送对应 Warning 的通知。Prometheus 中两条规则仍可同时显示为 Firing；抑制只发生在通知层。

`mountpoint` 仅用于磁盘抑制：同一主机的 `/`、`/data`、`/backup` 是不同文件系统，`/data` 的 Critical 不能压制 `/` 的 Warning。内存告警没有 `mountpoint`，因此明确只按 `host` 匹配。

`threshold` 不能加入 `equal`：同一块磁盘的 Warning 与 Critical 本来会携带不同阈值，例如 `80` 与 `90`；它们仍应被视为同一个告警对象。

当前路由的 `group_by` 不包含 `severity`：

```yaml
group_by:
  - alertname
  - job
  - host
```

因此 Critical 降回 Warning 区间时，邮件可以同时包含：

```text
正在告警（1）  → Warning
已恢复（1）    → Critical
```

这不是重复或异常，而是同一个通知组发生了“降级”变化；模板分别使用 `.Alerts.Firing` 与 `.Alerts.Resolved` 展示两种状态。

## 已完成的受控验证

磁盘告警已经完成以下闭环：

1. 临时降低阈值和 `for`，使 Warning 与 Critical 同时 Firing。
2. 确认 Prometheus 中两条 `DiskSpaceUsageHigh` series 都存在，severity 分别为 `warning`、`critical`。
3. 确认 Alertmanager 仅发送 Critical 邮件，Warning 显示为 inhibited。
4. 提高临时 Critical 阈值，使 Warning 仍满足、Critical 恢复。
5. 确认 Warning 解除抑制并正常通知；邮件同时展示 Warning Firing 与 Critical Resolved。
6. 恢复正式阈值和 `for`：默认 80/90、特殊组 A 90/95、特殊组 B 95/98。

不要通过写满生产卷触发测试。应只在批准的测试主机上短时间调整规则阈值与 `for`，并在验证后立即恢复正式配置。

## 为什么规则页更新后邮件会晚 1～2 分钟

这通常不是网络故障。邮件需要经过多层正常等待：

```text
配置 reload
→ 等待下一次 Prometheus rule evaluation
→ Pending（等待 for）
→ Firing
→ Alertmanager group_wait / group_interval
→ SMTP 邮件
```

当前正式磁盘策略的 `for` 分别是 10m 和 5m。测试时即使临时改为 `for: 1m`，仍会受到 `evaluation_interval`、`group_wait: 10s` 和已存在告警组的 `group_interval: 30s` 影响。因此规则页面已变化后，邮件晚约 1～2 分钟属于预期行为。

`repeat_interval: 1h` 只控制没有变化的持续告警多久再次提醒，不控制首次或状态变化后的通知延迟。只有告警已 Firing、Alertmanager API 已收到事件、且超过 group 等待时间仍长期未邮件投递时，才优先排查 SMTP、DNS、网络或邮件服务端。

## 部署、检查与生效

真实生产规则保存在监控 Hub 的：

```text
/data/docker/monitoring/prometheus/rules/node-disk.yml
/data/docker/monitoring/prometheus/rules/node-memory.yml
```

先检查完整主配置，以便同时验证 `rule_files`、file_sd 和全部规则：

```bash
docker run --rm \
  -v /data/docker/monitoring/prometheus:/etc/prometheus:ro,Z \
  --entrypoint /bin/promtool \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml
```

也可以只检查目标规则文件：

```bash
docker run --rm \
  -v /data/docker/monitoring/prometheus/rules:/rules:ro,Z \
  --entrypoint /bin/promtool \
  prom/prometheus:v3.13.2 \
  check rules /rules/node-disk.yml
```

检查成功后才 reload：

```bash
curl -fsS -X POST http://127.0.0.1:9090/-/reload
docker compose logs --tail=100 prometheus
curl -fsS http://127.0.0.1:9090/api/v1/rules
```

修改 `alertmanager.yml` 中的 `inhibit_rules` 或路由后，应先用 `amtool check-config` 检查，再 reload Alertmanager。详见 [Alertmanager 配置与邮件通知](08-alertmanager-configuration.md)。

## 当前结论

磁盘告警已完成：两级阈值、特殊主机阈值、Critical 抑制 Warning、Warning 独立通知、FIRING/RESOLVED 混合邮件以及通知延迟行为验证。内存告警已按相同数据契约与两级阈值配置，后续应补充受控演练；CPU 等新规则应复用本章的标签模型和检查流程，但阈值必须单独设计与演练。
