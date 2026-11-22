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
