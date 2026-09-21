# FASTQ 质控流水线台（FASTQ QC Pipeline Console）

从零实现的全栈演示：上传/选择小型 FASTQ → **Actor 队列流水线**质控 → 查看阶段状态与指标。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11 · FastAPI · SQLAlchemy · PostgreSQL |
| 流水线 | `ParseActor` → `QualityHistActor` → `NContentActor` → `ReportActor`（asyncio.Queue） |
| 前端 | Vue 3 · Vite · Quasar · 中文 UI · nginx `/api` 反代 |
| 基建 | docker compose（db / backend / seed / frontend） |

## 端口

| 服务 | 地址 |
|------|------|
| Frontend | http://localhost:3184 |
| Backend API | http://localhost:8184 |
| PostgreSQL | localhost:54384 |

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| `bioops` | `fastq123456` | 可提交质控作业、给作业挂/改分类标记 |
| `auditor` | `audit123456` | 只读结果与标记，不可提交、不可改标记 |

## 一键启动

```bash
cd projects/09-fastq-qc-pipeline
docker compose up --build
```

镜像源：Postgres/Node/Nginx 使用 `docker.m.daocloud.io`；npm 使用 `registry.npmmirror.com`；pip 使用清华源。

启动后 seed 会写入：

- `demo-good-r1`：合格样例（可算出 `mean_quality` / `n_rate`）
- `demo-broken-malformed`：损坏样例（`ParseActor` 失败，后续阶段 skipped）
- 2 条已跑完的演示作业（合格作业预挂 `baseline` 标记，便于演示按标记收缩）

## 作业分类标记

- 一个作业可挂**多个**标记（如 `night-qc`）；仅 `bioops` 可挂/改，`auditor` 只读。
- **落库方式**：标记存于 PostgreSQL `job_tags` 表（`job_id` / `tag` / `created_by` / `created_at`，
  `(job_id, tag)` 唯一约束，作业删除时级联清理）；保存走 `PUT /api/jobs/{id}/tags` 整体替换。
- **按标记收缩**：历史页「标记操作区」选择单个标记后，请求 `GET /api/jobs?tag=<标记>` 由**服务端 SQL 过滤**返回，前端不做本地筛选。
- 标记名规则：字母/数字开头，可含 `.` `_` `-`，最长 32 字符；单个作业最多 8 个。

## Verification（验收）

1. 打开 http://localhost:3184 ，用 `bioops` / `fastq123456` 登录。
2. **样例库** 看到 2 条样例 → 选合格样例 **提交质控作业**。
3. 作业详情页看到四个 Actor 阶段均为成功，指标卡出现 `reads` / `mean_quality` / `n_rate`。
4. 再跑损坏样例：`ParseActor` = failed，其余 = skipped。
5. **标记验收口令**：在 **历史** 页给某条作业挂上 `night-qc`（行内「标记」按钮），
   再在「标记操作区」按 `night-qc` 收缩 → 列表只剩挂该标记的作业（请求打到 `GET /api/jobs?tag=night-qc`）。
6. 退出，用 `auditor` / `audit123456` 登录：可看历史、详情与标记，但无挂标入口；
   提交作业 / 改标记接口均返回 403。
7. 健康检查：`curl http://localhost:8184/api/health`

## API

- `POST /api/auth/login`
- `GET  /api/health`
- `GET  /api/samples`
- `POST /api/jobs` `{ "sampleId": 1 }` 或 `{ "fastqText": "..." }`
- `GET  /api/jobs`（可选 `?tag=<标记>`：服务端按单标记收缩）
- `GET  /api/jobs/{id}`
- `GET  /api/jobs/{id}/stages`
- `PUT  /api/jobs/{id}/tags` `{ "tags": ["night-qc"] }`（仅 `bioops`，整体替换落库）
- `GET  /api/tags`（全部标记及各自作业数）

## 本地单测（可选）

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

覆盖：畸形 FASTQ 在 `ParseActor` 失败；正常样例产出 `mean_quality`。

## 目录结构

```
09-fastq-qc-pipeline/
  PRD.md
  README.md
  docker-compose.yml
  backend/
    Dockerfile
    seed.py
    data/{good,broken}.fastq
    app/
      main.py api.py auth.py models.py schemas.py
      pipeline/{actors,runner}.py
    tests/test_actors.py
  frontend/
    Dockerfile nginx.conf
    src/pages/{Login,Samples,JobSubmit,JobDetail,JobHistory}Page.vue
```
