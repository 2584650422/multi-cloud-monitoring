#!/usr/bin/env python3
"""Cache Tencent Cloud public-network metrics for Prometheus scraping."""

from __future__ import annotations

import argparse
import logging
import math
import os
import signal
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml
from prometheus_client import Counter, Gauge, REGISTRY, start_http_server
from prometheus_client.core import GaugeMetricFamily
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.lighthouse.v20200324 import lighthouse_client, models as lighthouse_models
from tencentcloud.monitor.v20180724 import models, monitor_client


LOG = logging.getLogger("tencent-cloud-network-exporter")
LABELS = (
    "cloud",
    "product",
    "region",
    "instance_id",
    "host",
    "env",
    "public_ip",
)
GROUP_LABELS = ("cloud", "product", "region")
MAX_INSTANCES_PER_REQUEST = 50
MAX_LIGHTHOUSE_INSTANCES_PER_REQUEST = 100
METRICS_PER_PRODUCT = {"cvm": 4, "lighthouse": 3}


BUSINESS_METRIC_LABELS = (*LABELS, "source_timestamped")


BUSINESS_METRICS = {
    "cloud_network_public_receive_mbps": (
        "Public network receive bandwidth in megabits per second.",
    ),
    "cloud_network_public_transmit_mbps": (
        "Public network transmit bandwidth in megabits per second.",
    ),
    "cloud_network_public_egress_utilization_ratio": (
        "Public network egress bandwidth utilization as a ratio from 0 to 1.",
    ),
    "cloud_network_public_transmit_megabytes": (
        "Public network transmit traffic in megabytes during the Tencent Cloud source period.",
    ),
}


class TimestampedBusinessMetrics:
    """Expose Tencent bandwidth samples with their source timestamps."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.samples: dict[str, dict[tuple[str, ...], tuple[float, int]]] = {
            name: {} for name in BUSINESS_METRICS
        }

    def update(
        self, metric: str, labels: tuple[str, ...], value: float, timestamp: int
    ) -> None:
        with self.lock:
            self.samples[metric][labels] = (value, timestamp)

    def collect(self) -> Iterable[GaugeMetricFamily]:
        with self.lock:
            snapshot = {
                name: values.copy() for name, values in self.samples.items()
            }
        for name, (documentation,) in BUSINESS_METRICS.items():
            family = GaugeMetricFamily(name, documentation, labels=BUSINESS_METRIC_LABELS)
            for labels, (value, timestamp) in snapshot[name].items():
                family.add_metric(labels, value, timestamp=timestamp)
            yield family


TIMESTAMPED_BUSINESS_METRICS = TimestampedBusinessMetrics()
REGISTRY.register(TIMESTAMPED_BUSINESS_METRICS)
METRIC_TIMESTAMP = Gauge(
    "cloud_network_metric_timestamp_seconds",
    "Timestamp of the Tencent Cloud data point currently exposed.",
    (*LABELS, "metric"),
)
GROUP_UP = Gauge(
    "cloud_network_exporter_group_up",
    "Whether the last collection of all configured metrics for a group succeeded.",
    GROUP_LABELS,
)
LAST_GROUP_SUCCESS = Gauge(
    "cloud_network_exporter_last_success_timestamp_seconds",
    "Unix timestamp of the last fully successful collection for a group.",
    GROUP_LABELS,
)
API_REQUESTS = Counter(
    "cloud_network_exporter_api_requests_total",
    "Tencent Cloud API requests made by the exporter.",
    (*GROUP_LABELS, "metric", "result"),
)
COLLECTION_ERRORS = Counter(
    "cloud_network_exporter_collection_errors_total",
    "Collection errors grouped by Tencent Cloud product and region.",
    GROUP_LABELS,
)
PLANNED_API_REQUESTS_PER_CYCLE = Gauge(
    "cloud_network_exporter_planned_api_requests_per_cycle",
    "Expected Tencent Cloud API requests in each collection cycle, before errors.",
)
COLLECTION_INTERVAL = Gauge(
    "cloud_network_exporter_collection_interval_seconds",
    "Configured interval between collection cycle starts in seconds.",
)
TENCENT_MONITOR_API_USAGE = Gauge(
    "cloud_tencent_monitor_api_usage_number",
    "Tencent Cloud Monitor API usage number returned by DescribeMonitorResourceInfo.",
    ("cloud",),
)
TENCENT_MONITOR_API_QUOTA = Gauge(
    "cloud_tencent_monitor_api_monthly_quota",
    "Configured monthly Tencent Cloud Monitor API request quota.",
    ("cloud",),
)
TENCENT_MONITOR_API_REMAINING = Gauge(
    "cloud_tencent_monitor_api_remaining_number",
    "Estimated remaining Tencent Cloud Monitor API requests in the configured quota.",
    ("cloud",),
)
TENCENT_MONITOR_API_USAGE_PERCENT = Gauge(
    "cloud_tencent_monitor_api_usage_percent",
    "Tencent Cloud Monitor API usage as a percentage of the configured monthly quota.",
    ("cloud",),
)
TENCENT_MONITOR_API_LAST_SUCCESS = Gauge(
    "cloud_tencent_monitor_api_last_success_timestamp_seconds",
    "Unix timestamp of the last successful Tencent Cloud Monitor API usage query.",
    ("cloud",),
)
TENCENT_MONITOR_API_UP = Gauge(
    "cloud_tencent_monitor_api_up",
    "Whether the last Tencent Cloud Monitor API usage query succeeded.",
    ("cloud",),
)
LIGHTHOUSE_TRAFFIC_USED = Gauge(
    "cloud_lighthouse_traffic_used_bytes",
    "Traffic consumed by the Lighthouse instance's returned traffic packages in bytes.",
    LABELS,
)
LIGHTHOUSE_TRAFFIC_TOTAL = Gauge(
    "cloud_lighthouse_traffic_total_bytes",
    "Total allowance of the Lighthouse instance's returned traffic packages in bytes.",
    LABELS,
)
LIGHTHOUSE_TRAFFIC_REMAINING = Gauge(
    "cloud_lighthouse_traffic_remaining_bytes",
    "Remaining allowance of the Lighthouse instance's returned traffic packages in bytes.",
    LABELS,
)
LIGHTHOUSE_TRAFFIC_OVERFLOW = Gauge(
    "cloud_lighthouse_traffic_overflow_bytes",
    "Traffic exceeding the Lighthouse instance's returned traffic packages in bytes.",
    LABELS,
)
LIGHTHOUSE_TRAFFIC_USAGE_PERCENT = Gauge(
    "cloud_lighthouse_traffic_usage_percent",
    "Consumed Lighthouse traffic package allowance as a percentage; values over 100 are possible after overflow.",
    LABELS,
)


@dataclass(frozen=True)
class InstanceConfig:
    instance_id: str
    product: str
    region: str
    host: str
    env: str
    public_ip: str

    def labels(self) -> tuple[str, ...]:
        return (
            "tencent",
            self.product,
            self.region,
            self.instance_id,
            self.host,
            self.env,
            self.public_ip,
        )


@dataclass(frozen=True)
class ProductSpec:
    namespace: str
    receive_metric: str
    transmit_metric: str
    utilization_metric: str
    transmit_traffic_metric: str | None
    bandwidth_multiplier: float


PRODUCTS = {
    "cvm": ProductSpec(
        namespace="QCE/CVM",
        receive_metric="WanIntraffic",
        transmit_metric="WanOuttraffic",
        utilization_metric="Outratio",
        transmit_traffic_metric="AccOuttraffic",
        bandwidth_multiplier=1.0,
    ),
    "lighthouse": ProductSpec(
        namespace="QCE/LIGHTHOUSE",
        receive_metric="LighthouseIntraffic",
        transmit_metric="LighthouseOuttraffic",
        utilization_metric="LighthouseOutratio",
        transmit_traffic_metric=None,
        # GetMonitorData 返回 9.804，对应控制台数据点为 9.804 Mbps，时间为2026-09-22 13:54:00 +08:00。
        # 发布的 MB/s 单位与此 API 观测值不一致；乘以 8 产生了错误的仪表板数据点 78.432 Mbps。
        # bandwidth_multiplier=8.0,
        bandwidth_multiplier=1.0,
    ),
}


def require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    config = require_mapping(config, "configuration")

    raw_instances = config.get("instances")
    if not isinstance(raw_instances, list) or not raw_instances:
        raise ValueError("instances must be a non-empty list")

    instances: list[InstanceConfig] = []
    identities: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(raw_instances):
        item = require_mapping(raw, f"instances[{index}]")
        required = ("instance_id", "product", "region", "host", "env", "public_ip")
        missing = [key for key in required if not str(item.get(key, "")).strip()]
        if missing:
            raise ValueError(f"instances[{index}] is missing: {', '.join(missing)}")
        instance = InstanceConfig(**{key: str(item[key]).strip() for key in required})
        if instance.product not in PRODUCTS:
            raise ValueError(
                f"instances[{index}].product must be one of: {', '.join(PRODUCTS)}"
            )
        identity = (instance.product, instance.region, instance.instance_id)
        if identity in identities:
            raise ValueError(f"duplicate instance: {'/'.join(identity)}")
        identities.add(identity)
        instances.append(instance)

    interval = int(config.get("collection_interval_seconds", 300))
    lookback = int(config.get("lookback_seconds", 600))
    if interval < 60:
        raise ValueError("collection_interval_seconds must be at least 60")
    if lookback < 120:
        raise ValueError("lookback_seconds must be at least 120")

    tencent = require_mapping(config.get("tencent_cloud"), "tencent_cloud")
    secret_id_env = str(tencent.get("secret_id_env", "TENCENTCLOUD_SECRET_ID"))
    secret_key_env = str(tencent.get("secret_key_env", "TENCENTCLOUD_SECRET_KEY"))
    secret_id = os.environ.get(secret_id_env)
    secret_key = os.environ.get(secret_key_env)
    if not secret_id or not secret_key:
        raise ValueError(
            f"Tencent Cloud credentials must be set in {secret_id_env} and {secret_key_env}"
        )

    monitor_api_monthly_quota = int(tencent.get("monitor_api_monthly_quota", 1_000_000))
    if monitor_api_monthly_quota <= 0:
        raise ValueError("tencent_cloud.monitor_api_monthly_quota must be positive")

    return {
        "listen_address": str(config.get("listen_address", "127.0.0.1")),
        "listen_port": int(config.get("listen_port", 9125)),
        "collection_interval_seconds": interval,
        "lookback_seconds": lookback,
        "request_timeout_seconds": int(tencent.get("request_timeout_seconds", 15)),
        "monitor_api_monthly_quota": monitor_api_monthly_quota,
        "secret_id": secret_id,
        "secret_key": secret_key,
        "instances": instances,
    }

def chunks(items: list[InstanceConfig], size: int) -> Iterable[list[InstanceConfig]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def planned_requests_per_cycle(instances: list[InstanceConfig]) -> int:
    group_sizes: dict[tuple[str, str], int] = defaultdict(int)
    for instance in instances:
        group_sizes[(instance.product, instance.region)] += 1
    monitor_requests = sum(
        METRICS_PER_PRODUCT[product] * math.ceil(size / MAX_INSTANCES_PER_REQUEST)
        for (product, _region), size in group_sizes.items()
    )
    traffic_package_requests = sum(
        math.ceil(size / MAX_LIGHTHOUSE_INSTANCES_PER_REQUEST)
        for (product, _region), size in group_sizes.items()
        if product == "lighthouse"
    )
    return monitor_requests + traffic_package_requests + 1


def latest_value(data_point: Any) -> tuple[float, int] | None:
    timestamps = list(data_point.Timestamps or [])
    values = list(data_point.Values or [])
    for timestamp, value in reversed(list(zip(timestamps, values))):
        if value is not None:
            return float(value), int(timestamp)
    return None


def data_point_instance_id(data_point: Any) -> str | None:
    for dimension in data_point.Dimensions or []:
        if dimension.Name.lower() == "instanceid":
            return dimension.Value
    return None


def lighthouse_traffic_totals(packages: Iterable[Any]) -> tuple[float, float, float, float]:
    """Return byte totals for every traffic package associated with one instance.

    An instance can have more than one returned package. Tencent returns every field
    in bytes, so summing them retains the API unit and avoids a hidden GB conversion.
    """

    used = total = remaining = overflow = 0.0
    for package in packages:
        used += float(package.TrafficUsed or 0)
        total += float(package.TrafficPackageTotal or 0)
        remaining += float(package.TrafficPackageRemaining or 0)
        overflow += float(package.TrafficOverflow or 0)
    return used, total, remaining, overflow


class TencentCollector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.credential = credential.Credential(config["secret_id"], config["secret_key"])
        self.clients: dict[str, monitor_client.MonitorClient] = {}
        self.lighthouse_clients: dict[str, lighthouse_client.LighthouseClient] = {}
        self.account_monitor_client: monitor_client.MonitorClient | None = None

    def client(self, region: str) -> monitor_client.MonitorClient:
        if region not in self.clients:
            http_profile = HttpProfile()
            http_profile.endpoint = "monitor.tencentcloudapi.com"
            http_profile.reqTimeout = self.config["request_timeout_seconds"]
            client_profile = ClientProfile(httpProfile=http_profile)
            self.clients[region] = monitor_client.MonitorClient(
                self.credential, region, client_profile
            )
        return self.clients[region]

    def lighthouse_api_client(self, region: str) -> lighthouse_client.LighthouseClient:
        if region not in self.lighthouse_clients:
            http_profile = HttpProfile()
            http_profile.endpoint = "lighthouse.tencentcloudapi.com"
            http_profile.reqTimeout = self.config["request_timeout_seconds"]
            client_profile = ClientProfile(httpProfile=http_profile)
            self.lighthouse_clients[region] = lighthouse_client.LighthouseClient(
                self.credential, region, client_profile
            )
        return self.lighthouse_clients[region]

    def collect_monitor_api_usage(self) -> bool:
        """Refresh account-level Monitor API usage and quota metrics."""
        labels = ("tencent",)
        request_labels = ("tencent", "account", "global")
        try:
            if self.account_monitor_client is None:
                http_profile = HttpProfile()
                http_profile.endpoint = "monitor.tencentcloudapi.com"
                http_profile.reqTimeout = self.config["request_timeout_seconds"]
                client_profile = ClientProfile(httpProfile=http_profile)
                self.account_monitor_client = monitor_client.MonitorClient(
                    self.credential, "", client_profile
                )
            request = models.DescribeMonitorResourceInfoRequest()
            response = self.account_monitor_client.DescribeMonitorResourceInfo(request)
            used = max(0, int(response.APIUsageNumber or 0))
            quota = self.config["monitor_api_monthly_quota"]
            TENCENT_MONITOR_API_USAGE.labels(*labels).set(used)
            TENCENT_MONITOR_API_QUOTA.labels(*labels).set(quota)
            TENCENT_MONITOR_API_REMAINING.labels(*labels).set(max(quota - used, 0))
            TENCENT_MONITOR_API_USAGE_PERCENT.labels(*labels).set(used / quota * 100)
            TENCENT_MONITOR_API_LAST_SUCCESS.labels(*labels).set_to_current_time()
            TENCENT_MONITOR_API_UP.labels(*labels).set(1)
            API_REQUESTS.labels(
                *request_labels, "DescribeMonitorResourceInfo", "success"
            ).inc()
            return True
        except Exception:
            TENCENT_MONITOR_API_UP.labels(*labels).set(0)
            API_REQUESTS.labels(
                *request_labels, "DescribeMonitorResourceInfo", "error"
            ).inc()
            LOG.exception("Failed to collect Tencent Cloud Monitor API usage")
            return False

    def query(
        self,
        product: str,
        region: str,
        instances: list[InstanceConfig],
        metric_name: str,
    ) -> dict[str, tuple[float, int]]:
        spec = PRODUCTS[product]
        request = models.GetMonitorDataRequest()
        request.Namespace = spec.namespace
        request.MetricName = metric_name
        request.Period = 60
        now = datetime.now(timezone.utc).replace(microsecond=0)
        request.StartTime = (now - timedelta(seconds=self.config["lookback_seconds"])).isoformat()
        request.EndTime = now.isoformat()
        request.Instances = []
        for instance in instances:
            api_instance = models.Instance()
            dimension = models.Dimension()
            dimension.Name = "InstanceId"
            dimension.Value = instance.instance_id
            api_instance.Dimensions = [dimension]
            request.Instances.append(api_instance)

        group_labels = ("tencent", product, region)
        try:
            response = self.client(region).GetMonitorData(request)
            API_REQUESTS.labels(*group_labels, metric_name, "success").inc()
        except Exception:
            API_REQUESTS.labels(*group_labels, metric_name, "error").inc()
            raise

        result: dict[str, tuple[float, int]] = {}
        for data_point in response.DataPoints or []:
            instance_id = data_point_instance_id(data_point)
            point = latest_value(data_point)
            if instance_id and point:
                result[instance_id] = point
        return result

    def collect_lighthouse_traffic_packages(
        self, region: str, instances: list[InstanceConfig]
    ) -> bool:
        """Collect current Lighthouse package allowances for one region.

        These values describe the current package state rather than a Cloud Monitor
        historical data point, therefore they intentionally use ordinary Gauges.
        """

        group_labels = ("tencent", "lighthouse", region)
        values: dict[str, tuple[float, float, float, float]] = {}
        try:
            for batch in chunks(instances, MAX_LIGHTHOUSE_INSTANCES_PER_REQUEST):
                request = lighthouse_models.DescribeInstancesTrafficPackagesRequest()
                request.InstanceIds = [instance.instance_id for instance in batch]
                request.Limit = len(batch)
                response = self.lighthouse_api_client(region).DescribeInstancesTrafficPackages(
                    request
                )
                API_REQUESTS.labels(
                    *group_labels, "DescribeInstancesTrafficPackages", "success"
                ).inc()
                for instance_package in response.InstanceTrafficPackageSet or []:
                    values[instance_package.InstanceId] = lighthouse_traffic_totals(
                        instance_package.TrafficPackageSet or []
                    )
        except Exception:
            API_REQUESTS.labels(
                *group_labels, "DescribeInstancesTrafficPackages", "error"
            ).inc()
            LOG.exception(
                "Lighthouse traffic package collection failed for region=%s", region
            )
            return False

        successful = True
        for instance in instances:
            totals = values.get(instance.instance_id)
            if totals is None:
                successful = False
                LOG.warning(
                    "No Lighthouse traffic package returned for region=%s instance=%s",
                    region,
                    instance.instance_id,
                )
                continue
            used, total, remaining, overflow = totals
            LIGHTHOUSE_TRAFFIC_USED.labels(*instance.labels()).set(used)
            LIGHTHOUSE_TRAFFIC_TOTAL.labels(*instance.labels()).set(total)
            LIGHTHOUSE_TRAFFIC_REMAINING.labels(*instance.labels()).set(remaining)
            LIGHTHOUSE_TRAFFIC_OVERFLOW.labels(*instance.labels()).set(overflow)
            usage_percent = used / total * 100 if total > 0 else 0.0
            LIGHTHOUSE_TRAFFIC_USAGE_PERCENT.labels(*instance.labels()).set(usage_percent)
        return successful

    def collect_group(
        self, product: str, region: str, instances: list[InstanceConfig]
    ) -> None:
        spec = PRODUCTS[product]
        metric_jobs = [
            (spec.receive_metric, "cloud_network_public_receive_mbps", spec.bandwidth_multiplier, "receive"),
            (spec.transmit_metric, "cloud_network_public_transmit_mbps", spec.bandwidth_multiplier, "transmit"),
            (spec.utilization_metric, "cloud_network_public_egress_utilization_ratio", 0.01, "egress_utilization"),
        ]
        if spec.transmit_traffic_metric:
            metric_jobs.append(
                (spec.transmit_traffic_metric, "cloud_network_public_transmit_megabytes", 1.0, "transmit_traffic")
            )
        group_labels = ("tencent", product, region)
        successful = True

        for metric_name, exported_metric, multiplier, timestamp_metric in metric_jobs:
            try:
                values: dict[str, tuple[float, int]] = {}
                for batch in chunks(instances, MAX_INSTANCES_PER_REQUEST):
                    values.update(self.query(product, region, batch, metric_name))
                for instance in instances:
                    point = values.get(instance.instance_id)
                    if point is None:
                        successful = False
                        LOG.warning(
                            "No data point for product=%s region=%s instance=%s metric=%s",
                            product,
                            region,
                            instance.instance_id,
                            metric_name,
                        )
                        continue
                    value, timestamp = point
                    TIMESTAMPED_BUSINESS_METRICS.update(
                        exported_metric, (*instance.labels(), "true"), value * multiplier, timestamp
                    )
                    METRIC_TIMESTAMP.labels(*instance.labels(), timestamp_metric).set(timestamp)
            except Exception:
                successful = False
                LOG.exception(
                    "Collection failed for product=%s region=%s metric=%s",
                    product,
                    region,
                    metric_name,
                )

        if product == "lighthouse":
            successful = self.collect_lighthouse_traffic_packages(region, instances) and successful

        GROUP_UP.labels(*group_labels).set(1 if successful else 0)
        if successful:
            LAST_GROUP_SUCCESS.labels(*group_labels).set_to_current_time()
        else:
            COLLECTION_ERRORS.labels(*group_labels).inc()

    def collect(self) -> None:
        groups: dict[tuple[str, str], list[InstanceConfig]] = defaultdict(list)
        for instance in self.config["instances"]:
            groups[(instance.product, instance.region)].append(instance)
        for (product, region), instances in groups.items():
            self.collect_group(product, region, instances)
        self.collect_monitor_api_usage()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = load_config(args.config)
    planned_requests = planned_requests_per_cycle(config["instances"])
    interval = config["collection_interval_seconds"]
    PLANNED_API_REQUESTS_PER_CYCLE.set(planned_requests)
    COLLECTION_INTERVAL.set(interval)
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda _signum, _frame: stop.set())

    start_http_server(config["listen_port"], addr=config["listen_address"])
    LOG.info(
        "Listening on http://%s:%d/metrics for %d Tencent Cloud instances",
        config["listen_address"],
        config["listen_port"],
        len(config["instances"]),
    )
    LOG.info(
        "Collection interval=%ds; planned Tencent Cloud API requests=%d/cycle, "
        "approximately %.1f/hour and %.0f/30-day month",
        interval,
        planned_requests,
        planned_requests * 3600 / interval,
        planned_requests * 30 * 24 * 3600 / interval,
    )
    collector = TencentCollector(config)
    while not stop.is_set():
        started = time.monotonic()
        collector.collect()
        elapsed = time.monotonic() - started
        stop.wait(max(0.0, config["collection_interval_seconds"] - elapsed))


if __name__ == "__main__":
    main()
