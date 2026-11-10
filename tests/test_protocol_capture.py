from __future__ import annotations

import hashlib
import json
import re
import shlex
import time
from pathlib import Path

import pytest

from lib.domain import ArtifactType
from lib.services import ArtifactService, ProtocolEvidenceService
from lib.traffic import run_dns_lookup
from lib.services.wifi_state import assess_wifi_association


ROOT = Path(__file__).resolve().parent.parent
EXPECTED_CHANNEL = 6


class ForegroundTcpdump:
    """Run tcpdump in a dedicated AP Paramiko channel and verify its SFTP copy."""

    def __init__(self, connection, *, interface, scope, filter_expr=None):
        self.connection = connection
        self.interface = interface
        self.scope = re.sub(r"[^A-Za-z0-9_.-]", "-", scope)
        self.filter_expr = filter_expr
        self.remote_pcap = f"/tmp/netregress-{self.scope}.pcap"
        self.remote_download = f"{self.remote_pcap}.sftp"
        self.remote_pid = f"/tmp/netregress-{self.scope}.pid"
        self.remote_log = f"/tmp/netregress-{self.scope}.tcpdump.log"
        self.stdin = None
        self.stdout = None
        self.stderr = None
        self.pid = None
        self.started = False
        self.stopped = False
        self.transferred = False

    def ap_exec(self, command, *, timeout=20, check=True):
        _stdin, stdout, stderr = self.connection.remote_conn_pre.exec_command(
            command, timeout=timeout
        )
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        if check and rc != 0:
            raise AssertionError(
                f"AP command failed (rc={rc}): {command!r}; stderr={err.strip()!r}"
            )
        return out, err, rc

    def start(self):
        if self.interface == "mon0":
            self.ap_exec("sudo -n ip link set mon0 up", timeout=10)
        self.ap_exec(
            "sudo -n rm -f "
            + " ".join(
                shlex.quote(path)
                for path in (self.remote_pcap, self.remote_download, self.remote_pid, self.remote_log)
            ),
            timeout=10,
        )
        filter_argument = (
            f" {shlex.quote(self.filter_expr)}" if self.filter_expr else ""
        )
        script = (
            f"echo $$ > {shlex.quote(self.remote_pid)}; "
            f"exec tcpdump -i {shlex.quote(self.interface)} -nn -s0 -U "
            f"-w {shlex.quote(self.remote_pcap)}{filter_argument} "
            f">{shlex.quote(self.remote_log)} 2>&1"
        )
        command = f"sudo -n sh -c {shlex.quote(script)}"
        self.stdin, self.stdout, self.stderr = (
            self.connection.remote_conn_pre.exec_command(command, timeout=15)
        )
        self.started = True

        for _ in range(24):
            output, _, _ = self.ap_exec(
                f"grep -q 'listening on ' {shlex.quote(self.remote_log)} "
                "2>/dev/null && echo READY || echo NOT_READY",
                timeout=10,
            )
            if output.strip() == "READY":
                break
            time.sleep(0.5)
        else:
            log, _, _ = self.ap_exec(
                f"cat {shlex.quote(self.remote_log)} 2>/dev/null || true",
                timeout=10,
                check=False,
            )
            raise AssertionError(
                f"tcpdump did not become ready on AP {self.interface}: {log!r}"
            )

        pid_output, _, _ = self.ap_exec(
            f"cat {shlex.quote(self.remote_pid)}", timeout=10
        )
        self.pid = pid_output.strip()
        assert self.pid.isdigit(), f"Invalid tcpdump PID: {pid_output!r}"
        running, _, _ = self.ap_exec(
            f"sudo -n kill -0 {self.pid} 2>/dev/null && echo RUNNING || echo STOPPED",
            timeout=10,
        )
        assert running.strip() == "RUNNING", "tcpdump exited before traffic generation"
        return self

    def stop(self):
        if not self.started or self.stopped:
            return
        if not self.pid:
            pid_output, _, _ = self.ap_exec(
                f"cat {shlex.quote(self.remote_pid)} 2>/dev/null || true",
                timeout=10,
                check=False,
            )
            self.pid = pid_output.strip()
        if self.pid and self.pid.isdigit():
            self.ap_exec(f"sudo -n kill -INT {self.pid}", timeout=10, check=False)
        self.stdout.channel.settimeout(20)
        self.stderr.channel.settimeout(20)
        self.stdout.read()
        self.stderr.read()
        exit_code = self.stdout.channel.recv_exit_status()
        self.stopped = True
        if exit_code != 0:
            log, _, _ = self.ap_exec(
                f"cat {shlex.quote(self.remote_log)} 2>/dev/null || true",
                timeout=10,
                check=False,
            )
            raise AssertionError(
                f"tcpdump exited with rc={exit_code} on {self.interface}: {log!r}"
            )

        size, _, _ = self.ap_exec(
            f"sudo -n stat -c%s {shlex.quote(self.remote_pcap)}",
            timeout=10,
        )
        assert size.strip().isdigit() and int(size.strip()) > 64, (
            f"tcpdump did not persist a non-empty capture on {self.interface}"
        )

    def download_and_verify(self, local_path: Path) -> tuple[Path, str]:
        assert self.stopped, "Stop tcpdump cleanly before transferring its PCAP"
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.unlink(missing_ok=True)
        self.ap_exec(
            f"sudo -n cp -- {shlex.quote(self.remote_pcap)} "
            f"{shlex.quote(self.remote_download)} "
            f"&& sudo -n chmod 0644 {shlex.quote(self.remote_download)}",
            timeout=30,
        )
        try:
            with self.connection.remote_conn_pre.open_sftp() as sftp:
                sftp.get(self.remote_download, str(local_path))
            remote_output, _, _ = self.ap_exec(
                f"sha256sum {shlex.quote(self.remote_download)}", timeout=10
            )
        finally:
            self.ap_exec(
                f"sudo -n rm -f {shlex.quote(self.remote_download)}",
                timeout=10,
                check=False,
            )

        match = re.match(r"^([0-9a-fA-F]{64})\s+", remote_output.strip())
        assert match, f"Could not read remote PCAP SHA-256: {remote_output!r}"
        assert local_path.is_file(), "SFTP did not create the local PCAP"
        local_bytes = local_path.read_bytes()
        assert len(local_bytes) > 64, "Downloaded PCAP is too small to contain captured traffic"
        local_hash = hashlib.sha256(local_bytes).hexdigest()
        assert local_hash.lower() == match.group(1).lower(), (
            "SFTP PCAP SHA-256 does not match the AP-side capture"
        )
        self.transferred = True
        return local_path, local_hash

    def cleanup(self):
        if self.started and not self.stopped:
            try:
                if not self.pid:
                    pid_output, _, _ = self.ap_exec(
                        f"cat {shlex.quote(self.remote_pid)} 2>/dev/null || true",
                        timeout=10,
                        check=False,
                    )
                    self.pid = pid_output.strip()
                if self.pid and self.pid.isdigit():
                    self.ap_exec(
                        f"sudo -n kill -INT {self.pid} 2>/dev/null || true",
                        timeout=10,
                        check=False,
                    )
                if self.stdout is not None:
                    self.stdout.channel.settimeout(5)
                    self.stdout.read()
                    self.stdout.channel.recv_exit_status()
            except Exception:
                pass
            try:
                if self.stdin is not None:
                    self.stdin.close()
            except Exception:
                pass
        paths_to_remove = [self.remote_pid, self.remote_download]
        # Retain AP-side PCAP and tcpdump log when capture/transfer/assertions
        # fail, so the operator can recover the original failure evidence.
        if self.transferred:
            paths_to_remove.extend((self.remote_log, self.remote_pcap))
        for path in paths_to_remove:
            try:
                self.ap_exec(
                    f"sudo -n rm -f {shlex.quote(path)}",
                    timeout=10,
                    check=False,
                )
            except Exception:
                pass


def _scope(request) -> tuple[str, str, object | None]:
    context = getattr(request.config, "_netregress_run_context", None)
    run_id = getattr(context, "run_id", None) or "adhoc"
    attempt_id = getattr(context, "attempt_id", None) or "adhoc"
    return str(run_id), str(attempt_id), context


def _artifact_service(context):
    if context is None:
        return None
    return context.artifact_service or ArtifactService.from_sqlite(
        context.run_service.run_repository.database
    )


def _register_pcap_artifact(
    *,
    context,
    node_id: str,
    pcap_path: Path,
    pcap_sha256: str,
) -> None:
    artifact_service = _artifact_service(context)
    if artifact_service is None:
        return
    pcap_data = pcap_path.read_bytes()
    artifact_service.register_file(
        run_id=context.run_id,
        path=pcap_path,
        artifact_type=ArtifactType.PCAP,
        test_node_id=node_id,
        attempt_id=context.attempt_id,
        display_name=pcap_path.name,
        expected_sha256=pcap_sha256,
        expected_size_bytes=len(pcap_data),
    )


def _register_protocol_artifact(*, context, node_id: str, evidence_path: Path) -> None:
    artifact_service = _artifact_service(context)
    if artifact_service is None:
        return
    evidence_data = evidence_path.read_bytes()
    artifact_service.register_file(
        run_id=context.run_id,
        path=evidence_path,
        artifact_type=ArtifactType.PROTOCOL_EVIDENCE,
        test_node_id=node_id,
        attempt_id=context.attempt_id,
        display_name=evidence_path.name,
        expected_sha256=hashlib.sha256(evidence_data).hexdigest(),
        expected_size_bytes=len(evidence_data),
    )


def _wait_for_wifi_disconnection(connection_pool, timeout_sec=15):
    """Wait until wpa_supplicant confirms that the client is disconnected."""
    deadline = time.monotonic() + timeout_sec
    latest = ""

    while time.monotonic() < deadline:
        latest = connection_pool.send_command(
            "client_vm",
            "wpa_cli -i wlan0 status",
            read_timeout=10,
        )
        if re.search(r"(?m)^wpa_state=DISCONNECTED$", latest):
            return latest
        time.sleep(0.5)

    raise AssertionError(
        f"Client did not reach DISCONNECTED state within {timeout_sec}s: "
        f"{latest!r}"
    )


def _wait_for_wifi_association(
    connection_pool, expected_ssid: str, timeout_sec=30
):
    """Wait for WPA2 association, using verified driver state if wpa_state is absent."""
    deadline = time.monotonic() + timeout_sec
    latest = ""

    while time.monotonic() < deadline:
        latest = connection_pool.send_command(
            "client_vm",
            "wpa_cli -i wlan0 status 2>/dev/null; "
            "iw dev wlan0 link 2>/dev/null || true",
            read_timeout=10,
        )
        association = assess_wifi_association(
            wpa_status=latest,
            iw_link=latest,
            expected_ssid=expected_ssid,
            require_wpa2=True,
        )
        if association.connected:
            return latest
        time.sleep(1)

    raise AssertionError(
        f"Client did not establish WPA2 association with {expected_ssid!r} "
        f"within {timeout_sec}s: {latest!r}"
    )


def _ensure_ap_monitor_interface(ap_connection) -> bool:
    """Create mon0 on the existing AP wiphy without changing wlan0 or its channel."""
    wlan_info, _, _ = ForegroundTcpdump(
        ap_connection, interface="wlan0", scope="preflight"
    ).ap_exec("iw dev wlan0 info", timeout=10)
    match = re.search(r"^\s*wiphy\s+(\d+)\s*$", wlan_info, re.MULTILINE)
    assert match, f"Could not identify AP wlan0 wiphy: {wlan_info!r}"
    phy = f"phy{match.group(1)}"

    monitor_info, _, monitor_rc = ForegroundTcpdump(
        ap_connection, interface="mon0", scope="preflight"
    ).ap_exec("iw dev mon0 info", timeout=10, check=False)
    if monitor_rc == 0:
        monitor_match = re.search(r"^\s*wiphy\s+(\d+)\s*$", monitor_info, re.MULTILINE)
        assert monitor_match and monitor_match.group(1) == match.group(1), (
            f"Existing mon0 does not share AP wlan0's wiphy {phy}: {monitor_info!r}"
        )
        assert re.search(r"\btype\s+monitor\b", monitor_info, re.IGNORECASE), (
            f"Existing mon0 is not a monitor-mode interface: {monitor_info!r}"
        )
        return False

    creator = ForegroundTcpdump(
        ap_connection, interface="wlan0", scope="preflight"
    )
    # Track ownership immediately after creation; a later activation or
    # verification error must not leak a monitor interface into the lab.
    creator.ap_exec(
        f"sudo -n iw phy {shlex.quote(phy)} interface add mon0 type monitor",
        timeout=15,
    )
    try:
        creator.ap_exec("sudo -n ip link set mon0 up", timeout=10)
        monitor_info, _, _ = creator.ap_exec("iw dev mon0 info", timeout=10)
        monitor_match = re.search(r"^\s*wiphy\s+(\d+)\s*$", monitor_info, re.MULTILINE)
        assert monitor_match and monitor_match.group(1) == match.group(1), (
            f"New mon0 does not share AP wlan0's wiphy {phy}: {monitor_info!r}"
        )
        assert re.search(r"\btype\s+monitor\b", monitor_info, re.IGNORECASE), (
            f"New mon0 is not a monitor-mode interface: {monitor_info!r}"
        )
    except Exception:
        try:
            creator.ap_exec("sudo -n iw dev mon0 del", timeout=10, check=False)
        except Exception:
            pass
        raise
    return True


@pytest.mark.real_lab
@pytest.mark.regression
def test_real_wifi_capture_contains_eapol_and_beacon(
    connection_pool, params, request
):
    """Capture actual WPA2 reauthentication and AP beacon frames on AP mon0."""
    ap_connection = connection_pool.get_connection("ap_host")
    helper = ForegroundTcpdump(
        ap_connection, interface="mon0", scope="-".join(_scope(request)[:2])
    )
    monitor_created = False
    try:
        wlan_info, _, _ = helper.ap_exec("iw dev wlan0 info", timeout=10)
        channel_match = re.search(r"\bchannel\s+(\d+)\b", wlan_info)
        assert channel_match and int(channel_match.group(1)) == EXPECTED_CHANNEL, (
            f"AP wlan0 is not on the protected channel {EXPECTED_CHANNEL}: {wlan_info!r}"
        )
        ap_mac, _, _ = helper.ap_exec(
            "cat /sys/class/net/wlan0/address", timeout=10
        )
        ap_mac = ap_mac.strip().lower()
        assert re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", ap_mac), (
            f"Invalid AP wlan0 BSSID: {ap_mac!r}"
        )
        client_mac_output = connection_pool.send_command(
            "client_vm",
            "cat /sys/class/net/wlan0/address",
            read_timeout=10,
        )
        client_mac_match = re.search(
            r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}",
            client_mac_output.lower(),
        )
        assert client_mac_match, (
            f"Could not identify client wlan0 MAC over management eth1: "
            f"{client_mac_output!r}"
        )
        client_mac = client_mac_match.group(0)
        monitor_created = _ensure_ap_monitor_interface(ap_connection)

        # wlan0 and mon0 share the AP's single-channel PHY.
        # The AP owns the active channel; the parsed Beacon in the PCAP
        # below is the authoritative verification of the captured channel.
        helper.start()
        # Allow periodic beacon frames to arrive before provoking authentication.
        time.sleep(2)
        disconnect = connection_pool.send_command(
            "client_vm",
            "sudo -n wpa_cli -i wlan0 disconnect",
            read_timeout=15,
        )
        assert "FAIL" not in disconnect.upper(), (
            f"Could not disconnect client for WPA2 capture: {disconnect!r}"
        )

        _wait_for_wifi_disconnection(connection_pool, timeout_sec=15)

        reconnect = connection_pool.send_command(
            "client_vm",
            "sudo -n wpa_cli -i wlan0 reconnect",
            read_timeout=15,
        )
        assert "FAIL" not in reconnect.upper(), (
            f"Could not request client reassociation: {reconnect!r}"
        )
        association = _wait_for_wifi_association(
            connection_pool,
            expected_ssid=params["wifi"]["ssid"],
            timeout_sec=30,
        )
        # Keep the same capture active briefly to record stable beacon traffic too.
        time.sleep(2)
        helper.stop()

        run_id, attempt_id, context = _scope(request)
        pcap_path = (
            ROOT / "results" / "captures"
            / f"{run_id}-{attempt_id}-eapol-beacon.pcap"
        )
        _, pcap_hash = helper.download_and_verify(pcap_path)
        _register_pcap_artifact(
            context=context,
            node_id=request.node.nodeid,
            pcap_path=pcap_path,
            pcap_sha256=pcap_hash,
        )

        protocol_service = (
            context.protocol_evidence_service
            if context is not None and context.protocol_evidence_service is not None
            else ProtocolEvidenceService()
        )
        eapol = protocol_service.analyze_eapol(pcap_path)
        beacon = protocol_service.analyze_beacon(
            pcap_path,
            expected_ssid=params["wifi"]["ssid"],
            expected_bssid=ap_mac,
        )

        evidence_path = (
            ROOT / "results" / "evidence"
            / f"{run_id}-{attempt_id}-eapol-beacon.json"
        )
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(
                {"eapol": eapol.as_dict(), "beacon": beacon.as_dict()},
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        _register_protocol_artifact(
            context=context,
            node_id=request.node.nodeid,
            evidence_path=evidence_path,
        )

        target_handshake = any(
            item.handshake_completed
            and {item.endpoint_a, item.endpoint_b} == {ap_mac, client_mac}
            for item in eapol.handshakes
        )
        assert target_handshake, (
            "Captured PCAP does not prove the WPA2 four-way handshake between "
            f"the configured AP and client: {eapol.as_dict()}"
        )
        assert beacon.beacon_count > 0, "No real 802.11 Beacon frames were captured"
        assert beacon.matches_expected_ssid and beacon.matches_expected_bssid, (
            f"Captured Beacon identity does not match the configured AP: {beacon.as_dict()}"
        )
        assert beacon.channel == EXPECTED_CHANNEL, (
            f"Expected channel {EXPECTED_CHANNEL}, got: {beacon.as_dict()}"
        )
        assert beacon.has_rsn and beacon.rsn_valid, (
            f"Beacon does not contain a valid RSN information element: {beacon.as_dict()}"
        )
        assert beacon.group_cipher == "CCMP-128"
        assert "CCMP-128" in beacon.pairwise_ciphers
        assert "PSK" in beacon.akms
        assert beacon.beacon_interval_ms == pytest.approx(102.4, abs=1.0)
    finally:
        try:
            helper.stop()
        except Exception:
            pass
        helper.cleanup()
        if monitor_created:
            try:
                helper.ap_exec("sudo -n iw dev mon0 del", timeout=10, check=False)
            except Exception:
                pass


@pytest.mark.real_lab
@pytest.mark.regression
def test_real_wifi_dns_capture_correlates_query_response(
    connection_pool, params, request
):
    """Capture the real client DNS exchange on the AP bridge and correlate both sides."""
    ap_connection = connection_pool.get_connection("ap_host")
    run_id, attempt_id, context = _scope(request)
    helper = ForegroundTcpdump(
        ap_connection,
        interface="br0",
        scope=f"{run_id}-{attempt_id}-dns",
        filter_expr="(udp port 53 or tcp port 53)",
    )
    try:
        helper.start()
        hostname = params["dns"]["test_hostname"]
        lookup = run_dns_lookup(connection_pool, "client_vm", hostname)
        assert lookup["success"] and lookup["resolved_ip"], (
            f"Real client DNS lookup failed for {hostname}: {lookup['output']!r}"
        )
        time.sleep(1)
        helper.stop()

        pcap_path = (
            ROOT / "results" / "captures"
            / f"{run_id}-{attempt_id}-dns.pcap"
        )
        _, pcap_hash = helper.download_and_verify(pcap_path)
        _register_pcap_artifact(
            context=context,
            node_id=request.node.nodeid,
            pcap_path=pcap_path,
            pcap_sha256=pcap_hash,
        )

        protocol_service = (
            context.protocol_evidence_service
            if context is not None and context.protocol_evidence_service is not None
            else ProtocolEvidenceService()
        )
        evidence = protocol_service.analyze_dns(
            pcap_path,
            expected_domain=hostname,
        )
        evidence_path = (
            ROOT / "results" / "evidence"
            / f"{run_id}-{attempt_id}-dns-protocol.json"
        )
        protocol_service.write_json(evidence, evidence_path)
        _register_protocol_artifact(
            context=context,
            node_id=request.node.nodeid,
            evidence_path=evidence_path,
        )

        assert evidence.correlated_transaction_count > 0, (
            f"Captured DNS PCAP has no correlated query/response for {hostname}: "
            f"{evidence.as_dict()}"
        )
        assert evidence.resolved_ips, (
            f"Correlated DNS response contained no IPv4/IPv6 answer: {evidence.as_dict()}"
        )
        assert lookup["resolved_ip"] in evidence.resolved_ips, (
            "DNS answer from the client lookup does not appear in the correlated "
            f"PCAP evidence: lookup={lookup['resolved_ip']!r}, "
            f"evidence={evidence.as_dict()}"
        )
    finally:
        try:
            helper.stop()
        except Exception:
            pass
        helper.cleanup()



def test_monitor_creation_failure_removes_only_test_owned_interface(monkeypatch):
    commands = []

    class FakeTcpdump:
        def __init__(self, connection, *, interface, scope, filter_expr=None):
            self.interface = interface

        def ap_exec(self, command, *, timeout=20, check=True):
            commands.append((self.interface, command))
            if command == "iw dev wlan0 info":
                return "Interface wlan0\n\twiphy 0\n", "", 0
            if command == "iw dev mon0 info":
                return "", "interface not found", 1
            if command.startswith("sudo -n iw phy phy0 interface add mon0 type monitor"):
                return "", "", 0
            if command == "sudo -n ip link set mon0 up":
                raise RuntimeError("simulated monitor activation failure")
            if command == "sudo -n iw dev mon0 del":
                return "", "", 0
            raise AssertionError(f"Unexpected AP command: {command}")

    monkeypatch.setitem(globals(), "ForegroundTcpdump", FakeTcpdump)

    with pytest.raises(RuntimeError, match="simulated monitor activation failure"):
        _ensure_ap_monitor_interface(object())

    assert any(command.startswith("sudo -n iw phy phy0 interface add mon0") for _, command in commands)
    assert ("wlan0", "sudo -n iw dev mon0 del") in commands


def test_preexisting_monitor_interface_is_not_recreated_or_deleted(monkeypatch):
    commands = []

    class FakeTcpdump:
        def __init__(self, connection, *, interface, scope, filter_expr=None):
            self.interface = interface

        def ap_exec(self, command, *, timeout=20, check=True):
            commands.append((self.interface, command))
            if command == "iw dev wlan0 info":
                return "Interface wlan0\n\twiphy 0\n", "", 0
            if command == "iw dev mon0 info":
                return "Interface mon0\n\ttype monitor\n\twiphy 0\n", "", 0
            raise AssertionError(f"Unexpected AP command: {command}")

    monkeypatch.setitem(globals(), "ForegroundTcpdump", FakeTcpdump)

    assert _ensure_ap_monitor_interface(object()) is False
    assert not any("interface add mon0" in command for _, command in commands)
    assert not any(command == "sudo -n iw dev mon0 del" for _, command in commands)
