# Dashboard 1860 优化记录

> 此文件保留 Grafana UI 调整的实施事实与验证结果，不替代 Grafana 部署或 provisioning 手册。

> 注：本记录中的 `10.250.0.101:9100` 和 `tencent-node` 是当时点对点基线的值。Gateway 切换后的当前运行状态见 [实施状态快照](implementation-status.md)，不要把本记录中的 endpoint 直接复制到后续 target 配置。

- Status: DONE（Host 变量已改为即时 Target 查询；host 命名规范化仍为 TODO）
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

Dashboard 的人类选择维度使用 `Cloud -> Env -> Host`；`job` 和 `node` 隐藏。底层 `instance` 变量继续为现有 1860 Panel 提供真实 endpoint，但不作为主要展示条件。

## 变量设计

| 顺序 | Name | Label | Metric selector |
| --- | --- | --- | --- |
| 1 | `cloud` | `cloud` | `up` |
| 2 | `env` | `env` | `up{cloud=~"$cloud"}` |
| 3 | `job` | `job` | `up{cloud=~"$cloud",env=~"$env"}` |
| 4 | `host` | `host` | `max by (host) (up{cloud=~"$cloud",env=~"$env",job=~"$job"})`（Query result） |
| 5 | 原 `node` | `instance` | `node_uname_info{cloud=~"$cloud",env=~"$env",job=~"$job",host=~"$host"}` |

`cloud`、`env`、`job` 仍使用 Label values；`host` 使用 Query result。Host 的即时查询不写 `== 1`，因此 target 仍在配置中但 `up=0` 时仍会显示。明确从 targets 删除的 target 在 Prometheus stale 后不会出现在即时结果中。所有可见变量均关闭 Multi-value 与 Include All；隐藏 job/node 也保持单选。

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
- `host`：Query result，查询 `max by (host) (up{job=~"$job",cloud=~"$cloud",env=~"$env"})`，Regex `/host="([^"]+)"/`。
- `node`：隐藏变量；Label values `instance`，Metric `node_uname_info`，Filter `host=~$host`。

当前 TX-VPN 选择成功解析为 `172.18.0.6:9100`。CPU、内存、磁盘、网络和 Uptime 等 Panel 已恢复数据。Pressure 显示 `No data` 可能是目标内核或 Node Exporter 没有对应 pressure 指标，不属于变量链路故障。

Grafana 实际返回的 Host 仍把腾讯公网 IP 编进资产名称。为避免在 Git 中保存公网地址，本文不记录原值。应在生产 `targets/tencent-node.yml` 中改为类似 `tc-test-node-01`。该变更属于 Prometheus target 配置，不应在 Grafana 中伪造别名；仓库 target 已使用推荐名称。

## 验证

优化后逐项检查：

1. 顶部变量顺序正确且没有 `All` 选项。
2. 选择 `tencent / prod / TX-VPN` 后所有 Panel 仍有数据。
3. 停止一个仍在 targets 中的 Node Exporter，Host 仍显示但 `up=0`。
4. 删除一个 target 并 reload Prometheus，等待 stale 后 Host 不再显示该节点。
5. Dashboard 中不存在变量循环依赖或 datasource 错误。
6. 刷新浏览器后变量与 Dashboard 修改仍保留。
7. 保存 Dashboard 时添加变更说明。

Dashboard provisioning 尚未实施。当前 UI 修改保存在 Grafana SQLite 中；后续应从 Grafana 导出脱敏 JSON 并纳入 Git，避免只依赖 `grafana.db`。
