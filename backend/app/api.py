from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import distinct
from sqlalchemy.orm import Session, joinedload, selectinload

from app.auth import authenticate_user, create_access_token, get_current_user, require_bioops
from app.database import SessionLocal, get_db
from app.models import Job, JobStage, JobTag, Sample
from app.pipeline.runner import create_job_stages, run_pipeline_sync
from app.schemas import (
    HealthOut,
    JobCreate,
    JobListItem,
    JobOut,
    LoginRequest,
    SampleOut,
    StageOut,
    TagCreate,
    TagOut,
    TokenResponse,
    normalize_tag_name,
)


router = APIRouter(prefix="/api")


def _run_job_background(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            run_pipeline_sync(db, job)
    finally:
        db.close()


@router.get("/health", response_model=HealthOut)
def health():
    return HealthOut(status="ok", service="fastq-qc-pipeline")


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest):
    user = authenticate_user(body.username.strip(), body.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token(user["username"], user["role"])
    return TokenResponse(
        access_token=token,
        username=user["username"],
        role=user["role"],
    )


@router.get("/samples", response_model=list[SampleOut])
def list_samples(_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Sample).order_by(Sample.id).all()


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(
    body: JobCreate,
    background: BackgroundTasks,
    user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    sample_id = body.sampleId
    fastq_text = (body.fastqText or "").strip() if body.fastqText else ""
    sample_name = "自定义输入"
    sample = None

    if sample_id is not None:
        sample = db.query(Sample).filter(Sample.id == sample_id).first()
        if not sample:
            raise HTTPException(status_code=404, detail="样例不存在")
        fastq_text = sample.fastq_content
        sample_name = sample.name
    elif not fastq_text:
        raise HTTPException(status_code=400, detail="请提供 sampleId 或 fastqText")

    job = Job(
        sample_id=sample.id if sample else None,
        sample_name=sample_name,
        status="pending",
        created_by=user["username"],
        fastq_snapshot=fastq_text,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    create_job_stages(db, job.id)
    background.add_task(_run_job_background, job.id)

    job = (
        db.query(Job)
        .options(joinedload(Job.stages), joinedload(Job.tags))
        .filter(Job.id == job.id)
        .first()
    )
    return job


@router.get("/jobs", response_model=list[JobListItem])
def list_jobs(
    tag: str | None = None,
    _user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """作业历史。带 tag 查询参数时在服务端按单标记收缩（精确、大小写不敏感）。"""
    query = db.query(Job).options(selectinload(Job.tags))
    if tag is not None and tag.strip():
        try:
            tag_name = normalize_tag_name(tag)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        query = query.join(JobTag, JobTag.job_id == Job.id).filter(JobTag.name == tag_name)
    return query.order_by(Job.id.desc()).all()


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, _user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    job = (
        db.query(Job)
        .options(joinedload(Job.stages), joinedload(Job.tags))
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    return job


@router.get("/jobs/{job_id}/stages", response_model=list[StageOut])
def get_job_stages(
    job_id: int, _user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    return (
        db.query(JobStage)
        .filter(JobStage.job_id == job_id)
        .order_by(JobStage.stage_order)
        .all()
    )


def _get_job_or_404(db: Session, job_id: int) -> Job:
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    return job


@router.get("/tags", response_model=list[str])
def list_tags(_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """全库已使用的标记名（去重、字典序），供历史页标记操作区展示。"""
    rows = db.query(distinct(JobTag.name)).order_by(JobTag.name).all()
    return [r[0] for r in rows]


@router.put("/jobs/{job_id}/tags", response_model=TagOut)
def add_job_tag(
    job_id: int,
    body: TagCreate,
    user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    """运维给作业挂标记（一作业可多标记，重复挂同名幂等）。审计员 403。"""
    _get_job_or_404(db, job_id)
    try:
        name = body.normalized_name()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    existing = (
        db.query(JobTag)
        .filter(JobTag.job_id == job_id, JobTag.name == name)
        .first()
    )
    if existing:
        return existing

    tag = JobTag(job_id=job_id, name=name, created_by=user["username"])
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/jobs/{job_id}/tags/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job_tag(
    job_id: int,
    name: str,
    user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    """运维摘除作业上的某个标记。审计员 403。"""
    _get_job_or_404(db, job_id)
    try:
        tag_name = normalize_tag_name(name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    tag = (
        db.query(JobTag)
        .filter(JobTag.job_id == job_id, JobTag.name == tag_name)
        .first()
    )
    if not tag:
        raise HTTPException(status_code=404, detail="该作业未挂此标记")
    db.delete(tag)
    db.commit()
    return None
