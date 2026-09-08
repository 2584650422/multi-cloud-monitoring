#!/usr/bin/env bash

set -Eeuo pipefail

# Node Exporter 安装/卸载脚本。
#
# 用法：
#   ./install-node-exporter.sh install              # 安装（省略 install 也可以）
#   ./install-node-exporter.sh uninstall            # 卸载本机 Node Exporter
#
# install 会精确监听目标节点的私网 IP:9100；可按需指定网卡或地址：
#   NETWORK_INTERFACE=ens192 LISTEN_IP=172.18.0.28 ./install-node-exporter.sh install
#
# uninstall 只处理本机服务、systemd 单元和二进制。Prometheus target 应在监控机单独删除。

# 想快速创建然后执行脚本可以使用如下方法
# cat > install-node-exporter.sh <<'SCRIPT_EOF'
# 脚本内容
# SCRIPT_EOF
# chmod 0700 /root/install-node-exporter.sh && /root/install-node-exporter.sh
# rm -rf /root/install-node-exporter.sh

NODE_EXPORTER_VERSION="1.11.1"
NETWORK_INTERFACE="${NETWORK_INTERFACE:-eth0}"
LISTEN_IP="${LISTEN_IP:-}"
INSTALL_DIR="/usr/local/bin"
SERVICE_FILE="/etc/systemd/system/node_exporter.service"
RUN_USER="node_exporter"
RUN_GROUP="node_exporter"
ACTION="${1:-install}"

log() {
  printf '[node_exporter-install] %s\n' "$*"
}

fail() {
  printf '[node_exporter-install] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  install-node-exporter.sh [install]
  install-node-exporter.sh uninstall

Environment variables for install:
  NETWORK_INTERFACE=eth0    Interface used to discover the private IPv4 address.
  LISTEN_IP=172.18.0.28     Explicit private IPv4 address on NETWORK_INTERFACE.

uninstall removes only the local service, unit file, and binary. It does not
remove the Prometheus target, historical metrics, system user, or backups.
EOF
}

case "${ACTION}" in
  --help|-h)
    usage
    exit 0
    ;;
  install|--install)
    ACTION="install"
    ;;
  uninstall|--uninstall)
    ACTION="uninstall"
    ;;
  *)
    usage >&2
    fail "不支持的参数: ${ACTION}"
    ;;
esac

if [[ "${EUID}" -ne 0 ]]; then
  fail "请使用 root 执行此脚本"
fi

uninstall_node_exporter() {
  log "停止并删除本机 Node Exporter"

  if [[ -f "${SERVICE_FILE}" ]] || systemctl cat node_exporter >/dev/null 2>&1; then
    systemctl disable --now node_exporter 2>/dev/null || \
      systemctl stop node_exporter 2>/dev/null || true
  fi

  rm -f -- "${SERVICE_FILE}" "${INSTALL_DIR}/node_exporter"
  systemctl daemon-reload
  systemctl reset-failed node_exporter 2>/dev/null || true

  if systemctl is-active --quiet node_exporter; then
    fail "node_exporter 仍处于运行状态；请检查 systemctl status node_exporter"
  fi

  log "本机 Node Exporter 已移除"
  printf '%s\n' '提示：Prometheus target、历史指标、node_exporter 用户和安装备份均未删除。'
}

if [[ "${ACTION}" == "uninstall" ]]; then
  uninstall_node_exporter
  exit 0
fi

[[ "${NETWORK_INTERFACE}" =~ ^[[:alnum:]_.:-]+$ ]] || \
  fail "NETWORK_INTERFACE 格式无效: ${NETWORK_INTERFACE}"

command -v ip >/dev/null 2>&1 || fail "缺少 ip 命令"
command -v tar >/dev/null 2>&1 || fail "缺少 tar 命令"
command -v sha256sum >/dev/null 2>&1 || fail "缺少 sha256sum 命令"
command -v systemctl >/dev/null 2>&1 || fail "当前系统不支持 systemd"

ip link show dev "${NETWORK_INTERFACE}" >/dev/null 2>&1 || \
  fail "网卡 ${NETWORK_INTERFACE} 不存在；可用 NETWORK_INTERFACE=网卡名 覆盖"

if [[ -z "${LISTEN_IP}" ]]; then
  LISTEN_IP="$({
    ip -4 -o addr show dev "${NETWORK_INTERFACE}" scope global 2>/dev/null || true
  } | awk '
    {
      sub(/\/.*/, "", $4)
      split($4, octet, ".")
      if (octet[1] == 10 ||
          (octet[1] == 172 && octet[2] >= 16 && octet[2] <= 31) ||
          (octet[1] == 192 && octet[2] == 168)) {
        print $4
        exit
      }
    }
  ')"
fi

[[ "${LISTEN_IP}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || \
  fail "无法从 ${NETWORK_INTERFACE} 获取 RFC1918 私网 IPv4 地址；可用 LISTEN_IP=x.x.x.x 覆盖"

if ! awk -F. '
  $1 == 10 ||
  ($1 == 172 && $2 >= 16 && $2 <= 31) ||
  ($1 == 192 && $2 == 168) {found = 1}
  END {exit !found}
' <<<"${LISTEN_IP}"; then
  fail "拒绝监听非 RFC1918 地址 ${LISTEN_IP}；请确认节点私网地址和网卡"
fi

if ! ip -4 -o addr show dev "${NETWORK_INTERFACE}" | awk '{sub(/\/.*/, "", $4); print $4}' | grep -Fxq "${LISTEN_IP}"; then
  fail "监听地址 ${LISTEN_IP} 不属于网卡 ${NETWORK_INTERFACE}"
fi

case "$(uname -m)" in
  x86_64|amd64)
    RELEASE_ARCH="amd64"
    EXPECTED_SHA256="9f5ea48e5bc7b656f8a91a32e7d7deb89f70f73dabd0d974418aca15f37d6810"
    ;;
  aarch64|arm64)
    RELEASE_ARCH="arm64"
    EXPECTED_SHA256="ba1886efbd76cb96b0087c695ea8d1b9cb6e8aa946c996d744e9ee16c8e3591a"
    ;;
  *)
    fail "不支持的 CPU 架构: $(uname -m)"
    ;;
esac

ARCHIVE_NAME="node_exporter-${NODE_EXPORTER_VERSION}.linux-${RELEASE_ARCH}.tar.gz"
ARCHIVE_PATH="/root/${ARCHIVE_NAME}"
DOWNLOAD_URL="https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/${ARCHIVE_NAME}"
WORK_DIR="$(mktemp -d /root/node_exporter-install.XXXXXX)"
BACKUP_SUFFIX="$(date +%Y%m%d%H%M%S)"

cleanup() {
  if [[ "${WORK_DIR}" == /root/node_exporter-install.* ]]; then
    rm -rf -- "${WORK_DIR}"
  fi
  rm -f -- "${ARCHIVE_PATH}" "${ARCHIVE_PATH}.part"
}
trap cleanup EXIT

download() {
  local url="$1"
  local output="$2"

  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --connect-timeout 15 -o "${output}" "${url}"
  elif command -v wget >/dev/null 2>&1; then
    wget --tries=3 --timeout=15 -O "${output}" "${url}"
  else
    fail "缺少 curl 或 wget，无法下载安装包"
  fi
}

if [[ -f "${ARCHIVE_PATH}" ]]; then
  log "使用已有安装包 ${ARCHIVE_PATH}"
else
  log "未找到 ${ARCHIVE_PATH}，开始下载"
  download "${DOWNLOAD_URL}" "${ARCHIVE_PATH}.part"
  mv -- "${ARCHIVE_PATH}.part" "${ARCHIVE_PATH}"
fi

log "使用 Node Exporter ${NODE_EXPORTER_VERSION} 官方 SHA256 校验安装包"
printf '%s  %s\n' "${EXPECTED_SHA256}" "${ARCHIVE_PATH}" | sha256sum -c -

log "解压并安装 Node Exporter ${NODE_EXPORTER_VERSION}"
tar -xzf "${ARCHIVE_PATH}" -C "${WORK_DIR}"
EXTRACTED_BINARY="${WORK_DIR}/node_exporter-${NODE_EXPORTER_VERSION}.linux-${RELEASE_ARCH}/node_exporter"
[[ -x "${EXTRACTED_BINARY}" ]] || fail "解压后未找到 node_exporter 二进制文件"

if ! getent group "${RUN_GROUP}" >/dev/null 2>&1; then
  groupadd --system "${RUN_GROUP}"
fi

if ! id "${RUN_USER}" >/dev/null 2>&1; then
  useradd --system --gid "${RUN_GROUP}" --no-create-home --shell /sbin/nologin "${RUN_USER}"
fi

if [[ -f "${INSTALL_DIR}/node_exporter" ]]; then
  cp -a "${INSTALL_DIR}/node_exporter" \
    "${INSTALL_DIR}/node_exporter.backup.${BACKUP_SUFFIX}"
fi

if [[ -f "${SERVICE_FILE}" ]]; then
  cp -a "${SERVICE_FILE}" "${SERVICE_FILE}.backup.${BACKUP_SUFFIX}"
fi

install -o root -g root -m 0755 "${EXTRACTED_BINARY}" "${INSTALL_DIR}/node_exporter"

cat >"${WORK_DIR}/node_exporter.service" <<EOF
[Unit]
Description=Prometheus Node Exporter
Documentation=https://github.com/prometheus/node_exporter
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
ExecStart=${INSTALL_DIR}/node_exporter --web.listen-address=${LISTEN_IP}:9100
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF

install -o root -g root -m 0644 "${WORK_DIR}/node_exporter.service" "${SERVICE_FILE}"

log "重新加载 systemd 并启动服务"
systemctl daemon-reload
systemctl enable node_exporter
systemctl restart node_exporter

if ! systemctl is-active --quiet node_exporter; then
  systemctl status node_exporter --no-pager -l || true
  fail "node_exporter 启动失败；请查看 journalctl -u node_exporter"
fi

metrics_ready() {
  local attempt

  for attempt in {1..10}; do
    if command -v curl >/dev/null 2>&1; then
      curl -fsS --max-time 2 "http://${LISTEN_IP}:9100/metrics" \
        >/dev/null 2>&1 && return 0
    else
      wget -q -T 2 -O /dev/null "http://${LISTEN_IP}:9100/metrics" \
        >/dev/null 2>&1 && return 0
    fi

    sleep 1
  done

  return 1
}

log "等待 metrics 监听就绪（最多 10 秒）"
if ! metrics_ready; then
  systemctl status node_exporter --no-pager -l || true
  fail "服务已启动，但等待 10 秒后本机 metrics 测试仍失败"
fi

INSTALLED_VERSION="$(${INSTALL_DIR}/node_exporter --version 2>&1 | sed -n '1s/.*version \([^ ]*\).*/\1/p')"
[[ "${INSTALLED_VERSION}" == "${NODE_EXPORTER_VERSION}" ]] || \
  fail "安装版本不符合预期: ${INSTALLED_VERSION}"

log "安装完成，临时解压目录和 ${ARCHIVE_PATH} 将被删除"
printf '\n监听地址: %s:9100\n' "${LISTEN_IP}"
printf '本机测试: curl -fsS http://%s:9100/metrics | head\n' "${LISTEN_IP}"
printf 'Prometheus target: %s:9100\n' "${LISTEN_IP}"
printf '远端验证前请确认安全组/防火墙仅允许监控 Gateway 访问 TCP/9100。\n'
