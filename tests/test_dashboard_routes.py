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
