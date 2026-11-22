from __future__ import annotations

from datetime import datetime, timezone

from dashboard.app import create_app
from lib.repositories import SQLiteDatabase
from lib.security import AuthManager, Role, UserRecord
from lib.services.identity import IdentityStore


def _seed_workspace(database: SQLiteDatabase) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("org-a", "org-a", "Org A", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("project-a", "org-a", "project-a", "Project A", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("project-b", "org-a", "project-b", "Project B", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,status,topology_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-a", "project-a", "Lab A", "gns3", "ACTIVE", 1, now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,status,topology_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-a2", "project-a", "Lab A2", "cml", "ACTIVE", 2, now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,status,topology_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-b", "project-b", "Lab B", "gns3", "ACTIVE", 1, now, now),
        )
        connection.execute(
            """INSERT INTO devices(
               device_id,project_id,lab_id,device_key,name,device_type,host,port,vendor,model,
               username,credential_id,capabilities_json,metadata_json,status,created_at,updated_at,created_by,updated_by
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("dev-a", "project-a", "lab-a", "router-a", "Router A", "ROUTER", "192.0.2.10", 22,
             "Linux", "FRR", "netadmin", None, "{}", "{}", "ACTIVE", now, now, "owner", "owner"),
        )
        connection.execute(
            """INSERT INTO topology_profiles(
               profile_id,project_id,name,description,scope_type,scope_id,lab_id,status,
               created_at,updated_at,created_by,updated_by
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("top-a", "project-a", "Lab topology", "", "LAB", "lab-a", "lab-a",
             "ACTIVE", now, now, "owner", "owner"),
        )
        connection.execute(
            """INSERT INTO topology_revisions(
               revision_id,profile_id,revision_number,definition_json,content_sha256,status,
               created_at,created_by,published_at,published_by
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("rev-a", "top-a", 1, '{"nodes":[],"links":[]}', "a" * 64,
             "PUBLISHED", now, "owner", now, "owner"),
        )
        connection.execute(
            """INSERT INTO pipeline_definitions(
               pipeline_id,project_id,lab_id,name,description,status,created_at,updated_at,created_by,updated_by
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("pipe-a", "project-a", "lab-a", "Reference workflow", "", "ACTIVE", now, now, "owner", "owner"),
        )
        connection.execute(
            """INSERT INTO pipeline_revisions(
               revision_id,pipeline_id,revision_number,definition_json,definition_sha256,status,
               created_at,created_by,published_at,published_by
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("pipe-rev-a", "pipe-a", 1, '{"steps":[]}', "b" * 64, "PUBLISHED", now, "owner", now, "owner"),
        )
        connection.execute(
            """INSERT INTO pipeline_executions(
               execution_id,project_id,lab_id,pipeline_id,revision_id,definition_sha256,status,
               inputs_json,result_json,linked_run_id,idempotency_key,created_at,started_at,completed_at,
               created_by,worker_id,lease_expires_at,heartbeat_at,attempt_count,last_error
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("exec-a", "project-a", "lab-a", "pipe-a", "pipe-rev-a", "b" * 64, "QUEUED",
             "{}", "{}", None, "overview-key-a", now, None, None, "owner", None, None, None, 0, None),
        )


def test_operations_overview_aggregates_real_project_lab_records(tmp_path):
    database_path = tmp_path / "overview.sqlite"
    database = SQLiteDatabase(database_path)
    database.initialize()
    _seed_workspace(database)
    app = create_app(database_path, auth_manager=AuthManager((), required=False))
    client = app.test_client()

    response = client.get("/api/v1/dashboard/operations-overview?project_id=project-a&lab_id=lab-a")
    assert response.status_code == 200
    data = response.get_json()["data"]

    assert data["scope"]["project"]["project_id"] == "project-a"
    assert data["labs"]["total"] == 2
    assert data["labs"]["in_scope"] == 1
    assert data["devices"]["total"] == 1
    assert data["topology"]["profiles"] == 1
    assert data["topology"]["revisions_by_status"] == {"PUBLISHED": 1}
    assert data["pipelines"]["total"] == 1
    assert data["pipelines"]["executions_by_status"] == {"QUEUED": 1}
    assert data["runs"]["total"] == 0
    assert data["providers"]["items"][0]["binding_status"] == "NOT_CONFIGURED"
    assert data["providers"]["items"][0]["connection_health"] == "UNKNOWN"
    assert data["providers"]["items"][0]["source"] == ["labs", "gns3_lab_bindings"]
    assert data["providers"]["source_updated_at"] is not None
    assert data["performance"]["status"] == "UNAVAILABLE"
    assert data["devices"]["source"] == "devices"
    assert data["devices"]["source_updated_at"] is not None



def test_operations_overview_counts_actual_active_run_lifecycle_states(tmp_path):
    database_path = tmp_path / "overview-run-states.sqlite"
    database = SQLiteDatabase(database_path)
    database.initialize()
    _seed_workspace(database)
    now = datetime.now(timezone.utc).isoformat()
    active_states = ("QUEUED", "PREPARING", "LAB_HEALTH_CHECK", "RUNNING")
    terminal_states = ("COMPLETED", "FAILED")
    with database.transaction(immediate=True) as connection:
        for index, lifecycle in enumerate(active_states + terminal_states):
            connection.execute(
                """INSERT INTO runs(
                   run_id,display_id,firmware_version,lab_id,validation_profile,
                   selected_tests_json,test_definition_versions_json,resolved_config_json,
                   configuration_hash,repository_commit,lifecycle,outcome,created_at,
                   provenance,project_id
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f"run-{index}", f"RUN-{index}", "1.0", "lab-a", "smoke",
                 "{}", "{}", "{}", "c" * 64, "test-commit", lifecycle, None,
                 now, "NATIVE", "project-a"),
            )

    from dashboard.query import DashboardQueryService
    result = DashboardQueryService(database).operations_overview("project-a", lab_id="lab-a")

    assert result["runs"]["total"] == 6
    assert result["runs"]["active"] == 4
    assert result["runs"]["by_lifecycle"] == {
        "QUEUED": 1, "PREPARING": 1, "LAB_HEALTH_CHECK": 1,
        "RUNNING": 1, "COMPLETED": 1, "FAILED": 1,
    }


def test_operations_overview_rejects_lab_outside_project_scope(tmp_path):
    database_path = tmp_path / "overview-scope.sqlite"
    database = SQLiteDatabase(database_path)
    database.initialize()
    _seed_workspace(database)
    app = create_app(database_path, auth_manager=AuthManager((), required=False))

    response = app.test_client().get(
        "/api/v1/dashboard/operations-overview?project_id=project-a&lab_id=lab-b"
    )
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "NOT_FOUND"


def test_operations_overview_redacts_provider_binding_without_topology_permission(tmp_path):
    database_path = tmp_path / "overview-permissions.sqlite"
    database = SQLiteDatabase(database_path)
    database.initialize()
    _seed_workspace(database)
    from dashboard.query import DashboardQueryService

    result = DashboardQueryService(database).operations_overview(
        "project-a", lab_id="lab-a", include_topology=False,
    )
    assert result["topology"]["access"] == "RESTRICTED"
    assert result["providers"]["access"] == "RESTRICTED"
    assert result["providers"]["items"] == []
    assert result["providers"]["configured"] is None
    assert result["providers"]["source_updated_at"] is None
    assert result["labs"]["items"][0]["provider_id"] is None
    assert result["labs"]["items"][0]["topology_version"] is None


def test_operations_overview_requires_a_project(tmp_path):
    app = create_app(tmp_path / "overview-empty.sqlite", auth_manager=AuthManager((), required=False))
    response = app.test_client().get("/api/v1/dashboard/operations-overview")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "INVALID_REQUEST"



def _authenticated_project_client(tmp_path):
    database_path = tmp_path / "overview-authenticated.sqlite"
    database = SQLiteDatabase(database_path)
    database.initialize()
    _seed_workspace(database)

    password = "correct-horse-battery-staple-2026"
    manager = AuthManager(
        (UserRecord(
            "ops-admin",
            AuthManager.password_hash(password),
            Role.ADMIN,
            ("project-a",),
        ),),
        required=True,
    )
    app = create_app(database_path, auth_manager=manager)
    app.config.update(TESTING=True)
    client = app.test_client()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "ops-admin", "password": password},
    )
    assert login.status_code == 200
    return app, client


def test_operations_overview_api_enforces_project_membership(tmp_path):
    _, client = _authenticated_project_client(tmp_path)
    response = client.get(
        "/api/v1/dashboard/operations-overview?project_id=project-b&lab_id=lab-b"
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "FORBIDDEN"


def test_operations_overview_api_redacts_subsystems_by_project_role(tmp_path):
    app, client = _authenticated_project_client(tmp_path)
    identity = IdentityStore(app.config["NETREGRESS_QUERY"].database)
    role = identity.create_role(
        name="Dashboard reader",
        scope_type="PROJECT",
        description="Read operational overview without topology access",
        actor="ops-admin",
    )
    identity.set_role_permissions(
        role["role_id"],
        ["workspace.read", "devices.read", "pipelines.read"],
        "ops-admin",
    )
    identity.assign_project_role("ops-admin", "project-a", role["role_id"], "ops-admin")

    response = client.get(
        "/api/v1/dashboard/operations-overview?project_id=project-a&lab_id=lab-a"
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["devices"]["access"] == "AVAILABLE"
    assert data["configuration"]["access"] == "RESTRICTED"
    assert data["evidence"]["access"] == "RESTRICTED"
    assert data["performance"]["access"] == "RESTRICTED"
    assert data["runs"]["access"] == "RESTRICTED"
    assert data["topology"]["access"] == "RESTRICTED"
    assert data["providers"]["access"] == "RESTRICTED"
    assert data["providers"]["items"] == []
    assert data["providers"]["configured"] is None
    assert data["providers"]["source_updated_at"] is None
    assert data["labs"]["items"][0]["provider_id"] is None
    assert data["labs"]["items"][0]["topology_version"] is None
    assert data["pipelines"]["access"] == "AVAILABLE"


def test_operations_overview_api_requires_authentication_when_enabled(tmp_path):
    app = create_app(
        tmp_path / "overview-unauthenticated.sqlite",
        auth_manager=AuthManager((), required=True),
    )
    app.config.update(TESTING=True)
    response = app.test_client().get(
        "/api/v1/dashboard/operations-overview?project_id=project-a"
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "UNAUTHENTICATED"


def _seed_extended_operations_evidence(database: SQLiteDatabase) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO devices(
               device_id,project_id,lab_id,device_key,name,device_type,host,port,vendor,model,
               username,credential_id,capabilities_json,metadata_json,status,created_at,updated_at,created_by,updated_by
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("dev-openwrt", "project-a", "lab-a", "openwrt-a", "OpenWrt Router",
             "ROUTER", "192.0.2.11", 22, "OpenWrt", "Generic", "root", None,
             "{}", "{}", "ACTIVE", now, now, "owner", "owner"),
        )
        connection.execute(
            """INSERT INTO configuration_schemas(
               schema_record_id,project_id,schema_id,version,name,definition_json,status,created_at,created_by
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("schema-openwrt", "project-a", "openwrt.wifi.v1", 1, "OpenWrt Wi-Fi",
             "{}", "ACTIVE", now, "owner"),
        )
        connection.execute(
            """INSERT INTO configuration_profiles(
               profile_id,project_id,name,description,scope_type,scope_id,schema_record_id,status,
               created_at,updated_at,created_by,updated_by
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("config-profile-a", "project-a", "Router Wi-Fi", "", "DEVICE", "dev-openwrt",
             "schema-openwrt", "PUBLISHED", now, now, "owner", "owner"),
        )
        connection.execute(
            """INSERT INTO configuration_revisions(
               revision_id,profile_id,schema_record_id,revision_number,values_json,
               configuration_hash,provenance_json,parent_revision_id,status,created_at,
               created_by,published_at,published_by
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("config-rev-a", "config-profile-a", "schema-openwrt", 1, "{}",
             "d" * 64, "{}", None, "PUBLISHED", now, "owner", now, "owner"),
        )
        for deployment_id, status in (("deploy-failed", "FAILED"), ("deploy-partial", "PARTIAL")):
            connection.execute(
                """INSERT INTO device_configuration_deployments(
                   deployment_id,project_id,lab_id,device_id,profile_id,revision_id,
                   schema_record_id,configuration_hash,status,plan_json,result_json,
                   created_at,started_at,completed_at,created_by
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (deployment_id, "project-a", "lab-a", "dev-openwrt", "config-profile-a",
                 "config-rev-a", "schema-openwrt", "d" * 64, status, "{}", "{}",
                 now, now, now, "owner"),
            )
        connection.execute(
            """INSERT INTO topology_apply_records(
               apply_id,project_id,lab_id,profile_id,revision_id,content_sha256,status,
               plan_json,observed_before_json,observed_after_json,result_json,
               created_at,started_at,completed_at,created_by
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("apply-failed", "project-a", "lab-a", "top-a", "rev-a", "a" * 64,
             "FAILED", "{}", "{}", "{}", "{}", now, now, now, "owner"),
        )
        connection.execute(
            """INSERT INTO pipeline_steps(
               execution_id,step_key,ordinal,step_type,status,definition_json,result_json,
               max_attempts,attempt_count,timeout_seconds,next_attempt_at,worker_id,
               lease_expires_at,created_at,started_at,completed_at,last_error
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("exec-a", "validate-topology", 0, "TOPOLOGY_VALIDATE", "FAILED",
             "{}", "{}", 1, 1, 300, None, None, None, now, now, now, "validation failed"),
        )
        connection.execute(
            """INSERT INTO pipeline_steps(
               execution_id,step_key,ordinal,step_type,status,definition_json,result_json,
               max_attempts,attempt_count,timeout_seconds,next_attempt_at,worker_id,
               lease_expires_at,created_at,started_at,completed_at,last_error
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("exec-a", "recover-provider", 1, "PROVIDER_RECONCILE", "RECOVERY_REQUIRED",
             "{}", "{}", 1, 1, 300, None, None, None, now, now, None, "recovery required"),
        )
        connection.execute(
            """INSERT INTO runs(
               run_id,display_id,firmware_version,lab_id,validation_profile,
               selected_tests_json,test_definition_versions_json,resolved_config_json,
               configuration_hash,repository_commit,lifecycle,outcome,created_at,
               started_at,completed_at,provenance,project_id
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("run-observed", "RUN-OBSERVED", "1.0", "lab-a", "smoke",
             "[]", "{}", "{}", "e" * 64, "test-commit", "COMPLETED", "VALIDATED",
             now, now, now, "NATIVE", "project-a"),
        )
        connection.execute(
            "INSERT INTO attempts(attempt_id,run_id,number,started_at,completed_at) VALUES(?,?,?,?,?)",
            ("attempt-observed", "run-observed", 1, now, now),
        )
        connection.execute(
            """INSERT INTO test_results(
               test_result_id,run_id,attempt_id,test_id,node_id,test_version,status,
               criticality,severity,evidence_state,error_reason,started_at,completed_at,
               provenance,failure_class,failure_reason,execution_pid,execution_metadata_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("result-observed", "run-observed", "attempt-observed", "wifi.throughput.minimum",
             "throughput-node", "1.0", "PASS", "ADVISORY", "LOW", "NOT_REQUIRED",
             None, now, now, "NATIVE", None, None, None, "{}"),
        )
        connection.execute(
            "INSERT INTO metrics(metric_id,test_result_id,name,unit,authoritative) VALUES(?,?,?,?,?)",
            ("metric-throughput", "result-observed", "throughput", "Mbps", 1),
        )
        connection.execute(
            """INSERT INTO samples(
               sample_id,metric_id,sequence,value,status,warmup,retried,captured_at,metadata_json
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("sample-throughput", "metric-throughput", 1, 95.5, "VALID", 0, 0, now, "{}"),
        )
        for artifact_id, artifact_type in (
            ("artifact-telemetry", "TELEMETRY"),
            ("artifact-lab-health", "LAB_HEALTH_SNAPSHOT"),
        ):
            connection.execute(
                """INSERT INTO artifacts(
                   artifact_id,run_id,test_result_id,test_node_id,attempt_id,artifact_type,path,
                   sha256,size_bytes,evidence_state,display_name,created_at,sensitivity_class,
                   retain_until,soft_deleted_at,provenance,failure_class,failure_reason,execution_pid
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (artifact_id, "run-observed", "result-observed", "throughput-node",
                 "attempt-observed", artifact_type, "evidence/" + artifact_id + ".json",
                 "f" * 64, 0, "COMPLETE", artifact_id, now, "INTERNAL", None, None,
                 "NATIVE", None, None, None),
            )


def test_operations_overview_includes_persisted_configuration_evidence_performance_and_action_items(tmp_path):
    import hashlib
    import json

    database = SQLiteDatabase(tmp_path / "overview-extended.sqlite")
    database.initialize()
    _seed_workspace(database)
    _seed_extended_operations_evidence(database)
    results_root = tmp_path / "results"
    results_root.mkdir()
    captured = ("2026-11-22T10:00:00+00:00", "2026-11-22T10:01:00+00:00")
    for index, (value, captured_at) in enumerate(((-54.0, captured[0]), (-50.0, captured[1]))):
        payload = {
            "snapshot_id": "wifi-snapshot-" + str(index),
            "run_id": "run-observed",
            "target": "client-a",
            "interface": "wlan0",
            "environment_class": "VIRTUAL_WIFI",
            "captured_at": captured_at,
            "points": [{
                "metric": "rssi_dbm",
                "value": value,
                "unit": "dBm",
                "environment_class": "VIRTUAL_WIFI",
                "source": "iw.link",
                "interface": "wlan0",
                "captured_at": captured_at,
                "metadata": {},
            }],
            "warnings": [],
        }
        file_path = results_root / ("wifi-" + str(index) + ".json")
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        file_path.write_bytes(encoded)
        with database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO artifacts(
                   artifact_id,run_id,test_result_id,test_node_id,attempt_id,artifact_type,path,
                   sha256,size_bytes,evidence_state,display_name,created_at,sensitivity_class,
                   retain_until,soft_deleted_at,provenance,failure_class,failure_reason,execution_pid
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("artifact-wifi-valid-" + str(index), "run-observed", "result-observed",
                 "throughput-node", "attempt-observed", "TELEMETRY", str(file_path),
                 hashlib.sha256(encoded).hexdigest(), len(encoded), "COMPLETE",
                 "wifi-telemetry-" + str(index), captured_at, "INTERNAL", None, None,
                 "NATIVE", None, None, None),
            )

    from dashboard.query import DashboardQueryService
    query = DashboardQueryService(database)
    query.results_root = results_root
    result = query.operations_overview("project-a", lab_id="lab-a")

    assert result["configuration"]["access"] == "AVAILABLE"
    assert result["configuration"]["deployments"] == 2
    assert result["configuration"]["by_status"] == {"FAILED": 1, "PARTIAL": 1}
    assert result["configuration"]["latest"]["status"] in {"FAILED", "PARTIAL"}
    assert result["evidence"]["telemetry_artifacts"] == 3
    assert result["evidence"]["valid_wifi_telemetry_artifacts"] == 2
    assert result["evidence"]["lab_health_snapshots"] == 1
    assert result["evidence"]["wifi_metrics"][0]["metric"] == "rssi_dbm"
    assert result["evidence"]["wifi_metrics"][0]["sample_count"] == 2
    assert result["evidence"]["wifi_metrics"][0]["mean_value"] == -52.0
    assert result["evidence"]["wifi_metrics"][0]["latest_value"] == -50.0
    assert result["evidence"]["wifi_metrics"][0]["unit"] == "dBm"
    assert result["evidence"]["wifi_metrics"][0]["interface"] == "wlan0"
    assert result["performance"]["status"] == "AVAILABLE"
    assert result["performance"]["metrics"][0] == {
        "name": "throughput",
        "unit": "Mbps",
        "value": 95.5,
        "mean_value": 95.5,
        "min_value": 95.5,
        "max_value": 95.5,
        "sample_count": 1,
        "authoritative": True,
        "captured_at": result["performance"]["metrics"][0]["captured_at"],
        "run_id": "run-observed",
        "test_id": "wifi.throughput.minimum",
    }
    assert result["pipelines"]["steps_by_status"] == {"FAILED": 1, "RECOVERY_REQUIRED": 1}
    assert result["pipelines"]["failed_steps"] == 1
    assert result["pipelines"]["recovery_required_steps"] == 1
    assert result["action_items"]["topology_apply_failures"] == 1
    assert result["action_items"]["configuration_deployment_failures"] == 2
    assert result["action_items"]["pipeline_recovery_required"] == 1
    assert result["action_items"]["regressions"]["status"] == "UNAVAILABLE"
    assert result["action_items"]["configuration_drift"]["status"] == "UNAVAILABLE"
    assert result["network_health"]["provider_health"] == "UNKNOWN"
    assert result["network_health"]["device_reachability"]["status"] == "UNAVAILABLE"
    assert result["network_health"]["configuration_sync"]["status"] == "UNAVAILABLE"
    assert result["network_health"]["infrastructure_resources"]["status"] == "UNAVAILABLE"


def test_operations_overview_uses_consistent_null_shapes_for_restricted_subsystems(tmp_path):
    database = SQLiteDatabase(tmp_path / "overview-all-restricted.sqlite")
    database.initialize()
    _seed_workspace(database)

    from dashboard.query import DashboardQueryService
    result = DashboardQueryService(database).operations_overview(
        "project-a",
        lab_id="lab-a",
        include_devices=False,
        include_topology=False,
        include_pipelines=False,
        include_runs=False,
        include_configuration=False,
        include_evidence=False,
        include_performance=False,
    )

    for key in ("devices", "topology", "pipelines", "runs", "configuration", "evidence", "performance"):
        assert result[key]["access"] == "RESTRICTED"
        assert result[key]["source"] is None
        assert result[key]["observed_at"] is None
    assert result["devices"]["by_status"] is None
    assert result["topology"]["revisions_by_status"] is None
    assert result["pipelines"]["steps_by_status"] is None
    assert result["runs"]["by_lifecycle"] is None
    assert result["configuration"]["by_status"] is None
    assert result["evidence"]["by_type"] is None
    assert result["performance"]["metrics"] is None


def test_operations_overview_is_read_only_and_query_observation_times_are_consistent(tmp_path):
    database = SQLiteDatabase(tmp_path / "overview-read-only.sqlite")
    database.initialize()
    _seed_workspace(database)
    tables = (
        "projects", "labs", "devices", "topology_profiles", "topology_revisions",
        "topology_apply_records", "gns3_lab_bindings", "pipeline_definitions",
        "pipeline_executions", "pipeline_steps", "device_configuration_deployments",
        "runs", "attempts", "test_results", "metrics", "samples", "artifacts",
    )
    with database.read_only_connection() as connection:
        before = {
            table: connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in tables
        }

    from dashboard.query import DashboardQueryService
    result = DashboardQueryService(database).operations_overview("project-a", lab_id="lab-a")

    with database.read_only_connection() as connection:
        after = {
            table: connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in tables
        }
    assert after == before
    observed_at = result["observed_at"]
    assert observed_at
    for section in ("labs", "devices", "topology", "providers", "pipelines", "runs",
                    "configuration", "evidence", "performance", "network_health"):
        assert result[section]["observed_at"] == observed_at
