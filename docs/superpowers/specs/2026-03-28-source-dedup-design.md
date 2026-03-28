# Source Deduplication & Cross-User Content Clone

## Problem

用户可以多次提交同一 URL 或 PDF，每次都跑完整摄入管线（6 个 LLM 阶段），浪费资源。不同用户提交相同资源时也会重复处理，而内容（chunks、concepts、embeddings、lessons、labs）是确定性的，应该复用。

## 资源身份识别：content_key

仅靠 URL 字符串匹配不可靠（同一视频有多种 URL 格式）。使用 `content_key` 作为资源唯一标识：

| 平台 | content_key 格式 | 提取方式 | 示例 |
|------|-----------------|---------|------|
| Bilibili | `bilibili:{bv_id}` | URL 正则提取 BV 号 | `bilibili:BV1gZ4y1F7hS` |
| YouTube | `youtube:{video_id}` | URL 正则提取 Video ID | `youtube:kCc8FmEb1nY` |
| PDF | `pdf:{md5}` | 上传时对文件内容算 MD5 | `pdf:a1b2c3d4e5f67890` |

所有去重匹配基于 `content_key`，不再依赖 URL 字符串。

**提取规则：**

```python
import re, hashlib

def extract_content_key(source_type: str, url: str | None = None, file_content: bytes | None = None) -> str | None:
    """Extract a unique content key for deduplication."""
    if source_type == "bilibili" and url:
        # 匹配 BV 号: BV + 10 位字母数字
        match = re.search(r"(BV[a-zA-Z0-9]{10})", url)
        return f"bilibili:{match.group(1)}" if match else None
    elif source_type == "youtube" and url:
        # 匹配 video ID: ?v=xxx 或 youtu.be/xxx
        match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
        return f"youtube:{match.group(1)}" if match else None
    elif source_type == "pdf" and file_content:
        md5 = hashlib.md5(file_content).hexdigest()
        return f"pdf:{md5}"
    return None
```

## Design

### 三层机制

| 层 | 职责 |
|---|------|
| **API 层** | 计算 content_key + 同用户 409 去重 + 跨用户 ref_source 匹配 + 派发 clone 或标记 waiting |
| **Worker 层** | `ingest_source` 完成/失败时 Redis publish；新增 `clone_source` task |
| **Redis pub/sub** | channel `source:done:{content_key_hash}`，payload: `{source_id, status}` |

### 去重规则

| 场景 | 行为 |
|------|------|
| 同用户 + 同 content_key + 非 error 状态 | 409 拒绝，提示"已导入或正在处理中" |
| 同用户 + 同 content_key + error 状态 | 允许重试，正常走 pipeline |
| 跨用户 + 同 content_key + 已有 ready ref_source | 创建 Source(waiting_donor) → 立即派发 `clone_source` |
| 跨用户 + 同 content_key + in-progress ref_source | 创建 Source(waiting_donor) → 等 Redis 通知后派发 `clone_source` |
| 跨用户 + 同 content_key + ref_source 失败 | 等待者也标记为 error，用户自行决定是否重新导入 |
| 无匹配 content_key | 正常走 `ingest_source` |
| content_key 提取失败（URL 格式无法识别） | 正常走 `ingest_source`，不做去重 |

### 流程图

```
User B 提交资源
  ↓
API: 计算 content_key (extract_content_key)
  ├─ content_key 为 None → 正常 ingest_source，不做去重
  └─ content_key 有值 ↓
API: 同用户查重 (content_key + created_by + status != error)
  ├─ 命中 → 409
  └─ 未命中 ↓
API: 跨用户查 ref_source (content_key + status != error + created_by != user.id)
  ├─ ref_source.status == ready
  │   → 创建 Source(status=waiting_donor, ref_source_id=ref.id)
  │   → 派发 clone_source(source_id, ref_source_id)
  ├─ ref_source.status 为 in-progress (pending/extracting/analyzing/...)
  │   → 创建 Source(status=waiting_donor, ref_source_id=ref.id)
  │   → 不派发 task，等 Redis 通知
  └─ 无 ref_source
      → 创建 Source(status=pending)
      → 派发 ingest_source(source_id)
```

```
ingest_source 完成 (status=ready):
  → Redis PUBLISH source:done:{content_key_hash} {"source_id": "...", "status": "ready"}

ingest_source 失败 (status=error):
  → Redis PUBLISH source:done:{content_key_hash} {"source_id": "...", "status": "error"}

Redis subscriber (Celery worker_ready signal 启动的后台线程):
  监听 source:done:* pattern
  收到消息:
    → 查 DB: SELECT * FROM sources WHERE ref_source_id = {source_id} AND status = 'waiting_donor'
    ├─ payload.status == "ready"
    │   → 为每个 waiting source 派发 clone_source(source_id, ref_source_id)
    └─ payload.status == "error"
        → 将每个 waiting source 标记为 error (metadata_ 写入错误信息 "引用源处理失败")
```

### clone_source task

从 ref_source 克隆内容到 target source：

1. 加载 target + ref_source，验证 ref_source 仍为 ready（否则标记 target 为 error）
2. 复制 `title`、`raw_content`、`metadata_`（含 lesson_by_page、labs_by_page、summaries）
3. 克隆 ContentChunk 行：新 source_id，复制 text、embedding、metadata_
4. 克隆 ConceptSource 行：新 source_id，指向同一全局 Concept
5. 标记 target status = "ready"

不需要 LLM 调用、不需要 embedding API 调用。秒级完成。

### DB 变更

Source 表新增：
- `content_key`: String, nullable, indexed — 资源唯一标识符（如 `bilibili:BV1gZ4y1F7hS`）
- `ref_source_id`: UUID FK to sources.id, nullable — 记录"我在等谁/我从谁克隆"

Source 新增状态值：
- `waiting_donor` — 等待 ref_source 完成，前端显示 "复用已有资源中..."

### 前端变更

**API 层 (`api.ts`):**
- `createSourceFromURL` 和 `createSourceFromFile` 识别 409 响应，抛 `DuplicateSourceError`

**导入页 (`import/page.tsx`):**
- catch `DuplicateSourceError`：显示"该链接/文件已导入完成"或"正在导入中"

**Dashboard (`page.tsx`):**
- `taskStateLabel` 新增 `waiting_donor: "复用已有资源中..."`

### 不做的事

- DB unique constraint（error 状态需要允许同 content_key 多行）
- Bilibili 分P 去重（不同 p= 参数视为同一视频，MVP 暂不区分）
- Worker 分布式锁

### 涉及文件

| 文件 | 改动 |
|------|------|
| `backend/app/db/models/source.py` | 加 `content_key` + `ref_source_id` 字段 |
| `backend/alembic/versions/XXXX_add_content_key_and_ref_source_id.py` | Migration |
| `backend/app/api/routes/sources.py` | `extract_content_key` + 同用户去重 + 跨用户 ref 匹配 + 条件派发 |
| `backend/app/worker/tasks/content_ingestion.py` | `clone_source` task + ingest 完成/失败时 Redis publish |
| `backend/app/worker/celery_app.py` | worker_ready signal 注册 subscriber 线程 |
| `backend/app/worker/ref_subscriber.py` | Redis subscriber 后台线程实现 |
| `frontend/src/lib/api.ts` | `DuplicateSourceError` + 409 处理 |
| `frontend/src/app/import/page.tsx` | 友好错误提示 |
| `frontend/src/app/page.tsx` | `waiting_donor` 状态标签 |
