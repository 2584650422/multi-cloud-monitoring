import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from prometheus_client import REGISTRY, generate_latest


MODULE_PATH = Path(__file__).parents[1] / "exporter.py"
SPEC = importlib.util.spec_from_file_location("cloud_network_exporter", MODULE_PATH)
exporter = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = exporter
SPEC.loader.exec_module(exporter)


class ExporterTests(unittest.TestCase):
    def test_request_budget_groups_by_product_region_and_chunks_of_50(self):
        def instance(index, product, region):
            return exporter.InstanceConfig(
                instance_id=f"ins-{index}",
                product=product,
                region=region,
                host=f"host-{index}",
                env="test",
                public_ip=f"203.0.113.{index % 254 + 1}",
            )

        instances = [instance(i, "cvm", "ap-one") for i in range(51)]
        instances.append(instance(52, "lighthouse", "ap-one"))
        instances.append(instance(53, "cvm", "ap-two"))
        self.assertEqual(exporter.planned_requests_per_cycle(instances), 12)

    def test_latest_value_skips_trailing_null(self):
        point = SimpleNamespace(Timestamps=[10, 20, 30], Values=[1.0, 2.5, None])
        self.assertEqual(exporter.latest_value(point), (2.5, 20))

    def test_data_point_instance_id_is_case_insensitive(self):
        point = SimpleNamespace(
            Dimensions=[SimpleNamespace(Name="InstanceId", Value="ins-test")]
        )
        self.assertEqual(exporter.data_point_instance_id(point), "ins-test")

    def test_load_config_rejects_unknown_product(self):
        content = """
tencent_cloud: {}
instances:
  - instance_id: x-1
    product: unknown
    region: ap-test
    host: test
    env: test
    public_ip: 203.0.113.1
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yml"
            path.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "product must be one of"):
                exporter.load_config(path)

    def test_load_config_reads_credentials_from_environment(self):
        content = """
tencent_cloud: {}
instances:
  - instance_id: ins-test
    product: cvm
    region: ap-test
    host: test
    env: test
    public_ip: 203.0.113.1
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yml"
            path.write_text(content, encoding="utf-8")
            previous_id = os.environ.get("TENCENTCLOUD_SECRET_ID")
            previous_key = os.environ.get("TENCENTCLOUD_SECRET_KEY")
            try:
                os.environ["TENCENTCLOUD_SECRET_ID"] = "id"
                os.environ["TENCENTCLOUD_SECRET_KEY"] = "key"
                config = exporter.load_config(path)
            finally:
                if previous_id is None:
                    os.environ.pop("TENCENTCLOUD_SECRET_ID", None)
                else:
                    os.environ["TENCENTCLOUD_SECRET_ID"] = previous_id
                if previous_key is None:
                    os.environ.pop("TENCENTCLOUD_SECRET_KEY", None)
                else:
                    os.environ["TENCENTCLOUD_SECRET_KEY"] = previous_key
            self.assertEqual(config["instances"][0].instance_id, "ins-test")

    def test_lighthouse_bandwidth_and_ratio_are_normalized(self):
        instance = exporter.InstanceConfig(
            instance_id="lhins-unit-test",
            product="lighthouse",
            region="ap-test",
            host="unit-test-host",
            env="test",
            public_ip="203.0.113.2",
        )
        values = {
            "LighthouseIntraffic": 1.25,
            "LighthouseOuttraffic": 2.5,
            "LighthouseOutratio": 37.5,
        }

        collector = object.__new__(exporter.TencentCollector)
        collector.config = {"instances": [instance]}
        collector.query = lambda _product, _region, _instances, metric: {
            instance.instance_id: (values[metric], 100)
        }
        collector.collect_group("lighthouse", "ap-test", [instance])

        labels = {
            "cloud": "tencent",
            "product": "lighthouse",
            "region": "ap-test",
            "instance_id": "lhins-unit-test",
            "host": "unit-test-host",
            "env": "test",
            "public_ip": "203.0.113.2",
            "source_timestamped": "true",
        }
        self.assertEqual(
            REGISTRY.get_sample_value("cloud_network_public_receive_mbps", labels),
            1.25,
        )
        self.assertEqual(
            REGISTRY.get_sample_value("cloud_network_public_transmit_mbps", labels),
            2.5,
        )
        self.assertEqual(
            REGISTRY.get_sample_value(
                "cloud_network_public_egress_utilization_ratio", labels
            ),
            0.375,
        )

    def test_timestamped_metrics_expose_tencent_source_time(self):
        labels = ("tencent", "cvm", "ap-test", "ins-1", "host-1", "test", "203.0.113.1", "true")
        exporter.TIMESTAMPED_BUSINESS_METRICS.update(
            "cloud_network_public_transmit_mbps", labels, 12.5, 1700000000
        )
        exposition = generate_latest().decode()
        self.assertIn(
            'cloud_network_public_transmit_mbps{cloud="tencent",env="test",host="host-1",instance_id="ins-1",product="cvm",public_ip="203.0.113.1",region="ap-test",source_timestamped="true"} 12.5 1700000000000',
            exposition,
        )


if __name__ == "__main__":
    unittest.main()
