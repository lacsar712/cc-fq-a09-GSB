import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import and_, func
from sqlalchemy.orm import Session, joinedload

from app.auth import authenticate_user, create_access_token, get_current_user, require_bioops
from app.database import SessionLocal, get_db
from app.models import Job, JobStage, JobTag, Sample
from app.pipeline.runner import create_job_stages, run_pipeline_sync
from app.schemas import (
    HealthOut,
    JobCreate,
    JobListItem,
    JobOut,
    JobTagsUpdate,
    LoginRequest,
    SampleOut,
    StageOut,
    TagOut,
    TokenResponse,
)


router = APIRouter(prefix="/api")

# 标记名规则：字母/数字开头，可含字母、数字、点、下划线、连字符，最长 32 字符
TAG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
MAX_TAGS_PER_JOB = 8


def normalize_tags(raw_tags: list[str]) -> list[str]:
    """清洗标记集合：去空白、去重（保序）、校验格式与数量，不合法直接 400。"""
    names: list[str] = []
    for raw in raw_tags:
        name = (raw or "").strip()
        if not name:
            continue
        if not TAG_PATTERN.match(name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"标记名不合法：{name}（字母/数字开头，可含 . _ -，最长 32 字符）",
            )
        if name not in names:
            names.append(name)
    if len(names) > MAX_TAGS_PER_JOB:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"单个作业最多 {MAX_TAGS_PER_JOB} 个标记",
        )
    return names


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
    """作业历史。带 ?tag=xxx 时在服务端按单个标记收缩（SQL 过滤，非前端筛）。"""
    query = db.query(Job).options(joinedload(Job.tags))
    if tag and tag.strip():
        name = tag.strip()
        query = query.join(JobTag, and_(JobTag.job_id == Job.id, JobTag.tag == name))
    return query.order_by(Job.id.desc()).all()


@router.get("/tags", response_model=list[TagOut])
def list_tags(_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """全部已落库标记及各自挂到的作业数（供历史页过滤下拉用）。"""
    rows = (
        db.query(JobTag.tag, func.count(JobTag.id))
        .group_by(JobTag.tag)
        .order_by(JobTag.tag)
        .all()
    )
    return [TagOut(name=name, job_count=count) for name, count in rows]


@router.put("/jobs/{job_id}/tags", response_model=JobOut)
def set_job_tags(
    job_id: int,
    body: JobTagsUpdate,
    user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    """整体替换一个作业的标记（仅运维）。空列表 = 清空该作业全部标记。"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    names = normalize_tags(body.tags)

    # 先删后插并 flush，避免同事务内唯一约束 (job_id, tag) 冲突
    db.query(JobTag).filter(JobTag.job_id == job_id).delete(synchronize_session=False)
    db.flush()
    for name in names:
        db.add(JobTag(job_id=job_id, tag=name, created_by=user["username"]))
    db.commit()

    return (
        db.query(Job)
        .options(joinedload(Job.stages), joinedload(Job.tags))
        .filter(Job.id == job_id)
        .first()
    )


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
