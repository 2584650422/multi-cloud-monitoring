# 路线图

本文件描述产品与工程能力的演进方向，不记录每日实施状态；当前进度见 [实施记录](records/implementation-status.md)。

## 阶段一：基础主机监控

- WireGuard 点对点与 Gateway 两种跨云采集路径。
- Node Exporter、Prometheus、Alertmanager 与 Grafana。
- Target 标签、配置检查、reload 与回滚流程。

## 阶段二：资产与可视化

- 接入其余阿里云和腾讯云主机。
- 统一 `host`、`cloud`、`env`、`private_ip` 标签。
- 维护单主机详情 Dashboard，并建立多主机 Infrastructure Overview。
- 将经过脱敏的 Dashboard JSON 纳入 provisioning 和 Git。

## 阶段三：告警与探测

- Alertmanager 与 SMTP 邮件通知已完成；后续优化邮件模板，并按需增加钉钉/Webhook 路由。
- 部署 Blackbox Exporter，监控 HTTP、TCP、DNS 与证书。
- 建立主机不可达、CPU、内存、磁盘与服务可用性告警。

## 阶段四：云指标与交付治理

- 接入阿里云、腾讯云监控 API，补充 EIP、公网带宽和云产品指标。
- 建立配置校验、变更审查、发布与回滚流程。
- 引入 GitOps 或 CI，对 Prometheus 配置、Dashboard 与部署文件执行自动检查。
