# Dashboard 1860 Optimization

- Status: DONE（host 命名规范化仍为 TODO）
- Baseline: Node Exporter Full, Dashboard ID 1860

## 已验证前提

- Prometheus datasource 由 provisioning 自动创建。
- Grafana Explore 查询 `up` 正常。
- Dashboard 1860 已导入并显示腾讯测试节点指标。

## 标签模型

```yaml
- targets:
    - 10.250.0.101:9100
  labels:
    host: tc-test-node-01
    cloud: tencent
    env: test
    private_ip: 172.18.0.6
```

Prometheus 自动保留：

```text
instance="10.250.0.101:9100"
job="tencent-node"
```

Dashboard 的人类选择维度使用 `Cloud -> Env -> Job -> Host`。底层 `instance` 变量继续为现有 1860 Panel 提供真实 endpoint，但不作为主要展示条件。

## 变量设计

| 顺序 | Name | Label | Metric selector |
| --- | --- | --- | --- |
| 1 | `cloud` | `cloud` | `up` |
| 2 | `env` | `env` | `up{cloud=~"$cloud"}` |
| 3 | `job` | `job` | `up{cloud=~"$cloud",env=~"$env"}` |
| 4 | `host` | `host` | `up{cloud=~"$cloud",env=~"$env",job=~"$job"}` |
| 5 | 原 `node` | `instance` | `node_uname_info{cloud=~"$cloud",env=~"$env",job=~"$job",host=~"$host"}` |

所有查询变量使用 Prometheus datasource 和 `Label values` Query type。`cloud`、`env`、`job` 可启用 Multi-value 与 Include All；如果启用 All，下游 matcher 必须使用 `=~` 而不是 `=`。

原 `$node` 只隐藏、不删除。Dashboard 1860 的大量 Panel 仍使用 `instance=~"$node"`，删除或改名会让它们失效。

## 预期结果

```text
Datasource | Cloud   | Env  | Job          | Host
Prometheus | tencent | test | tencent-node | tc-test-node-01
```

底层解析为：

```text
$node = 10.250.0.101:9100
```

## 实施结果

已在 Grafana 中完成并保存：

- `cloud`：Label values `cloud`，Metric `up`。
- `env`：Label values `env`，Metric `up`，Filter `cloud=~$cloud`。
- `job`：Label values `job`，Metric `up`，Filter `cloud=~$cloud`、`env=~$env`。
- `host`：Label values `host`，Metric `up`，Filter `job=~$job`。
- `node`：隐藏变量；Label values `instance`，Metric `node_uname_info`，Filter `host=~$host`。

`node` 成功解析为 `10.250.0.101:9100`。CPU、内存、磁盘、网络和 Uptime 等 Panel 已恢复数据。Pressure 显示 `No data` 可能是目标内核或 Node Exporter 没有对应 pressure 指标，不属于变量链路故障。

Grafana 实际返回的 Host 仍把腾讯公网 IP 编进资产名称。为避免在 Git 中保存公网地址，本文不记录原值。应在生产 `targets/tencent-node.yml` 中改为类似 `tc-test-node-01`。该变更属于 Prometheus target 配置，不应在 Grafana 中伪造别名；仓库 target 已使用推荐名称。

## 验证

优化后逐项检查：

1. 顶部变量顺序正确且没有空选项。
2. 选择 `tencent / test / tencent-node / tc-test-node-01` 后所有 Panel 仍有数据。
3. Dashboard 中不存在 `No data`、变量循环依赖或 datasource 错误。
4. 刷新浏览器后变量与 Dashboard 修改仍保留。
5. 保存 Dashboard 时添加变更说明。

Dashboard provisioning 尚未实施。当前 UI 修改保存在 Grafana SQLite 中；后续应从 Grafana 导出脱敏 JSON 并纳入 Git，避免只依赖 `grafana.db`。
