# Section Planning — Topic-Bucket Grouping for Video Chunks

**Status**: 草案 v2 · 待评审
**作者**: catundercar
**日期**: 2026-05-15
**关联 issue**: 待开（Linear SOC-#）
**v1 → v2 关键调整**：见文末 Changelog。

---

## 1. 背景与现状

资料从原始内容到课程的拆分管线：

```
源材料 ─ extractor ─▶ RawContentChunk[]
                       │
                       ├─ content_analyzer ─▶ AnalyzedChunk（topic/summary/concepts/...）
                       │                          │
                       ├─ embedding ─▶ ContentChunk 行（带 embedding）
                       │
                       ▼
              course_generator._build_sections
                       │
                       ├─ has_page_index?
                       │     ├─ true  → 按 (source_id, page_index) 聚合：1 page = 1 section
                       │     └─ false → per_chunk_mode：1 chunk = 1 section
                       │
                       ▼
                   Section 行
```

| 资料类型 | 当前聚合规则 | 19-min 视频实例 |
|---|---|---|
| PDF / Markdown 有 `page_index` | 同 page 合并 | 不适用 |
| 视频 / 字幕 / 长文本 | per_chunk_mode（1:1） | 19 chunks → 19 sections |

### 痛点

视频被切成等时长 chunk（典型 60s 一片），每节内容碎且长度均匀化，丢失了主题边界。读者看到一连串没有逻辑分组的小节，无法形成"这部分讲完了，下一部分进入新话题"的认知。

## 2. 目标 / 非目标

**目标**
- 视频 / 长文本类资料按**主题边界**聚合成 4–12 个有意义的 section
- 不动 PDF / 带 `page_index` 路径
- 失败时自动回退到 per-chunk，导入流程不能因此失败
- 支持超长内容（4h+）

**非目标**
- 不重做 chunk extraction
- 不引入跨 source 的主题归纳
- 不暴露给用户的"手动调整 bucket"UI（v2 范围外）
- 不做纯 embedding 的无 LLM 分桶（v2 范围外）

## 3. 设计

### 3.1 数据模型

`ContentChunk.metadata_` 新增两个字段（JSONB 内嵌，免迁移）：

```python
{
    "section_bucket": 3,                               # int，相邻同值聚合
    "section_bucket_topic": "图像识别中的层次特征",     # 可选，bucket 人类可读名
}
```

`Source.metadata_["section_planner_stats"]` 存储分桶过程的统计与版本信息（见 §6 监控）。

### 3.2 新组件 `SectionPlanner`

`backend/app/services/section_planner.py`

```python
from dataclasses import dataclass

@dataclass
class BucketAssignment:
    bucket_id: int
    bucket_topic: str | None  # nullable; LLM may omit a name

class SectionPlanner:
    def __init__(self, model_router: ModelRouter): ...

    async def plan(
        self,
        chunks: list[RawContentChunk],
        analyses: list[ChunkAnalysis],   # 复用 ContentAnalyzer 的 summary
        embeddings: list[list[float]],   # 来自已入库 ContentChunk（见 §3.5）
        title: str,
    ) -> list[BucketAssignment]:
        """Returns one BucketAssignment per input chunk.
        Same length / same order as input.
        Falls back to per-chunk (bucket_id = chunk_index) on any error."""
```

#### 三层回退

```
┌─────────────────────────────────────────────────────────┐
│ Layer 1: single-pass skeleton                           │
│   - 输入: [(idx, size, summary, boundary_hint), ...]    │
│     • size = duration_sec (视频/音频) 或 word_count (文本) │
│     • summary 来自 ContentAnalyzer                       │
│     • boundary_hint 来自相邻 chunk embedding 余弦距离      │
│   - 输出: {buckets: [...], assignments: [...]}          │
│   - 触发: 默认                                          │
│   - 体积: 120 chunks ≈ 30KB in（summary 比原文截断更紧凑）  │
└─────────────────────────────────────────────────────────┘
             │ skeleton 输入超过 budget (> 64KB)
             ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 2: windowed-skeleton (2-level)                    │
│   - 按 30 chunk/窗口切分，每窗口独立分桶                  │
│   - 窗口边界缝合：TODO (Phase 2)                         │
│     候选方案：重叠 3 chunk + LLM 在合并 pass 中判合并     │
│     v1 暂时接受窗口边界的潜在假切分                       │
│   - 触发: 8+ 小时 / >>120 chunks / 极慢本地模型           │
└─────────────────────────────────────────────────────────┘
             │ 任何 LLM 失败 / 解析失败 / 超时
             ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 3: per-chunk fallback                             │
│   - bucket_id = chunk_index                             │
│   - 等价于今天的行为，零 regression                      │
└─────────────────────────────────────────────────────────┘
```

#### 模型路由

新增 `TaskType.STRUCTURE_PLANNING`，**不复用 EVALUATION**。

理由：EVALUATION 语义偏向"打分/判别"，未来可能被路由到 reward model 或纯分类器；而 section planning 是**结构化生成任务**，复用会埋下耦合风险。

短期路由策略：`STRUCTURE_PLANNING` → 与 EVALUATION 同 tier（fast/cheap），解耦后未来可独立调整。后续 [SOC-7](https://linear.app/socratiq-study/issue/SOC-7)（`tier: fast/smart` 接 ModelRouter）落地后，bucket pass 永远走 fast tier。

### 3.3 Prompt 草案

`backend/app/services/prompts/section_planning.md`

```
You group consecutive transcript chunks of a learning resource into
coherent "sections" — like chapters or topic shifts. Output the bucket
id each chunk belongs to.

INPUT FORMAT
Each chunk has:
  - idx: chunk index (0-based)
  - summary: a 1-2 sentence summary of the chunk's content
  - boundary_hint: 0.0–1.0, higher means stronger signal that a topic
    shift starts AT this chunk (use as a soft signal, not a hard rule)
  - size: ONE of the following, indicating chunk "weight":
      * duration_sec: chunk length in seconds (video/audio)
      * word_count: number of words (text-only resources)
    The field name tells you which unit applies to this batch.

RULES
1. Each bucket id is a non-negative integer.
2. Adjacent chunks under the same theme MUST share the same id.
3. A new theme MUST get id +1 (don't skip or reuse).
4. bucket_ids MUST be monotonically non-decreasing across chunks.
   When a topic briefly recurs (e.g. "concept → example → back to
   concept"), prefer keeping it in the SAME bucket as the original
   concept rather than opening a new one and returning. Linearity
   over precision.
5. TARGET: 4–12 buckets total.
   - If size unit is duration_sec: each bucket ≈ 5–15 minutes
     (sum of duration_sec across its chunks, i.e. 300–900 sec).
   - If size unit is word_count: each bucket ≈ 1500–4000 words
     (sum of word_count across its chunks).
   - For short resources (total duration < 480 sec OR total
     word_count < 2000), 1–3 buckets is fine.
   - For very long resources, up to 12 buckets — NOT proportional
     to length, coarser granularity is correct.
6. Bucket topic: a concise phrase, ≤8 words, in the chunk's predominant
   language. Should name the SPECIFIC subject, not generic labels like
   "introduction" or "discussion".

OUTPUT (strict JSON)
{
  "buckets": [
    {"id": 0, "topic": "Why we need binary search"},
    {"id": 1, "topic": "Python implementation"}
  ],
  "assignments": [
    {"chunk_index": 0, "bucket_id": 0},
    {"chunk_index": 1, "bucket_id": 0},
    {"chunk_index": 2, "bucket_id": 1}
  ]
}

CONSTRAINTS (validator will reject otherwise)
- assignments.length === input chunks.length, same order
- bucket_ids monotonically non-decreasing
- every bucket_id in assignments has a corresponding entry in buckets
- number of distinct buckets in [1, 12]
```

### 3.4 Embedding 边界信号预计算

在 SectionPlanner 入口处：

```python
async def plan(self, chunks, analyses, embeddings, title):
    # 1. 计算每个 chunk 与前一 chunk 的 embedding 余弦距离
    boundary_scores = self._compute_boundary_scores(embeddings)
    # 2. TextTiling 风格平滑（窗口=3）
    smoothed = self._smooth(boundary_scores, window=3)
    # 3. 归一化到 0..1
    normalized = self._normalize(smoothed)
    # 4. 喂给 LLM 作为 boundary_hint
    ...
```

由于 planner 在 `embed_and_store_chunks` **之后**运行（见 §3.5），embeddings 已在数据库中，复用零成本。

注意：boundary_hint 仅作为 LLM 的**软先验**出现在 prompt 输入中；v2 不提供"无 LLM 时用 boundary score 独立分桶"的兜底路径（移出范围，见 §7）。

### 3.5 Ingestion pipeline 接入点

`backend/app/worker/tasks/content_ingestion.py`：

**Planner 顺序：analyze → embed → plan → update metadata。**

```python
# 现有
analyzer = ContentAnalyzer(resources.model_router)
analysis = await analyzer.analyze(...)

# 现有：chunks 先入库 + 算 embedding
stored_chunks = await embed_and_store_chunks(raw_chunks, ...)

# 新增：planner 在 embedding 之后，从已入库的 chunk 读 embedding
planner = SectionPlanner(resources.model_router)
buckets = await planner.plan(
    chunks=raw_chunks,
    analyses=analysis.chunks,
    embeddings=[c.embedding for c in stored_chunks],
    title=source.title,
)

# 把 bucket 写回 chunk metadata（UPDATE 操作，非 INSERT）
await update_chunk_metadata(stored_chunks, buckets)
```

**关键点**：planner 输出是 metadata UPDATE 而非 INSERT。chunk 行本身已在 embed 阶段写入，bucket 信息后填进 JSONB 字段。失败时 chunk 已正确入库，metadata 缺失走 §3.6 的 per-chunk 兜底分支即可。

### 3.6 course_generator 改造

`backend/app/services/course_generator.py::_build_sections`

```python
if has_page_index:
    # 现有路径，不变
elif _has_section_buckets(all_chunks):    # 新分支
    bucket_groups: dict[tuple[UUID, int], list[ContentChunkModel]] = defaultdict(list)
    for chunk in all_chunks:
        bucket = (chunk.metadata_ or {}).get("section_bucket")
        if bucket is None:
            bucket = chunk.id           # 单 chunk 兜底
        bucket_groups[(chunk.source_id, bucket)].append(chunk)
    # 按 (source_id, min(chunk.created_at) within bucket) 排序，建 Section
    ...
else:
    # per_chunk_mode（现有路径，向后兼容）
```

LessonGenerator 那侧也从 `per_chunk_mode` 切到 `per_bucket_mode`：每个 bucket 的全部 chunks 文本合并喂给 `LessonGenerator.generate`，作为一节课文。

### 3.7 Metadata 持久化路径

- Ingestion 写入：`ContentChunk.metadata_["section_bucket"]` / `["section_bucket_topic"]`（已有 JSONB 字段，免迁移）
- course_generator 读取：`chunk.metadata_.get("section_bucket")`
- **版本标记**：`source.metadata_["section_planner_stats"]` 包含 `planner_version`（如 `"v1"`）。Planner prompt / 模型升级时递增。即便没有 admin UI，知道哪些资料是哪个版本切的，对回归排查有用。
- Regenerate：自动复用已有 bucket 标签（不重新分桶）
- Re-process（重跑 ingestion）：bucket 重新计算

## 4. 边界与失败处理

| 情况 | 行为 |
|---|---|
| 视频/音频：**总时长 < 8 分钟** | 跳过分桶，1 个 bucket |
| 文本：**总字数 < 2000 词** | 跳过分桶，1 个 bucket |
| LLM 返回桶数 = 1 | 接受（短主题资料合理），课程会只有 1 节 |
| LLM 返回桶数 > chunks 数 | clamp 到 chunks 数 |
| LLM 返回桶数 > 12 | 硬 clamp 到 12（合并最末尾的相邻桶） |
| `assignments` 非单调递增 | 视为失败 → Layer 3 |
| `assignments.length != chunks.length` | 视为失败 → Layer 3 |
| 任何 JSON 解析失败 | Layer 3 |
| Provider timeout | Layer 3 |
| LLM 路由整体不可用（含 EVALUATION/STRUCTURE_PLANNING tier） | Layer 3 per-chunk，导入不报错 |
| 旧资料 chunks 无 `section_bucket` | course_generator 走 per-chunk（向后兼容） |
| Embedding 读取失败 | boundary_hint 全部填 0，继续 Layer 1（不影响分桶能力） |

## 5. 验收用例

| 用例 | 期望 |
|---|---|
| 3Blue1Brown 19-min 神经网络视频（19 chunks） | 6–10 buckets，覆盖输入层 / 隐藏层 / 输出层 / 训练等主题 |
| Karpathy 2h GPT 视频（~120 chunks） | 10–12 buckets，按 attention / training / sampling 这种粗粒度切（**注意上限 12，不随长度线性增长**） |
| 30-page PDF | 走 page_index 路径，不受影响 |
| 5-min 短视频（4 chunks） | 触发时长短路，1 bucket |
| 8-min 中等视频（3 chunks，但每 chunk 长） | **不**触发短路（chunk 数无意义），正常分桶 |
| 长 Markdown 文章（无时间戳，6000 词，15 chunks） | 走 word_count 路径，3–5 buckets |
| 短 Markdown 文章（1500 词） | 触发字数短路，1 bucket |
| STRUCTURE_PLANNING 路由不可用 | Layer 3 per-chunk，导入不报错 |
| 主题回归型内容（"概念→例子→回到概念"） | 三段同 bucket（验证单调约束 + prompt 第 4 条生效） |

## 6. 监控

`source.metadata_.section_planner_stats`：

```json
{
  "tier_used": "skeleton" | "windowed" | "fallback",
  "planner_version": "v1",
  "bucket_count": 8,
  "avg_chunks_per_bucket": 2.4,
  "min_chunks_per_bucket": 1,
  "max_chunks_per_bucket": 5,
  "topic_uniqueness": 1.0,
  "planning_duration_ms": 1840,
  "llm_input_tokens": 4200,
  "llm_output_tokens": 180,
  "error": null
}
```

`topic_uniqueness` = unique(topics) / len(topics)。若 < 0.7 应告警 —— 说明 planner 给出大量重复名字，分桶失效。

`/sources` 详情弹窗 History 段展示这些数字（Phase 3）。

## 7. 范围外（后续 issue）

- **用 embedding 余弦做无 LLM 分桶**：当 STRUCTURE_PLANNING tier 持续失败时，用 chunk embeddings 余弦相似度 + TextTiling 风格平滑做无 LLM 分桶（v2 已用 boundary_hint 作为 LLM 软先验，但未提供独立兜底路径）
- **Layer 2 窗口缝合细节**：重叠 3 chunk + LLM 合并 pass（Phase 2 才会触发）
- **/import 配置面板**：让用户选 "自动分桶 / 强制 per-chunk / 自定义桶大小"
- **/generate Step 2 重新分桶按钮**：不重新 ingestion 的前提下重切 section
- **Admin 跳过 re-ingestion 的重新分桶按钮**：仅当 planner 升级频率高到 re-ingestion 成本难忍受时才考虑
- **Manual override**：在详情弹窗里允许把两个相邻 section 合并 / 一个 section 切两半
- **A/B 框架**：同一资料并行跑 Layer 1 和 embedding-only 兜底，对比用户最终采用率

## 8. 落地节奏

1. **Phase 1**（本 PR）：Layer 1 skeleton + Layer 3 per-chunk fallback + boundary_hint 计算 + `TaskType.STRUCTURE_PLANNING` + 基础监控字段写入
2. **Phase 2**：Layer 2 windowed-skeleton（覆盖 8h+ 内容）+ 窗口缝合方案
3. **Phase 3**：`/sources` History UI 展示 planner stats
4. **Phase 4**：embedding-only 无 LLM 兜底 + 用户 manual override

---

## Changelog（v1 → v2）

**必改类**

1. **Skeleton 输入**：`first_200_chars` → `ContentAnalyzer.summary`（避免漏掉 chunk 后半段的主题切换）
2. **新增 `size` 字段（duration_sec 或 word_count 二选一）**：让 prompt 的"5–15 分钟 / 1500–4000 词"约束模型可计算，并覆盖无时间戳的文本资料
3. **短路阈值**：从 "chunks ≤ 3" 改为 "总时长 < 8 分钟 或 总字数 < 2000"（chunk 数无意义）
4. **Topic 长度约束**：5–15 字符 → ≤8 words（修复原稿与示例自相矛盾）

**建议改类**

5. **新增 `TaskType.STRUCTURE_PLANNING`**：不复用 EVALUATION，避免语义耦合
6. **新增 embedding `boundary_hint`**：作为 LLM 的软先验，让 LLM 工作从"凭空切" → "审核命名"
7. **Planner 移到 `embed_and_store_chunks` 之后**：boundary_hint 复用已入库 embedding，零额外调用成本；planner 输出改为 metadata UPDATE
8. **Prompt 第 4 条**：明示"宁可合并不要回归"，保留单调约束但解释原因
9. **桶数上限硬性 clamp 到 12**：避免长视频被切成 20+ 碎片
10. **监控新增**：`avg_chunks_per_bucket`、`topic_uniqueness`、`planner_version`、token 计数

**范围调整**

11. **Layer 2 窗口缝合细节降级为 Phase 2 TODO**：短 topic 短语的 embedding 相似度噪声大（"图像识别" vs "图片分类" ≈ 0.6），v1 不实现细节
12. **不引入 pure-embedding fallback layer**：原评审版的"Layer 3 = 无 LLM 兜底"砍掉，回到三层（skeleton / windowed / per-chunk）。LLM 全失败时直接 per-chunk，等价现状零回归
13. **Admin "重新分桶"按钮移到范围外**：重跑 ingestion 已能解决同样的问题；但 `planner_version` 字段保留在监控里
