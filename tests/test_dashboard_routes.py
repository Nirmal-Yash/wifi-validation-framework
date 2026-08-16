from dashboard.app import app


def test_health_and_core_pages():
    app.config.update(TESTING=True)
    client = app.test_client()
    for path in ("/", "/topology", "/history", "/about", "/health", "/api/topology_data"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code, response.data[:500])


def test_unknown_page_is_not_server_error():
    app.config.update(TESTING=True)
    response = app.test_client().get("/does-not-exist")
    assert response.status_code == 404


def test_execution_api_contract():
    app.config.update(TESTING=True)
    client = app.test_client()
    response = client.get("/api/executions?limit=5")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert isinstance(payload["executions"], list)


def test_missing_execution_is_not_found():
    app.config.update(TESTING=True)
    response = app.test_client().get("/api/executions/999999999")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "EXECUTION_NOT_FOUND"


def test_regressions_api_contract():
    app.config.update(TESTING=True)
    response = app.test_client().get("/api/regressions")
    assert response.status_code == 200
    assert response.get_json()["success"] is True
