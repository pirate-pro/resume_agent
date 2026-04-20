def test_health_and_jobs_endpoints(client) -> None:
    web_response = client.get("/")
    health_response = client.get("/api/v1/health")
    ready_response = client.get("/api/v1/ready")
    jobs_response = client.get("/api/v1/jobs")
    asset_response = client.get("/assets/styles.css")

    assert web_response.status_code == 200
    assert health_response.status_code == 200
    assert ready_response.status_code == 200
    assert jobs_response.status_code == 200
    assert asset_response.status_code == 200
    assert "Resume Control Room" in web_response.text
    assert "--paper" in asset_response.text
    assert health_response.json()["status"] == "ok"
    assert ready_response.json()["status"] == "ready"
    assert len(jobs_response.json()) == 20
