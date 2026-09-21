# FASTQ 质控流水线台（FASTQ QC Pipeline Console）

从零实现的全栈演示：上传/选择小型 FASTQ → **Actor 队列流水线**质控 → 查看阶段状态与指标 → **给作业挂分类标记并按标记在服务端收缩历史**。

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
| `bioops` | `fastq123456` | 可提交质控作业 |
| `auditor` | `audit123456` | 只读结果，不可提交 |

## 一键启动

```bash
cd projects/09-fastq-qc-pipeline
docker compose up --build
```

镜像源：Postgres/Node/Nginx 使用 `docker.m.daocloud.io`；npm 使用 `registry.npmmirror.com`；pip 使用清华源。

启动后 seed 会写入：

- `demo-good-r1`：合格样例（可算出 `mean_quality` / `n_rate`）
- `demo-broken-malformed`：损坏样例（`ParseActor` 失败，后续阶段 skipped）

## API

- `POST /api/auth/login`
- `GET  /api/health`
- `GET  /api/samples`
- `POST /api/jobs` `{ "sampleId": 1 }` 或 `{ "fastqText": "..." }`
- `GET  /api/jobs`（可带 `?tag=night-qc`，**服务端**按单标记收缩）
- `GET  /api/jobs/{id}`（返回含 `tags`）
- `GET  /api/jobs/{id}/stages`
- `GET  /api/tags`（全库已使用标记名，去重）
- `PUT    /api/jobs/{id}/tags` `{ "name": "night-qc" }`（仅运维，幂等）
- `DELETE /api/jobs/{id}/tags/{name}`（仅运维）

## 分类标记（作业多标记）

- **权限**：仅运维 `bioops` 可挂/摘标记（`PUT`/`DELETE`）；审计员 `auditor` 对标记只读，可看可筛。
- **多标记**：一个作业可挂多个标记（同一作业下标记名唯一，重复挂同名幂等）。标记名仅允许小写字母、数字、`-`、`_` 且以字母/数字开头（≤64 字符）。
- **如何落库**：标记存于独立关联表 `job_tags`，每行 = `(job_id, name, created_by, created_at)`；挂载即插入一行、摘除即删除该行，作业删除时级联清除。标记名按字符串直接存储，不做规范化字典表。
- **按标记收缩必须打到服务端**：历史页点标记会请求 `GET /api/jobs?tag=…`，由后端 `JOIN job_tags` 在数据库过滤，**不是前端本地过滤**；筛选状态同步到 URL 查询参数 `?tag=`，可刷新/分享。
- **操作区**：历史列表上方有标记筛选操作区，列表每行有「分类标记」列可直接挂/摘。

## Verification（验收）

1. 打开 http://localhost:3184 ，用 `bioops` / `fastq123456` 登录。
2. **样例库** 看到 2 条样例 → 选合格样例 **提交质控作业**，再提交第二个作业。
3. 作业详情页看到四个 Actor 阶段均为成功，指标卡出现 `reads` / `mean_quality` / `n_rate`。
4. 再跑损坏样例：`ParseActor` = failed，其余 = skipped。
5. 进入 **历史**：在某个作业行点「标记」，挂上 `night-qc`（同一作业还可再挂其它标记）。
6. **验收口令**：点上方标记区的 `night-qc`（或直接访问 `/jobs?tag=night-qc`），历史**收缩到只剩挂了 `night-qc` 的那一条**，顶部出现服务端收缩提示；点「清除收缩」恢复全部。
7. 退出，用 `auditor` / `audit123456` 登录：可看历史与标记、可按标记收缩，但无挂/摘入口，直接调写接口返回 403；提交作业接口同样 403。
8. 健康检查：`curl http://localhost:8184/api/health`

## 本地单测（可选）

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

覆盖：畸形 FASTQ 在 `ParseActor` 失败；正常样例产出 `mean_quality`；
标记的多标记挂载、按单标记服务端收缩（night-qc）、大小写不敏感、审计员 403、摘除与非法名校验。

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
    tests/{test_actors,test_tags_api}.py
  frontend/
    Dockerfile nginx.conf
    src/
      components/JobTags.vue
      pages/{Login,Samples,JobSubmit,JobDetail,JobHistory}Page.vue
```
