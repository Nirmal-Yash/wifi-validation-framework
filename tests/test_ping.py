import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from lib.services import MeasurementPolicyEvaluator

pytestmark = pytest.mark.real_lab


def client_ping(connection_pool, router_ip, count):
    output = connection_pool.send_command(
        "client_vm", f"ping -c {count} -W 3 {router_ip} 2>&1"
    )
    loss_match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
    if not loss_match:
        raise AssertionError(f"Could not parse packet-loss observation: {output!r}")
    loss = float(loss_match.group(1))
    rtt_match = re.search(
        r"rtt min/avg/max/(?:mdev|stddev)\s*=\s*[\d.]+/([\d.]+)/",
        output, re.IGNORECASE,
    )
    avg = float(rtt_match.group(1)) if rtt_match else None
    return {"success": loss < 100.0, "packet_loss_pct": loss,
            "avg_rtt_ms": avg, "output": output}


def _sampling_plan(params):
    settings = params.get("performance", {})
    warmups = settings.get("warmup_iterations", 1)
    samples = settings.get("sample_count", 3)
    if isinstance(warmups, bool) or not isinstance(warmups, int) or warmups < 0:
        raise ValueError("performance.warmup_iterations must be a non-negative integer")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 3:
        raise ValueError("performance.sample_count must be an integer of at least 3")
    return warmups, samples, settings


def _decision_summary(metric_logger, run_context, request, metric_name):
    definition = run_context.definition_for(request.node.nodeid)
    metric_definition = run_context.test_registry.metric_definition(definition.test_id, metric_name)
    metric = next((item for item in metric_logger.metrics() if item.name == metric_name), None)
    assert metric is not None, f"Required performance metric was not collected: {metric_name}"
    return MeasurementPolicyEvaluator.evaluate(metric, metric_definition.measurement_policy)


@pytest.mark.perf
def test_ping_success(connection_pool, params, metric_logger, run_context, request):
    router_ip = params["network"]["router_ip"]
    warmups, samples, settings = _sampling_plan(params)
    count = int(settings.get("ping_success_packet_count", 5))
    for iteration in range(warmups + samples):
        result = client_ping(connection_pool, router_ip, count)
        metric_logger.log(
            1.0 if result["success"] else 0.0, "bool", name="ping_success",
            warmup=iteration < warmups, metadata={"iteration": iteration},
        )
    summary = _decision_summary(metric_logger, run_context, request, "ping_success")
    assert summary.count == samples
    assert summary.decision_value == 1.0, (
        f"WiFi ping success rate across {samples} measured samples was {summary.decision_value}"
    )


@pytest.mark.perf
def test_packet_loss_within_threshold(connection_pool, params, metric_logger, run_context, request):
    router_ip = params["network"]["router_ip"]
    warmups, samples, settings = _sampling_plan(params)
    count = int(settings.get("packet_loss_packet_count", 20))
    for iteration in range(warmups + samples):
        result = client_ping(connection_pool, router_ip, count)
        metric_logger.log(
            result["packet_loss_pct"], "percent", name="packet_loss",
            warmup=iteration < warmups, metadata={"iteration": iteration},
        )
    summary = _decision_summary(metric_logger, run_context, request, "packet_loss")
    threshold = params["thresholds"]["max_packet_loss_pct"]
    assert summary.count == samples
    assert summary.decision_value <= threshold, (
        f"Mean packet loss {summary.decision_value}% over {samples} samples exceeds {threshold}%"
    )


@pytest.mark.perf
def test_latency_within_threshold(connection_pool, params, metric_logger, run_context, request):
    router_ip = params["network"]["router_ip"]
    warmups, samples, settings = _sampling_plan(params)
    count = int(settings.get("latency_packet_count", 10))
    for iteration in range(warmups + samples):
        result = client_ping(connection_pool, router_ip, count)
        rtt = result["avg_rtt_ms"]
        assert rtt is not None and math.isfinite(rtt), (
            f"Could not parse finite client WiFi average RTT: {result['output']!r}"
        )
        metric_logger.log(
            rtt, "ms", name="latency", warmup=iteration < warmups,
            metadata={"iteration": iteration},
        )
    summary = _decision_summary(metric_logger, run_context, request, "latency")
    threshold = params["thresholds"]["max_latency_ms"]
    assert summary.count == samples
    assert summary.decision_value <= threshold, (
        f"P95 latency {summary.decision_value}ms over {samples} samples exceeds {threshold}ms"
    )
