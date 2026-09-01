# Operations Runbook

本 Runbook 面向值班与变更操作。所有 Compose 命令默认在 `/data/docker/monitoring` 执行。

## 快速健康检查

```bash
cd /data/docker/monitoring
docker compose ps
docker compose logs --tail=100 prometheus
docker compose logs --tail=100 grafana
curl -fsS http://127.0.0.1:9090/-/ready
wg show
ip route get 10.250.0.101
curl -fsS http://10.250.0.101:9100/metrics >/dev/null
```

## 容器与日志

```bash
docker compose ps
docker compose top
docker compose logs --tail=100 prometheus
docker compose logs --tail=100 grafana
docker compose logs --since=30m prometheus
docker compose logs --since=30m grafana
docker inspect prometheus --format '{{.State.Status}} {{.State.Health.Status}}'
docker inspect grafana --format '{{.State.Status}} {{.State.ExitCode}}'
```

镜像未定义 healthcheck 时 `.State.Health` 可能为空，应结合 `/-/ready`、日志和 API 判断。

## 检查 Prometheus 配置

```bash
docker run --rm \
  -v /data/docker/monitoring/prometheus:/etc/prometheus:ro,Z \
  --entrypoint /bin/promtool \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml
```

检查单独的已启用规则：

```bash
docker run --rm \
  -v /data/docker/monitoring/prometheus/rules:/rules:ro,Z \
  --entrypoint /bin/promtool \
  prom/prometheus:v3.13.2 \
  check rules /rules/*.yml
```

当 rules 目录为空时不要运行带未展开 glob 的第二条命令。

## 查看 Target

```bash
curl -fsS 'http://127.0.0.1:9090/api/v1/targets?state=active'
curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=up'
curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=up%7Bjob%3D%22tencent-node%22%7D'
```

有 `jq` 时可读性更好：

```bash
curl -fsS 'http://127.0.0.1:9090/api/v1/targets?state=active' | jq \
  '.data.activeTargets[] | {scrapeUrl, health, lastError}'
```

## WireGuard 与路由

```bash
wg show
ip -br addr show wg0
ip route
ip route get 10.250.0.101
ping -c 4 10.250.0.101
```

目标路由必须指向 `wg0`。`latest handshake` 应在有流量时更新，transfer 应双向增长。

## Node Exporter

腾讯测试节点：

```bash
systemctl status node_exporter --no-pager -l
journalctl -u node_exporter -n 100 --no-pager
ss -lntp | grep 9100
curl -fsS http://10.250.0.101:9100/metrics | head
```

## 修改 Prometheus 配置

1. 给当前文件创建带时间戳的备份，不覆盖旧备份：

   ```bash
   cp -a prometheus/prometheus.yml \
     prometheus/prometheus.yml.bak.$(date +%Y%m%d%H%M%S)
   ```

2. 修改主配置、target 或规则。
3. 运行完整 promtool 检查。
4. 通过 lifecycle reload：

   ```bash
   curl -fsS -X POST http://127.0.0.1:9090/-/reload
   ```

5. 验证日志、ready、targets 和 `up`：

   ```bash
   docker compose logs --tail=100 prometheus
   curl -fsS http://127.0.0.1:9090/-/ready
   curl -fsS 'http://127.0.0.1:9090/api/v1/targets?state=active'
   ```

不要在校验失败时 reload/restart。

## 修改 Grafana provisioning

1. 备份文件并修改。
2. `docker compose config` 检查 mount。
3. 重启单个服务：

   ```bash
   docker compose restart grafana
   ```

4. 查看启动日志：

   ```bash
   docker compose logs --tail=200 grafana
   ```

5. 检查容器内文件、UI datasource 和 Explore 中的 `up`。

不要执行 `docker compose down`，它会同时影响整个监控栈。

## 磁盘增长

```bash
du -sh /data/docker/monitoring/prometheus/data
du -sh /data/docker/monitoring/grafana/data
du -sh /data/docker/monitoring/grafana/logs
du -sh /var/lib/docker/containers 2>/dev/null
df -h /data /var/lib/docker 2>/dev/null
```

查找 Prometheus 大目录：

```bash
du -x -h --max-depth=2 /data/docker/monitoring/prometheus/data | sort -h | tail -20
```

TSDB 保留期当前为 15d。不要手工删除 WAL 或 block 来释放空间；先判断采样量、标签基数、保留期和磁盘容量。

## 备份

### 配置

配置应由 Git 保存；变更前仍可做本机快照：

```bash
tar -C /data/docker -czf \
  /data/docker/monitoring-config-$(date +%Y%m%d%H%M%S).tar.gz \
  --exclude='monitoring/prometheus/data' \
  --exclude='monitoring/grafana/data' \
  --exclude='monitoring/grafana/logs' \
  monitoring
```

备份归档不得包含 `.env`、密钥或 Token，且不应长期留在同一故障域。

### Grafana 数据

Grafana 使用 SQLite 时，优先在变更窗口停止单个 Grafana 容器再复制，避免不一致：

```bash
docker compose stop grafana
cp -a grafana/data/grafana.db \
  grafana/data/grafana.db.backup.$(date +%Y%m%d%H%M%S)
docker compose start grafana
```

停机前需获得变更授权。长期方案应使用文件系统快照或数据库一致性备份。

### Prometheus 数据

不要直接复制运行中的 WAL。可在启用 admin API 并评估安全风险后使用 TSDB snapshot，或使用支持一致性快照的存储。当前 Compose 未启用 admin API，因此生产 TSDB 备份方案为 TODO；恢复前必须验证快照完整性。

## 镜像升级

1. 记录当前镜像与 digest：

   ```bash
   docker compose images
   docker image inspect prom/prometheus:v3.13.2 --format '{{index .RepoDigests 0}}'
   docker image inspect grafana/grafana:13.2.0 --format '{{index .RepoDigests 0}}'
   ```

2. 在 Git 分支中修改固定 tag，不使用 `latest`。
3. 阅读 release notes，在非生产环境运行配置检查和启动测试。
4. 备份 Grafana 数据库，确认 Prometheus TSDB 兼容性。
5. 拉取并只更新目标服务：

   ```bash
   docker compose pull prometheus
   docker compose up -d --no-deps prometheus
   ```

6. 检查日志、ready、targets、Grafana Explore。

Grafana 同理替换服务名。升级不是只执行 `pull`；tag 不变时行为可能受本地缓存与远端 manifest 影响，所以必须记录 digest。

## 配置回滚

1. 将上一个已验证 Git 版本恢复到生产配置路径。
2. Prometheus 先运行 promtool。
3. `docker compose config`。
4. Prometheus 用 reload；Grafana provisioning 变更重启 Grafana。
5. 检查日志、Target、Explore。

## 镜像回滚

将 Compose 的 image tag/digest 改回已记录版本：

```bash
docker compose up -d --no-deps prometheus
docker compose logs --tail=200 prometheus
```

如果新版本已经执行不可逆的数据迁移，不能只降级镜像；必须按对应组件 release notes 恢复兼容备份。Grafana SQLite 尤其需要升级前备份。不要删除当前数据目录来“回滚”。
