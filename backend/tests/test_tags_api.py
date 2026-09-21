"""API tests for job tags: multi-tag attach, server-side filtering, RBAC."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Job


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    # Seed two bare jobs directly (pipeline behaviour is covered in test_actors).
    db = TestingSession()
    db.add(Job(created_by="bioops", sample_name="自定义输入", fastq_snapshot="@a\nACGT\n+\nIIII\n"))
    db.add(Job(created_by="bioops", sample_name="自定义输入", fastq_snapshot="@b\nACGT\n+\nIIII\n"))
    db.commit()
    db.close()

    # NOTE: do not enter TestClient as a context manager — that would trigger the
    # app lifespan and try to create tables on the real (Postgres) engine.
    c = TestClient(app)
    yield c

    app.dependency_overrides.clear()


def _token(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def bioops_headers(client):
    return _token(client, "bioops", "fastq123456")


@pytest.fixture()
def auditor_headers(client):
    return _token(client, "auditor", "audit123456")


def test_attach_multiple_tags_and_list(client, bioops_headers):
    r = client.put("/api/jobs/1/tags", json={"name": "night-qc"}, headers=bioops_headers)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "night-qc"

    r = client.put("/api/jobs/1/tags", json={"name": "routine"}, headers=bioops_headers)
    assert r.status_code == 200, r.text

    # idempotent: attaching the same name again does not duplicate
    r = client.put("/api/jobs/1/tags", json={"name": "night-qc"}, headers=bioops_headers)
    assert r.status_code == 200
    assert r.json()["name"] == "night-qc"

    r = client.get("/api/tags", headers=bioops_headers)
    assert r.status_code == 200
    assert sorted(r.json()) == ["night-qc", "routine"]

    r = client.get("/api/jobs/1", headers=bioops_headers)
    names = sorted(t["name"] for t in r.json()["tags"])
    assert names == ["night-qc", "routine"]


def test_filter_by_single_tag_returns_only_matching_job(client, bioops_headers):
    """验收口令：挂 night-qc 后按标记收缩只剩它。"""
    client.put("/api/jobs/1/tags", json={"name": "night-qc"}, headers=bioops_headers)
    client.put("/api/jobs/2/tags", json={"name": "routine"}, headers=bioops_headers)

    r = client.get("/api/jobs", headers=bioops_headers)
    assert r.status_code == 200
    assert len(r.json()) == 2

    r = client.get("/api/jobs", params={"tag": "night-qc"}, headers=bioops_headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["id"] == 1
    assert [t["name"] for t in rows[0]["tags"]] == ["night-qc"]


def test_tag_filter_is_case_insensitive(client, bioops_headers):
    client.put("/api/jobs/1/tags", json={"name": "night-qc"}, headers=bioops_headers)
    r = client.get("/api/jobs", params={"tag": "NIGHT-QC"}, headers=bioops_headers)
    assert r.status_code == 200
    assert [row["id"] for row in r.json()] == [1]


def test_auditor_is_read_only(client, bioops_headers, auditor_headers):
    # auditor can read tags
    client.put("/api/jobs/1/tags", json={"name": "night-qc"}, headers=bioops_headers)
    r = client.get("/api/jobs", params={"tag": "night-qc"}, headers=auditor_headers)
    assert r.status_code == 200
    assert len(r.json()) == 1

    # auditor cannot attach
    r = client.put("/api/jobs/1/tags", json={"name": "x"}, headers=auditor_headers)
    assert r.status_code == 403

    # auditor cannot remove
    r = client.delete("/api/jobs/1/tags/night-qc", headers=auditor_headers)
    assert r.status_code == 403


def test_detach_tag_removes_it_from_filter(client, bioops_headers):
    client.put("/api/jobs/1/tags", json={"name": "night-qc"}, headers=bioops_headers)
    r = client.delete("/api/jobs/1/tags/night-qc", headers=bioops_headers)
    assert r.status_code == 204

    r = client.get("/api/jobs", params={"tag": "night-qc"}, headers=bioops_headers)
    assert r.status_code == 200
    assert r.json() == []

    # deleting again -> 404
    r = client.delete("/api/jobs/1/tags/night-qc", headers=bioops_headers)
    assert r.status_code == 404


def test_invalid_tag_name_rejected(client, bioops_headers):
    r = client.put("/api/jobs/1/tags", json={"name": "中文标记"}, headers=bioops_headers)
    assert r.status_code == 422

    r = client.put("/api/jobs/1/tags", json={"name": "  "}, headers=bioops_headers)
    assert r.status_code == 422


def test_tag_operations_on_missing_job_404(client, bioops_headers):
    r = client.put("/api/jobs/999/tags", json={"name": "night-qc"}, headers=bioops_headers)
    assert r.status_code == 404
