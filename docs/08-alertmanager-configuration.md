# Alertmanager 配置与邮件通知

本项目已在阿里监控 Hub 验证以下完整链路：

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

真实 SMTP 主机、账户、密码、收件人均不进入 Git。仓库只保留 [脱敏模板](../alertmanager/alertmanager.yml.example)。

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

模板的默认 route 具有以下语义：

| 参数 | 当前值 | 含义 |
| --- | --- | --- |
| `group_by` | `alertname`, `job`, `host` | 同一主机的同类告警归为一组，避免混淆不同资产。 |
| `group_wait` | `10s` | 新告警组首次通知前等待，便于同组告警汇集。 |
| `group_interval` | `30s` | 已通知的分组发生变化后，再次发送的最小间隔。 |
| `repeat_interval` | `1h` | 未恢复的同组告警每小时重复提醒。 |
| `send_resolved` | `true` | 之前已通知的告警恢复后发送恢复邮件。 |

## 3. 检查、启动与 reload

先检查 Alertmanager 配置，任何失败都不要 restart：

```bash
docker run --rm \
  -v /data/docker/monitoring/alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro,Z \
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

## 4. 端到端演练

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

预期：`up{job="node-exporter"}` 变为 `0`，NodeDown 先 Pending，超过两分钟进入 Firing；Alertmanager 收到 active alert 并发送 FIRING 邮件。服务恢复后 `up` 回到 `1`、Prometheus 规则页为 Normal，Alertmanager 根据 `send_resolved: true` 发送 RESOLVED 邮件。

## 5. 常见排查

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

邮件模板优化、钉钉/Webhook 路由和 CPU/内存/磁盘规则属于后续工作；不要将它们标记为已完成。
