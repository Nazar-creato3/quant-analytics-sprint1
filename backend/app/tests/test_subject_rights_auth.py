"""GA16-027: subject export/delete are not public and not cross-user."""
from fastapi.testclient import TestClient

from app.main import app
from app.tests.qa_session import auth_headers, clear_session_user


def setup_function() -> None:
    clear_session_user()


def teardown_function() -> None:
    clear_session_user()


def test_subject_rights_need_session_and_reject_foreign_id() -> None:
    client = TestClient(app)
    assert client.get("/api/v1/subject-rights/export", params={"user_id": "victim"}).status_code == 401
    assert client.post("/api/v1/subject-rights/delete", json={"user_id": "victim"}).status_code == 401
    headers = auth_headers("alice")
    forbidden = client.get("/api/v1/subject-rights/export", params={"user_id": "victim"}, headers=headers)
    assert forbidden.status_code == 403
    erased = client.post("/api/v1/subject-rights/delete", json={"user_id": "victim"}, headers=headers)
    assert erased.status_code == 403
