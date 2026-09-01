# Grafana Configuration

实际仓库文件：

- [grafana/grafana.ini](../grafana/grafana.ini)
- [datasource provisioning](../grafana/provisioning/datasources/prometheus.yml)

Grafana Compose 和 datasource provisioning 当前状态为 IN PROGRESS / Investigating。

## 为什么 Grafana 也使用 host network

Prometheus 只监听宿主机 `127.0.0.1:9090`。Grafana 共享宿主机网络命名空间后，其后端访问 `127.0.0.1` 就是同一宿主机上的 Prometheus。

如果 Grafana 使用 bridge，Grafana 容器中的 `127.0.0.1` 只指向 Grafana 自身，此 datasource URL 将失败。替代方案是把两个服务放入用户定义 bridge 并让 Prometheus 监听容器网络，但这会改变现有网络和暴露面设计。

## grafana.ini

`[paths]` 与 Compose 的 `GF_PATHS_*` 保持一致：

```ini
[paths]
data = /var/lib/grafana
logs = /var/log/grafana
plugins = /var/lib/grafana/plugins
provisioning = /etc/grafana/provisioning
```

数据、日志和 provisioning 路径被显式固定，排查时不依赖镜像默认值。Grafana 监听 `0.0.0.0:3000`，因此生产访问必须由安全组、主机防火墙或后续 HTTPS 反向代理限制；不要直接对全网开放。

管理员密码不写入 ini 或 Git。通过批准的 Secret 管理方式或首次登录流程设置。

## Prometheus datasource provisioning

实际文件：

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    uid: prometheus
    type: prometheus
    access: proxy
    url: http://127.0.0.1:9090
    isDefault: true
    editable: false
```

- 固定 `uid` 便于未来 Dashboard 引用。
- `access: proxy` 表示查询由 Grafana 后端发起，而不是用户浏览器直连 Prometheus。
- `isDefault` 设为默认数据源。
- `editable: false` 防止 UI 临时修改与 Git 声明漂移。

## 部署与容器内验证

先看宿主机文件：

```bash
ls -lah /data/docker/monitoring/grafana/provisioning/datasources
sed -n '1,120p' /data/docker/monitoring/grafana/provisioning/datasources/prometheus.yml
```

再确认 Compose 展开和实际 mount：

```bash
docker compose config
docker inspect grafana --format '{{json .Mounts}}'
```

容器内验证：

```bash
docker exec grafana \
  ls -lah /etc/grafana/provisioning/datasources

docker exec grafana \
  cat /etc/grafana/provisioning/datasources/prometheus.yml

docker exec grafana \
  sh -c 'printf "%s\n" "$GF_PATHS_PROVISIONING"'

docker compose logs --tail=200 grafana
```

预期 `GF_PATHS_PROVISIONING=/etc/grafana/provisioning`，容器内文件内容应与宿主机一致。

## 连通性

host network 下可从 Grafana 容器测试宿主机 loopback：

```bash
docker exec grafana \
  sh -c 'wget -qO- http://127.0.0.1:9090/-/ready || true'
```

如果镜像中没有 `wget`，不要临时修改生产容器安装工具；在宿主机执行：

```bash
curl -fsS http://127.0.0.1:9090/-/ready
ss -lntp | grep 9090
```

## 修改 provisioning 后

Grafana 在启动阶段加载 provisioning。修改文件后执行：

```bash
docker compose restart grafana
docker compose logs --tail=200 grafana
```

随后在 UI 的 Connections / Data sources 中验证名称、UID、默认状态，并在 Explore 执行：

```promql
up
```

当前事故仍标记 `Status: Investigating`。只有采集到宿主机、mount、环境变量和日志证据后，才能在故障案例中补 Root Cause 与 Resolution。

## 数据位置

```text
/data/docker/monitoring/grafana/data
  grafana.db
  plugins/
  sessions and runtime files

/data/docker/monitoring/grafana/logs
  Grafana file logs
```

同时仍应查看 Docker stdout/stderr：

```bash
docker compose logs grafana
```
