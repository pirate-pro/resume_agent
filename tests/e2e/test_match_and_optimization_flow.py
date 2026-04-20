from pathlib import Path


def test_end_to_end_match_and_optimization_flow(client, sample_resume_docx, task_worker) -> None:
    with sample_resume_docx.open("rb") as file_handle:
        upload_response = client.post(
            "/api/v1/resumes/upload",
            files={"file": ("resume.docx", file_handle, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert upload_response.status_code == 200
    upload_payload = upload_response.json()

    match_response = client.post(
        "/api/v1/match-tasks",
        json={"resume_id": upload_payload["resume_id"], "target_city": "Shanghai"},
    )
    assert match_response.status_code == 200
    accepted_match = match_response.json()
    assert accepted_match["task_status"] == "queued"
    assert accepted_match["stage"] == "intake"

    assert task_worker.run_until_idle(task_type="match") == 1
    match_payload = client.get(f"/api/v1/match-tasks/{accepted_match['task_id']}").json()
    assert match_payload["task_status"] == "completed"
    assert match_payload["stage"] == "deliver"
    assert len(match_payload["matches"]) >= 1
    top_match = match_payload["matches"][0]
    assert top_match["city"] == "Shanghai"
    assert top_match["score_card"]["overall_score"] > 0.6
    assert any(event["event_type"] == "stage.profile.completed" for event in match_payload["events"])

    optimization_response = client.post(
        "/api/v1/optimization-tasks",
        json={"resume_id": upload_payload["resume_id"], "target_job_id": top_match["job_posting_id"]},
    )
    assert optimization_response.status_code == 200
    accepted_optimization = optimization_response.json()
    assert accepted_optimization["task_status"] == "queued"
    assert accepted_optimization["stage"] == "optimize"

    assert task_worker.run_until_idle(task_type="optimization") == 1
    optimization_payload = client.get(
        f"/api/v1/optimization-tasks/{accepted_optimization['task_id']}"
    ).json()
    assert optimization_payload["status"] == "completed"
    assert optimization_payload["task_status"] == "completed"
    assert optimization_payload["stage"] == "deliver"
    assert "## 核心技能" in optimization_payload["optimized_resume_markdown"]
    assert optimization_payload["review_report"]["allow_delivery"] is True
    assert any(event["event_type"] == "stage.review.completed" for event in optimization_payload["events"])
    optimize_event = next(event for event in optimization_payload["events"] if event["event_type"] == "stage.optimize.completed")
    review_event = next(event for event in optimization_payload["events"] if event["event_type"] == "stage.review.completed")
    optimize_trace = optimize_event["payload"]["agent"]["metadata"]["run_trace"]
    review_trace = review_event["payload"]["agent"]["metadata"]["run_trace"]
    assert Path(optimize_trace["summary_path"]).exists()
    assert Path(optimize_trace["timeline_path"]).exists()
    assert Path(review_trace["summary_path"]).exists()
    assert Path(review_trace["timeline_path"]).exists()
