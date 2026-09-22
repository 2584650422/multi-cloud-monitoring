# Dashboard provisioning

仪表盘以文件 provisioning 的方式管理；Grafana 启动时从 `json/` 读取定义，provider 配置见 `dashboard-provider.yml`。

- `json/tencent-cloud-public-network.json`：腾讯云公网入/出带宽、出口带宽利用率和采集时效。

仪表盘数据源 UID 为 `PBFA97CFB590B2093`，与 `../datasources/prometheus.yml` 保持一致。新增仪表盘时应先在测试环境验证 JSON 和 PromQL，再提交到该目录；生产环境仅重启 Grafana 即可加载变更。
