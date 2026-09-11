# Alertmanager 配置与邮件通知

本项目已在阿里监控 Hub 验证 NodeDown 与 `DiskSpaceUsageHigh`（`severity=warning|critical`）的通知链路；邮件使用中文 HTML 模板，并支持资产没有公网 IP 的情况。磁盘告警完成分级、抑制、Warning 单独通知以及 FIRING / RESOLVED 混合通知演练后，邮件模板已重构为通用告警事件布局，并已验证北京时间展示。

```text
测试 Node Exporter 停止
→ Prometheus: up = 0
→ NodeDown: Pending（for: 2m）
→ NodeDown: Firing
→ Alertmanager 接收告警
→ SMTP 发送 FIRING 邮件
→ Node Exporter 恢复
→ Prometheus: Normal
→ SMTP 发送 RESOLVED 邮件
```

真实 SMTP 主机、账户、密码、收件人均不进入 Git。仓库保留 [Alertmanager 脱敏配置](../alertmanager/alertmanager.yml.example)、[可部署模板](../alertmanager/templates/email.tmpl) 和保持展开排版的[维护源文件](../alertmanager/templates/email-edit.tmpl)；两份模板内容同步，规则定义见 [Prometheus 告警规则](09-alert-rules.md)。

## 1. 组件边界与监听地址

Alertmanager 运行在与 Prometheus 相同的 Docker Compose 中，使用 `network_mode: host`，但仅监听：

```text
127.0.0.1:9093
```

Prometheus 通过同一宿主机网络命名空间中的 `127.0.0.1:9093` 发送 Firing/Resolved 状态。9093 不需要暴露至公网或腾讯 VPC；Alertmanager UI/API 仅供监控 Hub 本机排障。

Prometheus 的顶级配置为：

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - 127.0.0.1:9093
```

这不是 scrape job：Prometheus 不抓取 Alertmanager 指标，而是把已 Firing 的告警事件推送到该地址。

## 2. 本地机密配置

在监控 Hub 上创建真实配置，而不是编辑 Git 中的 example：

```bash
cd /data/docker/monitoring
cp alertmanager/alertmanager.yml.example alertmanager/alertmanager.yml
vi alertmanager/alertmanager.yml
# Alertmanager runs as 65534:65534, so grant only its group read access.
chown root:65534 alertmanager/alertmanager.yml
chmod 0640 alertmanager/alertmanager.yml
```

至少替换这些 placeholder：

```text
<SMTP_HOST>:<SMTP_PORT>
<ALERT_FROM_ADDRESS>
<SMTP_USERNAME>
<SMTP_AUTH_PASSWORD>
<ALERT_RECIPIENT_ADDRESS>
```

`smtp_require_tls` 必须与实际 SMTP 服务要求一致。若供应商要求 STARTTLS、465 隐式 TLS、认证身份等特殊参数，应以供应商文档为准；不要把账号、授权码或 Token 贴入 issue、聊天记录或 Git。

不要把真实配置设为 `root:root 0600`：Compose 将容器以 `65534:65534` 运行，容器将无法读取 bind mount。`root:65534` 配合 `0640` 使 root 可管理文件，而 Alertmanager 仅拥有读取权限。

默认 route 具有以下语义：

| 参数 | 当前值 | 含义 |
| --- | --- | --- |
| `group_by` | `alertname`, `job`, `host` | 同一主机的同类告警归为一组，避免混淆不同资产。 |
| `group_wait` | `10s` | 新告警组首次通知前等待，便于同组告警汇集。 |
| `group_interval` | `30s` | 已通知的分组发生变化后，再次发送的最小间隔。 |
| `repeat_interval` | `1h` | 未恢复的同组告警每小时重复提醒。 |
| `send_resolved` | `true` | 之前已通知的告警恢复后发送恢复邮件。 |

### 磁盘告警的分级与抑制

当前磁盘规则的 Warning 与 Critical 使用同一个 `alertname`：

```text
DiskSpaceUsageHigh
```

它们仅通过 `severity=warning` / `severity=critical` 区分。因此 Alertmanager 可以对同一主机、同一挂载点执行抑制：

```yaml
inhibit_rules:
  # Disk：同一主机、同一挂载点
  - source_matchers:
      - alertname="DiskSpaceUsageHigh"
      - severity="critical"
    target_matchers:
      - alertname="DiskSpaceUsageHigh"
      - severity="warning"
    equal:
      - host
      - mountpoint

  # Memory：同一主机
  - source_matchers:
      - alertname="MemoryUsageHigh"
      - severity="critical"
    target_matchers:
      - alertname="MemoryUsageHigh"
      - severity="warning"
    equal:
      - host
```

Critical 是 source，Warning 是 target。磁盘只有同一 `host + mountpoint` 才会匹配；内存只要求同一 `host`。Prometheus 仍会保留两条 Firing series，抑制只阻止 Warning 邮件，不会删除规则状态。

`group_by` 刻意不包含 `severity`。当磁盘从 Critical 降回 Warning 时，Alertmanager 会把同一通知组的变化合并：邮件可能同时显示 Warning 的“正在告警”和 Critical 的“已恢复”。这是已完成验证的预期行为，不是重复通知。

新告警或同一告警组发生状态变化后，邮件不会保证即时到达：Prometheus 需等待下次 rule evaluation 与 `for`，Alertmanager 还会应用 `group_wait` 或 `group_interval`。在受控磁盘演练中，规则页面变化后约 1～2 分钟收到邮件属于预期范围，而不是网络故障。

## 3. 自定义 HTML 邮件模板

模板文件存在并不等于 Alertmanager 会加载它。Compose 必须将宿主机目录挂载到容器，并且 `alertmanager.yml` 顶层必须声明 `templates`：

```yaml
templates:
  - '/etc/alertmanager/templates/*.tmpl'
```

仓库 Compose 的对应 bind mount 为：

```yaml
- /data/docker/monitoring/alertmanager/templates:/etc/alertmanager/templates:ro,Z
```

Compose 同时为 Prometheus、Alertmanager、Grafana 挂载宿主机时区文件：

```yaml
- /etc/localtime:/etc/localtime:ro
```

这是容器运行环境的时区基线，但不能代替模板对告警时间对象的显式转换。

部署后可分别核对宿主机和容器的本地时区：

```bash
date
docker exec alertmanager date
docker exec prometheus date
docker exec grafana date
```

这些命令用于确认运行环境一致；邮件中的 `StartsAt` / `EndsAt` 仍以模板显式转换结果为准。

在监控 Hub 上创建目录并复制模板。真实模板可在本机调整，不能含 SMTP 密钥：

```bash
install -d -o root -g root -m 0755 /data/docker/monitoring/alertmanager/templates
install -o root -g root -m 0644 \
  /path/to/multi-cloud-monitoring/alertmanager/templates/email.tmpl \
  /data/docker/monitoring/alertmanager/templates/email.tmpl
```

配置中的 `headers.Subject` 与 `html` 分别引用模板定义的 `email.subject` 和 `email.html`。模板不会直接混合遍历 `.Alerts`：它分别使用 `.Alerts.Firing` 和 `.Alerts.Resolved`，显示“正在告警（N）”与“已恢复（N）”。

当前仓库以 `email-edit.tmpl` 的展开式结构维护，并将同一内容同步到可直接部署的 `email.tmpl`。生产 `templates/` 目录只能安装 `email.tmpl`：两个文件都定义 `email.subject`、`email.html`，同时被 `*.tmpl` 加载会产生重复定义。

模板以 `email.alert` 渲染单条告警，再分别遍历 `.Alerts.Firing` 与 `.Alerts.Resolved`。这样只维护一份详情布局，仍能明确显示“正在告警（N）”与“已恢复（N）”。每条告警按以下顺序展示：

```text
摘要标题
├─ 告警信息：级别、监控指标、当前值/最近告警值、触发条件、可选磁盘字段
├─ 实例信息：主机、环境、云厂商、私网 IP、可选公网 IP
├─ 时间信息：触发时间，已恢复时额外显示恢复时间
└─ 技术信息：规则标识、采集地址
```

规则 annotations 的通用数据契约为：

```yaml
annotations:
  summary: "一句话说明发生了什么"
  metric_name: "监控指标名称"
  current_value: "当前或最近告警值"
  condition: "触发阈值和持续时间"
```

`description` 不再是该模板的数据契约；磁盘的 `mountpoint`、`device`、`fstype` 继续来自指标标签，只有存在时才显示。规则内部 severity 值保持 `warning` / `critical`；展示层将它们渲染为“警告（Warning）”和“严重（Critical）”。`cloud=tencent|aliyun` 与 `env=prod|test` 也仅在展示层转换为中文。

邮件主题使用“【告警】/【恢复】+ 主机 + 指标 + 环境”的可读格式；多告警通知没有共同主机或指标时，模板会自动回退到共同摘要或 Prometheus 规则名。模板使用嵌套 table 和 inline style，避免依赖邮件客户端不稳定的 CSS；FIRING 使用红色、RESOLVED 使用绿色。

`public_ip` 是可选 target label：有公网 IP 的资产显示实际值；未定义该 label 时模板显示“无”。因此没有公网 IP 的 target 不要为了模板写入空字符串标签。

### Critical 实测后的时间显示修复

Critical 告警实测时，直接写：

```gotemplate
{{ .StartsAt }}
{{ .EndsAt }}
```

邮件可能显示类似 `2026-09-09 10:09:35 +0000 UTC`。这不是 Prometheus 规则判断错误，而是通知对象中的 `time.Time` 仍携带 UTC 信息，直接输出会保留原时区。容器 `/etc/localtime` 挂载只影响容器本地运行环境，不能可靠改变这个时间对象的格式化结果。

仓库模板改为在展示层显式转换：

```gotemplate
{{ date "2006-01-02 15:04:05" (tz "Asia/Shanghai" .StartsAt) }}（北京时间）
{{ date "2006-01-02 15:04:05" (tz "Asia/Shanghai" .EndsAt) }}（北京时间）
```

FIRING 必须保留 `StartsAt`；RESOLVED 必须同时保留 `StartsAt` 与 `EndsAt`。`EndsAt` 是恢复时间，不能为了简化模板删除。

## 4. 检查、启动与 reload

先检查 Alertmanager 配置，任何失败都不要 restart：

```bash
docker run --rm \
  -v /data/docker/monitoring/alertmanager:/etc/alertmanager:ro,Z \
  --entrypoint /bin/amtool \
  prom/alertmanager:v0.28.0 \
  check-config /etc/alertmanager/alertmanager.yml
```

然后同时检查 Compose 和 Prometheus 主配置：

```bash
cd /data/docker/monitoring
docker compose config

docker run --rm \
  -v /data/docker/monitoring/prometheus:/etc/prometheus:ro,Z \
  --entrypoint /bin/promtool \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml
```

首次部署：

```bash
docker compose up -d alertmanager
curl -fsS http://127.0.0.1:9093/-/ready
```

修改 `alertmanager.yml` 后，Compose 已启用 `--web.enable-lifecycle`，可优先热加载：

```bash
curl -fsS -X POST http://127.0.0.1:9093/-/reload
docker compose logs --tail=100 alertmanager
```

如果 reload 失败，或 Compose 中尚未启用 lifecycle，再在批准的变更窗口执行：

```bash
docker compose restart alertmanager
```

修改 `prometheus/prometheus.yml` 中的 `alerting` 段后，先运行 `promtool`，再 reload Prometheus：

```bash
curl -fsS -X POST http://127.0.0.1:9090/-/reload
curl -fsS http://127.0.0.1:9090/api/v1/alertmanagers
```

后一个 API 的 `activeAlertmanagers` 应包含 `127.0.0.1:9093`。

模板、`alertmanager.yml` 或其目录挂载变更后都要先运行上述检查；通过后对 Alertmanager reload。模板文件不会被自动轮询。

## 5. 端到端演练

仅选择已批准的测试节点，不要为验证而停止生产关键节点。

```bash
# 在测试节点
systemctl stop node_exporter

# 在监控 Hub：确认 Prometheus 告警和 Alertmanager 活动告警
curl -fsS 'http://127.0.0.1:9090/api/v1/alerts'
curl -fsS http://127.0.0.1:9093/api/v2/alerts

# 恢复测试节点
systemctl start node_exporter
```

预期：`up{job="node-exporter"}` 变为 `0`，NodeDown 先 Pending，超过两分钟进入 Firing；Alertmanager 收到 active alert 并发送 FIRING 邮件。服务恢复后 `up` 回到 `1`、Prometheus 规则页为 Normal，Alertmanager 根据 `send_resolved: true` 发送 RESOLVED 邮件。`DiskSpaceUsageHigh` 的 Warning、Critical、Critical 抑制 Warning 和 Warning 独立通知也已完成受控验证；不要通过写满生产文件系统来复现实验。

## 6. 常见排查

```bash
# Alertmanager 容器、日志与就绪状态
docker compose ps alertmanager
docker compose logs --tail=200 alertmanager
curl -fsS http://127.0.0.1:9093/-/ready

# Prometheus 是否已识别 Alertmanager
curl -fsS http://127.0.0.1:9090/api/v1/alertmanagers

# 当前活动告警
curl -fsS http://127.0.0.1:9090/api/v1/alerts
curl -fsS http://127.0.0.1:9093/api/v2/alerts

# SMTP/通知错误
docker compose logs --since=30m alertmanager 2>&1 | \
  grep -iE 'smtp|email|notify|error|tls|auth'
```

如果 Prometheus 有 Firing 但 Alertmanager API 为空，先检查 Prometheus 的 `alerting` 配置、reload 日志和 `/api/v1/alertmanagers`。如果 Alertmanager 有 active alert 但未收到邮件，优先检查 SMTP 认证、TLS 参数、发件人限制和收件邮箱的垃圾邮件目录。

当前未完成项为钉钉/Webhook 路由、CPU/内存等资源规则与告警抑制策略；不要将它们标记为已完成。
