# Troubleshooting Case Library

本文件记录本项目实际发生或正在处理的故障。已解决案例包含证据、根因和处理；未定位案例不提前编造结论。

## Case 1：WireGuard 无 handshake

- Status: Resolved

### 现象

腾讯端：

```text
transfer: 0 B received, 持续 sent
```

阿里端：

```text
没有 endpoint
没有 latest handshake
```

### 排查

两端先看 Peer 状态：

```bash
wg show
```

阿里端确认 UDP socket：

```bash
ss -lunp | grep 51820
```

在阿里公网接口观察 WireGuard UDP 包；实际接口名以 `ip route` 为准：

```bash
tcpdump -ni eth0 udp port 51820
```

确认 Overlay 路由：

```bash
ip route
ip route get 10.250.0.101
```

同时核对阿里云安全组入方向协议、端口和来源 CIDR。

### Root Cause

阿里云安全组错误开放了 TCP 51820；WireGuard 使用 UDP 51820。

```text
TCP 51820 != UDP 51820
```

云安全组按协议分别匹配。开放相同数字的 TCP 端口不会允许 UDP 数据报到达主机。

腾讯 Spoke 主动发包，但 UDP 被安全组丢弃，阿里 WireGuard 从未收到经过认证的握手包。WireGuard 不会从未收到的包学习对端 endpoint，因此阿里端没有 endpoint，也没有 latest handshake；腾讯端则只增加 sent，received 保持 0。

### Resolution

阿里安全组改为仅允许腾讯测试机公网 IP/32 到 UDP 51820。随后产生 Ping 流量，`latest handshake` 出现并且收发字节双向增长。

## Case 2：Prometheus rule 配置解析失败

- Status: Resolved

### 错误

```text
field global not found in type rulefmt.RuleGroups
field scrape_configs not found in type rulefmt.RuleGroups
```

主配置检查显示成功，但 `/etc/prometheus/rules/prometheus.yml` 检查失败。

### Root Cause

Prometheus 主配置的副本误放入 `rules/`，而主配置中的 glob 会将所有 `rules/*.yml` 当作规则文件解析。

这是两种不同 schema：

```text
主配置 prometheus.yml
  global
  scrape_configs
  rule_files

规则文件
  groups
    rules
      alert
      expr
```

规则解析器当然不认识顶层 `global` 和 `scrape_configs`，所以报 `field ... not found in type rulefmt.RuleGroups`。

### Resolution

将误放的主配置移出 `rules/`。如果尚未启用告警，rules 目录可以为空；不要用一个假的规则文件占位。

验证：

```bash
docker run --rm \
  -v /data/docker/monitoring/prometheus:/etc/prometheus:ro,Z \
  --entrypoint /bin/promtool \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml
```

## Case 3：Grafana datasource provisioning 未生效

- Status: Closed / Not an incident
- Root Cause: 操作时看错了 Grafana 数据源列表；provisioning 实际已经成功创建 Prometheus datasource。
- Resolution: 未修改配置。在 Grafana UI 中确认数据源存在，并通过 Explore 查询 `up` 验证连通性。

本次不需要修复，但保留以下标准证据链。以后不能仅凭 UI 第一眼未显示就判断是 YAML、mount、路径或网络问题。

### 1. 宿主机文件

```bash
ls -lah /data/docker/monitoring/grafana/provisioning/datasources
sed -n '1,160p' \
  /data/docker/monitoring/grafana/provisioning/datasources/prometheus.yml
```

确认文件名、权限、缩进、`apiVersion` 和 datasource 列表。

### 2. Compose 展开与 mount

```bash
cd /data/docker/monitoring
docker compose config
docker inspect grafana --format '{{json .Mounts}}'
```

确认宿主机目录实际挂载到 `/etc/grafana/provisioning/datasources`，且没有被另一个更上层或更下层 mount 遮蔽。

### 3. 容器内实际内容

```bash
docker exec grafana \
  ls -lah /etc/grafana/provisioning/datasources

docker exec grafana \
  cat /etc/grafana/provisioning/datasources/prometheus.yml
```

宿主机存在不代表容器内一定可见；路径错误、SELinux label 或 Compose 未重建都可能造成差异。

### 4. Grafana provisioning 路径

```bash
docker exec grafana \
  sh -c 'printf "GF_PATHS_PROVISIONING=%s\n" "$GF_PATHS_PROVISIONING"'

docker exec grafana \
  sh -c 'grep -n "^provisioning" /etc/grafana/grafana.ini || true'
```

预期为 `/etc/grafana/provisioning`。

### 5. 启动日志

```bash
docker compose logs --tail=300 grafana
docker compose logs grafana | grep -iE 'provision|datasource|error|warn'
```

重点保存 Grafana 解析错误、权限错误、重复 UID、文件不可读等原始日志。

### 6. Prometheus connectivity

```bash
curl -fsS http://127.0.0.1:9090/-/ready
ss -lntp | grep 9090
```

如果 datasource 已创建但 Save & test/Explore 失败，才重点检查连通性。datasource 根本没创建时，先解决 provisioning 加载问题。

### 7. 重启加载

确认文件和路径正确后，在批准的变更窗口只重启 Grafana：

```bash
docker compose restart grafana
docker compose logs --tail=200 grafana
```

本案例的关键经验是：先确认 UI、Explore 和容器内 provisioning 事实，再决定是否修改声明式配置；不要因为误判删除可复现的数据源配置。

## Case 4：磁盘 Critical 邮件时间显示 UTC、表格内框线不明显

- Status: Resolved and verified

### 现象

完成 `DiskSpaceUsageHigh{severity="critical"}` 受控演练后，邮件正文出现两类展示问题：

```text
开始时间：2026-09-09 10:09:35.496 +0000 UTC
```

同时，部分邮箱只显示表格外框，单元格之间的横线和竖线不明显。

### 原因

模板直接输出 `.StartsAt` / `.EndsAt` 时，会按告警对象携带的 UTC 时区格式化；这不是规则触发时间错误。`/etc/localtime` 挂载可以统一容器运行环境，但不能保证 Alertmanager 的时间对象在模板输出时自动转换。仅设置容器 `TZ` 也不能替代展示层转换。

邮件客户端对 HTML `border="1"` 的支持不完全一致，只给 `<table>` 设置边框时，内部 `<td>` 边框可能被弱化。

### 修复

最终模板使用 `tz` + `date` 在展示层转换时间：

```gotemplate
{{ date "2006-01-02 15:04:05" (tz "Asia/Shanghai" .StartsAt) }}（北京时间）
{{ date "2006-01-02 15:04:05" (tz "Asia/Shanghai" .EndsAt) }}（北京时间）
```

重构后的模板还将单条事件拆为“告警信息、实例信息、时间信息、技术信息”四个区块；FIRING 与 RESOLVED 复用 `email.alert`，但仍分别分组展示。用于邮件展示的通用 annotations 是 `summary`、`metric_name`、`current_value`、`condition`；已移除冗余的 `description`。

表格单元格继续使用显式边框，例如：

```html
style="border:1px solid #bdbdbd; padding:7px;"
```

FIRING 区块保留 `StartsAt`；RESOLVED 区块保留 `StartsAt` 和 `EndsAt`。生产目录只能放一个定义 `email.subject` / `email.html` 的 `*.tmpl` 文件，避免 `email.tmpl` 与维护源文件 `email-edit.tmpl` 同时加载产生重复定义。

### 验证

```bash
docker run --rm \
  -v /data/docker/monitoring/alertmanager:/etc/alertmanager:ro,Z \
  --entrypoint /bin/amtool \
  prom/alertmanager:v0.28.0 \
  check-config /etc/alertmanager/alertmanager.yml

docker compose restart alertmanager
docker compose logs --tail=200 alertmanager
```

已通过受控 Critical、Warning 单独通知和 Critical 恢复后的混合通知验证：邮件显示 `（北京时间）`，FIRING/RESOLVED 分组、内部表格线与恢复时间均正常。

## 通用：容器启动失败

```bash
docker compose ps -a
docker compose logs --tail=200 <service>
docker inspect <container> --format '{{json .State}}'
docker inspect <container> --format '{{json .Mounts}}'
ss -lntp | grep -E ':9090|:3000'
ls -ld /data/docker/monitoring/<component>/*
```

常见类别是端口被旧 systemd 服务占用、bind mount 文件变成目录、UID 无写权限、SELinux 拒绝、配置解析失败或镜像架构不匹配。必须以日志和 inspect 证据定位，不要用 `chmod 777` 或删除数据绕过。
