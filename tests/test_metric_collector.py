from datetime import datetime, timezone

from lib.services import MetricCollector


def test_collector_preserves_multiple_raw_samples():
    collector = MetricCollector()
    captured = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    collector.log(10, "ms", name="latency", captured_at=captured)
    collector.log(12, "ms", name="latency", warmup=True, retried=True, captured_at=captured)

    metrics = collector.metrics()
    assert len(metrics) == 1
    assert len(metrics[0].samples) == 2
    assert metrics[0].samples[1].warmup is True
    assert metrics[0].samples[1].retried is True
    assert metrics[0].samples[0].captured_at == captured
    assert collector.sample_count == 2
