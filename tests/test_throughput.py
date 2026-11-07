import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from lib.services import MeasurementPolicyEvaluator
from lib.traffic import run_iperf3_via_ssh

pytestmark = pytest.mark.real_lab


@pytest.mark.perf
def test_throughput_meets_minimum(connection_pool, params, metric_logger, run_context, request):
    """Evaluate throughput from warm-up plus repeated measured iperf3 runs."""
    settings = params.get("performance", {})
    warmups = settings.get("warmup_iterations", 1)
    samples = settings.get("sample_count", 3)
    duration = settings.get("iperf_duration_sec", 10)
    for name, value, lower in (("warmup_iterations", warmups, 0),
                               ("sample_count", samples, 3),
                               ("iperf_duration_sec", duration, 1)):
        if isinstance(value, bool) or not isinstance(value, int) or value < lower:
            raise ValueError(f"performance.{name} has an invalid value")

    minimum = params["thresholds"]["min_throughput_mbps"]
    router_ip = params["network"]["router_ip"]
    for iteration in range(warmups + samples):
        result = run_iperf3_via_ssh(
            connection_pool, "client_vm", router_ip, duration=duration
        )
        throughput = float(result["throughput_mbps"])
        assert math.isfinite(throughput) and throughput >= 0, (
            f"iperf3 returned an invalid throughput observation: {result!r}"
        )
        metric_logger.log(
            throughput, "Mbps", name="throughput", warmup=iteration < warmups,
            metadata={"iteration": iteration, "duration_sec": duration},
        )

    definition = run_context.definition_for(request.node.nodeid)
    metric_definition = run_context.test_registry.metric_definition(definition.test_id, "throughput")
    metric = next((item for item in metric_logger.metrics() if item.name == "throughput"), None)
    assert metric is not None, "Required throughput metric was not collected"
    summary = MeasurementPolicyEvaluator.evaluate(metric, metric_definition.measurement_policy)
    assert summary.count == samples
    assert summary.decision_value >= minimum, (
        f"Mean throughput {summary.decision_value} Mbps over {samples} measured samples "
        f"is below minimum threshold {minimum} Mbps"
    )
