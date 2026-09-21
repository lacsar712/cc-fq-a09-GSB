"""Seed database with demo users' samples (accounts are in-memory)."""

import os
import time
from pathlib import Path

from sqlalchemy.exc import OperationalError

from app.database import Base, SessionLocal, engine
from app.models import Job, JobTag, Sample
from app.pipeline.runner import create_job_stages, run_pipeline_sync


DATA_DIR = Path(__file__).resolve().parent / "data"


def wait_for_db(retries: int = 30, delay: float = 1.0) -> None:
    for i in range(retries):
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            return
        except OperationalError:
            print(f"waiting for db... ({i + 1}/{retries})")
            time.sleep(delay)
    raise RuntimeError("database not ready")


def seed_samples(db) -> None:
    if db.query(Sample).count() > 0:
        print("samples already seeded, skip")
        return

    good = (DATA_DIR / "good.fastq").read_text(encoding="utf-8")
    broken = (DATA_DIR / "broken.fastq").read_text(encoding="utf-8")

    db.add(
        Sample(
            name="demo-good-r1",
            description="合格小型 FASTQ 样例（含少量 N）",
            is_broken=False,
            fastq_content=good,
        )
    )
    db.add(
        Sample(
            name="demo-broken-malformed",
            description="损坏样例：缺少 + 分隔行 / 长度不一致，ParseActor 应失败",
            is_broken=True,
            fastq_content=broken,
        )
    )
    db.commit()
    print("seeded 2 samples")


def seed_jobs(db) -> None:
    """补 2 条跑完的演示作业，并给合格作业挂 baseline 标记，方便演示按标记收缩。"""
    if db.query(Job).count() > 0:
        print("jobs already seeded, skip")
        return

    for name in ("demo-good-r1", "demo-broken-malformed"):
        sample = db.query(Sample).filter(Sample.name == name).first()
        if not sample:
            continue
        job = Job(
            sample_id=sample.id,
            sample_name=sample.name,
            status="pending",
            created_by="bioops",
            fastq_snapshot=sample.fastq_content,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        create_job_stages(db, job.id)
        run_pipeline_sync(db, job)

    good_job = (
        db.query(Job)
        .filter(Job.sample_name == "demo-good-r1")
        .order_by(Job.id)
        .first()
    )
    if good_job:
        db.add(JobTag(job_id=good_job.id, tag="baseline", created_by="bioops"))
        db.commit()
    print("seeded 2 demo jobs (good one tagged 'baseline')")


def seed() -> None:
    wait_for_db()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_samples(db)
        seed_jobs(db)
    finally:
        db.close()


if __name__ == "__main__":
    seed()
