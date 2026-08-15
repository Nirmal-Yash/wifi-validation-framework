from dashboard.app import app
from dashboard.db import connection


def test_topology_workspace_renders():
    app.config.update(TESTING=True)
    response = app.test_client().get('/topology')
    assert response.status_code == 200
    assert b'Topology Command Center' in response.data
    assert b'COMPONENT PALETTE' in response.data


def test_active_version_delete_is_rejected():
    app.config.update(TESTING=True)
    with connection() as conn:
        row = conn.execute("SELECT topology_id,id FROM topology_versions WHERE status='ACTIVE' ORDER BY id LIMIT 1").fetchone()
    if not row:
        return
    response = app.test_client().delete(f"/api/topologies/{row['topology_id']}/versions/{row['id']}")
    assert response.status_code == 409
    assert response.get_json()['error']['code'] == 'VERSION_DELETE_REJECTED'
