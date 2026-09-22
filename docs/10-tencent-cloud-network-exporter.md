# 腾讯云公网带宽采集

本阶段只接入腾讯云，不包含阿里云。数据链路如下：

```text
Tencent Cloud GetMonitorData
        -> tencent-cloud-network-exporter 默认每 300 秒主动批量查询并缓存
        -> /metrics (127.0.0.1:9125)
        -> Prometheus 每 30 秒抓取并写入本地 TSDB
```

Prometheus 的每次抓取只读取 exporter 内存中的缓存，不会触发腾讯云 API 调用。
Prometheus 不依赖 exporter 成功启动；即使腾讯云 API 或密钥暂时异常，现有 Node Exporter
和告警链路也应继续运行，云指标只会表现为该 scrape target 不可用。

## API 调用量与采集周期

`collection_interval_seconds` 控制一次完整采集循环，并非一次 API 请求的周期。
`GetMonitorData` 每次只能查询一个指标，一次最多批量查询 50 台实例。每轮请求数为：

```text
3 个指标 × Σ(每个 product + region 分组的实例数向上取整除以 50)
```

例如同一地域的 CVM 和 Lighthouse 各少于 50 台：每轮 6 次请求。原先每 60 秒一轮，
即 360 次/小时、30 天约 259,200 次；约 6,000 次对应运行约 16.7 小时。现在脱敏示例
使用每 300 秒一轮，预期 72 次/小时、30 天约 51,840 次。跨地域或某组超过 50 台时，
按上式增加。腾讯云控制台的“资源消耗”按主账号统计；同一主账号其他程序调用
`GetMonitorData` 也可能计入，不能仅凭控制台总量推断本 exporter 用量。

运行时可查询 `cloud_network_exporter_planned_api_requests_per_cycle` 和
`cloud_network_exporter_collection_interval_seconds`，核对预期每轮请求数和周期；
`sum(increase(cloud_network_exporter_api_requests_total{cloud="tencent"}[1h]))` 可查看
exporter 过去一小时的实际请求数。该计数器从容器最近一次启动开始累计，重启后重置。

生产 `config.yml` 若仍为 `collection_interval_seconds: 60`，仅更新仓库示例不会改变
运行周期。要降低用量，编辑生产配置为 `300`，并将 `lookback_seconds` 设为 `600`，
随后只重启 exporter：

```bash
docker compose restart tencent-cloud-network-exporter
```

5 分钟采集会降低曲线的时间分辨率；需要逐分钟数据时保留 60 秒配置。

## 指标与单位

exporter 统一暴露：

```text
cloud_network_public_receive_mbps
cloud_network_public_transmit_mbps
cloud_network_public_egress_utilization_ratio
cloud_network_metric_timestamp_seconds
cloud_network_exporter_group_up
cloud_network_exporter_last_success_timestamp_seconds
```

腾讯云 CVM 的 `WanIntraffic` / `WanOuttraffic` 本身是 Mbps。腾讯云的
[Lighthouse 监控指标文档](https://cloud.tencent.com/document/product/248/60127)将
`LighthouseIntraffic` / `LighthouseOuttraffic` 标为 MBytes/s，但 2026-09-22 13:54:00
的一次同实例核对中，API 原始入带宽为 `9.804`，控制台为 `9.804 Mbps`；旧版 exporter
乘以 8 后显示 `78.43 Mbps`。因此当前实现按实测值直接作为 Mbps，不再乘以 8。
腾讯云利用率返回百分数，exporter 除以 100 后统一为 0～1 比率。

历史上已经写入 Prometheus 的 Lighthouse 带宽样本仍是旧版的 8 倍；重新构建并启动
exporter 后的新样本才会恢复正确值。

## 监控时间与尖峰持续时间

当前 exporter 请求 `Period=60`。按腾讯云指标文档，这两个 Lighthouse 带宽指标
在 60 秒粒度使用 `max`，因此 13:54:00 的 10 秒尖峰可能成为整个 13:54 分钟的最大值。
exporter 每轮只取最近一个非空点并缓存，Prometheus 则按**抓取时间**记录缓存值；
曲线上显示的时间不是腾讯云原始指标时间。若 exporter 在 13:56 才取得 13:54 的点，
Grafana 就会在 13:56 附近显示尖峰；缓存到下一轮更新前，曲线也会保持高位。
[腾讯云 API 常见问题](https://cloud.tencent.com/document/product/248/54788)明确提醒监控数据可能延迟 1～2 分钟。

`cloud_network_metric_timestamp_seconds` 记录当前暴露值对应的原始时间，可用
`time() - cloud_network_metric_timestamp_seconds` 检查实际滞后。缩短采集周期只会减少
exporter 自身增加的等待时间，同时增加 API 调用量；不能消除云端上报延迟，也不能把
60 秒最大值还原成 10 秒曲线。要按原始时间绘制 10 秒尖峰，需要改用 `Period=10`
并将返回的所有时间点按原始时间戳写入时序库，不能仅调整 Grafana 刷新频率。

每个业务指标带有：

```text
cloud="tencent"
product="cvm|lighthouse"
region="..."
instance_id="..."
host="..."
env="..."
public_ip="..."
```

`cloud="tencent"` 由 exporter 固定写入，确保与既有 Node Exporter 的资产标签契约一致。
`instance` 是 Prometheus 自动附加的 exporter 抓取地址 `127.0.0.1:9125`，不能也不应
用于区分腾讯云实例；资产区分使用稳定的 `host + instance_id`。`public_ip` 用于展示公网
地址，但不替代 `host`，因此不要将公网 IP 写进 `host`。

真实实例 ID、资产名和公网 IP 只写入生产 `config.yml`，不提交 Git。本阶段纳管的实例均应
填写 `public_ip`；没有直接公网 IP 的资产暂不放入这份公网带宽清单。

## 最小权限

已知实例 ID 时，采集上述指标只需要：

```json
{
  "version": "2.0",
  "statement": [
    {
      "effect": "allow",
      "action": ["monitor:GetMonitorData"],
      "resource": ["*"]
    }
  ]
}
```

本实现不调用 `DescribeInstances`，不需要 Lighthouse/CVM 资源枚举权限。

## 生产文件

在监控机创建目录和文件：

```bash
install -d -m 0750 /data/docker/monitoring/tencent-cloud-network-exporter

cp exporters/tencent-cloud-network-exporter/config.yml.example \
  /data/docker/monitoring/tencent-cloud-network-exporter/config.yml

cp exporters/tencent-cloud-network-exporter/.env.example \
  /data/docker/monitoring/tencent-cloud-network-exporter/.env

chmod 0600 /data/docker/monitoring/tencent-cloud-network-exporter/.env
```

编辑 `config.yml`，按实例填写 `instance_id`、`product`、`region`、`host`、`env` 和
`public_ip`。与既有 Node Exporter target 对应的机器必须使用完全相同的 `host` 和 `env`。
编辑 `.env`，填入已经创建的腾讯云子账号密钥。不要把这两个生产文件提交到 Git。

## 从旧名称迁移

早期验证环境使用了通用名称 `cloud-network-exporter`。在首次加入阿里云 exporter 前，
将其迁移为 `tencent-cloud-network-exporter`，以隔离容器名、镜像、运行目录、密钥文件和
Prometheus `job` 标签。

先复制旧运行文件，并补齐所有实例的 `public_ip`：

```bash
install -d -m 0750 /data/docker/monitoring/tencent-cloud-network-exporter
cp -p /data/docker/monitoring/cloud-network-exporter/config.yml \
  /data/docker/monitoring/tencent-cloud-network-exporter/config.yml
cp -p /data/docker/monitoring/cloud-network-exporter/.env \
  /data/docker/monitoring/tencent-cloud-network-exporter/.env
vi /data/docker/monitoring/tencent-cloud-network-exporter/config.yml
```

同步本仓库更新后的 Compose、Prometheus 配置与 exporter 源码，并先完成后文的 build。
新旧 exporter 都监听 `127.0.0.1:9125`，不能同时运行。停止旧容器后启动新容器；如果新容器
无法启动，可立即用 `docker start cloud-network-exporter` 恢复旧容器：

```bash
docker stop cloud-network-exporter
docker compose up -d tencent-cloud-network-exporter
docker compose logs --tail=100 tencent-cloud-network-exporter
```

确认新容器的 `/metrics` 与 Prometheus target 均正常后，再删除旧容器：

```bash
docker rm cloud-network-exporter
docker image rm local/cloud-network-exporter:0.1.0
```

源码目录为 `exporters/tencent-cloud-network-exporter/`，运行配置与密钥不应放在其中。
确认新服务稳定后，仅删除旧目录中遗留的 `.env` 和 `config.yml`；生产运行文件应只保留在
`/data/docker/monitoring/tencent-cloud-network-exporter/`。容器内仍使用
`/etc/cloud-network-exporter/config.yml` 这个兼容路径，不影响外部的 Tencent 专用命名。

## 检查与启动

Compose 配置中的绝对 bind mount 要求生产文件先存在：

```bash
docker compose config
docker compose build tencent-cloud-network-exporter
docker compose up -d tencent-cloud-network-exporter
docker compose logs --tail=100 tencent-cloud-network-exporter
```

该监控机已确认默认 Docker bridge 网络无法解析外部 DNS；Compose 为 exporter 的构建步骤
设置了 `build.network: host`。它只影响 `pip install` 的构建网络，不会改动其他服务的网络模式。

先验证 exporter：

```bash
curl -fsS http://127.0.0.1:9125/metrics | grep '^cloud_network_'
```

确认三项业务指标、`cloud_network_exporter_group_up 1` 和合理的数据时间戳后，再检查并加载 Prometheus：

```bash
docker run --rm \
  -v /data/docker/monitoring/prometheus:/etc/prometheus:ro,Z \
  --entrypoint /bin/promtool \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml

curl -fsS -X POST http://127.0.0.1:9090/-/reload
```

如果运行中的旧 Prometheus 尚未启用 lifecycle：

```bash
docker kill -s HUP prometheus
```

最后查询：

```promql
up{job="tencent-cloud-network-exporter"}
cloud_network_exporter_group_up{cloud="tencent"}
cloud_network_public_receive_mbps{cloud="tencent"}
cloud_network_public_transmit_mbps{cloud="tencent"}
cloud_network_public_egress_utilization_ratio{cloud="tencent"}
```

`up=1` 只证明 Prometheus 能抓到 exporter。腾讯云 API 采集是否成功必须同时看
`cloud_network_exporter_group_up`、日志和 `cloud_network_metric_timestamp_seconds`。
