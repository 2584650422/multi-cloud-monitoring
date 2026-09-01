# 路线图

## DONE

- WireGuard 测试隧道建立并完成双向连通验证。
- 腾讯测试机 Node Exporter 通过隧道提供指标。
- Prometheus 成功采集测试 Target，`up == 1`。
- Prometheus 主配置语法检查通过。

## IN PROGRESS

- 核对生产机 Compose、bind mount 和实际目录。
- 完成 Prometheus / Grafana 容器运行与持久化验证。
- 定位 Grafana Prometheus datasource provisioning 未生效问题。
- 将经过脱敏和验证的配置纳入 Git。

## PLANNED

- 接入其余阿里云与腾讯云主机。
- 统一 cloud、environment、region、instance 等标签。
- 优化 Grafana Dashboard。
- 部署 Alertmanager 并接入通知渠道。
- 部署 Blackbox Exporter，监控 HTTP、TCP、DNS 和证书。
- 接入阿里云、腾讯云监控 API，补充 EIP、公网带宽及云产品指标。
- 建立配置校验、发布和回滚流程。
