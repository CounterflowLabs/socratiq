# Lesson Input Budget — Token-Aware, Provider-Aware Bucket Sizing

**Status**: 草案 v1 · 待评审
**作者**: catundercar
**日期**: 2026-05-16
**关联 issue**: 待开
**关联文档**: [section-planning.md](./section-planning.md)

---

## 1. 背景与现状

### 1.1 已发现的 bug

`SectionPlanner` 决定每个 section 的字幕量,`LessonGenerator` 把这些字幕喂给 LLM 生成 block 课时。两者中间有一道**静默截断**:

```python
# backend/app/services/lesson_generator.py:48
subtitles=subtitles[:8000],   # 字符数硬切,无 logging
```

三个 tier 的实际数据量 vs. 8000 字符上限:

| 路径 | 中文典型 | 英文典型 | 8000 字符意味着 |
|---|---|---|---|
| Layer 3 embedding-only | ~2750 字 | ~14000-16500 字符 | 英文丢 ~50% |
| Layer 1/2 LLM 自决 + `_MAX_BUCKETS=12` 全局封顶 | 因主题而异 | 长视频每 bucket 可能 >8000 字符 | 不可预测 |
| 短路径 `_SHORT_CIRCUIT_WORD_COUNT=2000` | 不触发 | ~11000 字符 | 短英文素材也被切 |

截断完全静默——logger 不警告、stats 不上报、persisted lesson 上无标记。

### 1.2 业内做法

LangChain / LlamaIndex / LiteLLM / 大多数 production-grade RAG 系统:

- 用 tiktoken 算 token,不用字符
- 维护一份 `model → context_window` 表(LiteLLM 的 `model_prices_and_context_window.json` 是事实标准)
- 单次 LLM 输入用 `min(provider_context - overhead, sweet_spot_cap)`,sweet spot 通常 8k-16k token(基于 Liu et al. 2023 "Lost in the Middle":长 context 中段 attention 显著 degrade,即使有 200k 也不应填满)

socratiq 已经声明"多 LLM Provider 支持"为核心特性,但当前 8000 字符的硬切既不 token-aware 也不 provider-aware,与项目定位不匹配。

## 2. 目标 / 非目标

### 目标

- **消除静默数据丢失**:任何输入截断必须 log + stats 上报
- **生产者保证契约**:`SectionPlanner` 输出的 bucket 不再出现 `LessonGenerator` 消化不了的尺寸
- **Provider-aware**:大 context provider(Claude 200k)用更大输入预算;小 context provider(Llama-7B 4k)自动收紧
- **Token-based**:消除 char-vs-token 在中英文场景下的不一致
- **保持简单**:不引入完整的 provider 适配 tokenizer 体系,通用近似器(tiktoken cl100k_base)即可

### 非目标

- 不重写 SectionPlanner 的 4 层 tier 路由架构
- 不让 `LessonGenerator` 在输入过大时自动多次 LLM 调用拼接(会破坏"1 bucket = 1 lesson"的清晰心智模型,且成本 ×N)
- 不引入 provider 专属 tokenizer(transformers/Qwen tokenizer 会引入 100MB 包,得不偿失)
- 不动 short-circuit thresholds(短路径产出的单一 bucket 会自动过 split pass,无需单独处理)
- 不做 provider 切换时的 re-plan(已生成 course 的 bucket 维持不变)

## 3. 设计

### 3.1 架构概览

```
┌────────────────────────────────────────────────────────────────────┐
│  app/services/llm/token_budget.py                  [NEW]           │
│                                                                    │
│  ┌──────────────────┐  ┌────────────────────┐                      │
│  │ _MODEL_CONTEXT_  │  │ count_tokens()     │                      │
│  │ TOKENS dict      │  │ truncate_to_tokens │                      │
│  └────────┬─────────┘  └────────┬───────────┘                      │
│           │                     │                                  │
│           └──────┬──────────────┘                                  │
│                  ▼                                                 │
│         ┌─────────────────────────────────────┐                    │
│         │ lesson_input_token_budget(provider) │                    │
│         └────────────┬────────────────────────┘                    │
└──────────────────────┼─────────────────────────────────────────────┘
                       │
        ┌──────────────┴──────────────────────┐
        │                                     │
        ▼                                     ▼
┌──────────────────┐                 ┌──────────────────────┐
│ LessonGenerator  │  ← runtime      │ content_ingestion    │
│ __init__:        │  safety net     │ pre-plan:            │
│  budget = ...    │                 │  cap = ...           │
│ generate:        │                 │  planner.plan(       │
│  warn+truncate   │                 │    ..., cap=cap)     │
│  if over budget  │                 └──────────┬───────────┘
└──────────────────┘                            │
                                                ▼
                                     ┌──────────────────────────┐
                                     │ SectionPlanner.plan      │
                                     │   ↓ all 4 tiers          │
                                     │   ↓ _finalize()          │
                                     │     ├─ split_oversized() │
                                     │     └─ build_stats()     │
                                     └──────────────────────────┘
```

### 3.2 核心模块: `app/services/llm/token_budget.py`

```python
"""Token budget计算 — context-window-aware, tokenizer-approximated.

Strategy:
  - tiktoken cl100k_base as universal approximator (errors <15% even for
    Chinese/non-OpenAI tokenizers, well within our safety margin).
  - Each model's context window comes from a maintained table (mirrors
    LiteLLM's model_prices_and_context_window.json layout). Unknown
    models fall back to a conservative 8k window.
  - Sweet-spot cap (12k input tokens) regardless of how big the context
    is — long-context attention degrades past that range.
  - Subtract reserved overhead for prompt template + max_output_tokens.
"""

# Default max_output for unknown models. Per-model overrides live in
# _MODEL_OUTPUT_TOKENS — frontier models (Sonnet/GPT-4o) get 8k, mid-tier
# (Haiku/4o-mini/DeepSeek) get 6k, small/local stay at 4k.
DEFAULT_LESSON_MAX_OUTPUT_TOKENS = 4000
DEFAULT_PROMPT_OVERHEAD_TOKENS = 1500

# Provider-aware lookup. Bigger models can sustain longer coherent JSON
# output without drift; small models drift past 4k. Unknown → 4k fallback.
_MODEL_OUTPUT_TOKENS: dict[str, int] = {
    "claude-3-5-sonnet-*":  8_000,
    "claude-3-opus-*":      8_000,
    "gpt-4o":               8_000,
    "claude-3-5-haiku-*":   6_000,
    "gpt-4o-mini":          6_000,
    "deepseek-*":           6_000,
    "qwen-max":             6_000,
    "llama3.1:70b":         6_000,
    "llama3.1:8b":          4_000,
    "qwen2.5:7b":           4_000,
    # ... see token_budget.py for full table
}

# Long-context attention degrades past ~12k tokens for most models.
_INPUT_SWEET_SPOT_TOKENS = 12_000

_FALLBACK_CONTEXT = 8_192

_MODEL_CONTEXT_TOKENS: dict[str, int] = {
    # Anthropic (200k context)
    "claude-3-5-sonnet-20241022":  200_000,
    "claude-3-5-haiku-20241022":   200_000,
    "claude-3-opus-20240229":      200_000,
    "claude-sonnet-4-20250514":    200_000,
    # OpenAI
    "gpt-4o":                      128_000,
    "gpt-4o-mini":                 128_000,
    "gpt-4-turbo":                 128_000,
    "gpt-4":                        32_768,
    # DeepSeek
    "deepseek-chat":                64_000,
    "deepseek-reasoner":            64_000,
    # Qwen
    "qwen-max":                     32_000,
    "qwen-plus":                   131_000,
    "qwen2.5:7b":                   32_000,
    # Local / Llama
    "llama3.1:8b":                 128_000,
    "llama3.1:70b":                128_000,
}

def lesson_max_output_tokens(provider: LLMProvider) -> int:
    """Per-call max_tokens for lesson generation against `provider`."""
    return _MODEL_OUTPUT_TOKENS.get(
        provider.model_id(), DEFAULT_LESSON_MAX_OUTPUT_TOKENS,
    )

def lesson_input_token_budget(
    provider: LLMProvider,
    *,
    max_output_tokens: int | None = None,  # None → auto from provider
    prompt_overhead_tokens: int = DEFAULT_PROMPT_OVERHEAD_TOKENS,
) -> int:
    """Maximum input tokens for one lesson_generator call against `provider`.

    budget = min(
        context_window(provider) - max_output_tokens - prompt_overhead,
        SWEET_SPOT_CAP,
    )

    `max_output_tokens=None` auto-derives from `lesson_max_output_tokens(provider)`
    so input + output budgets always come from the same source.
    """
    if max_output_tokens is None:
        max_output_tokens = lesson_max_output_tokens(provider)
    ctx = _MODEL_CONTEXT_TOKENS.get(provider.model_id(), _FALLBACK_CONTEXT)
    raw = ctx - max_output_tokens - prompt_overhead_tokens
    return max(512, min(raw, _INPUT_SWEET_SPOT_TOKENS))

def count_tokens(text: str) -> int:
    """tiktoken cl100k_base approximation. <15% error vs native tokenizers."""

def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Cut text to at most `max_tokens` tokens (decoded back to a string)."""
```

**为什么 tiktoken cl100k_base 而不是 provider 专属 tokenizer**:
- 误差 < 10% 对 OpenAI 系/Anthropic、< 15% 对中文场景的 Qwen/DeepSeek
- 已经在 budget 计算里加了 `_INPUT_SWEET_SPOT_TOKENS=12000` 这个 hard cap,远低于任何 provider context window;少算 15% 也不会爆 context
- 引入 provider 专属 tokenizer 要么走 `transformers + 模型权重 vocab`(~100MB+)要么调 provider 的 count_tokens API(每次摄入打多次 API call)。Trade-off 不值

**为什么 sweet spot cap 12k**:
- "Lost in the Middle"(Liu et al. 2023)证明长 context 中段 attention 显著 degrade
- 12k 是业内 RAG 场景的事实甜点区
- 即使 Claude 3.5 Sonnet 有 200k context,塞满后单次 lesson 质量也会下降
- 如果将来发现某 provider 在 16k 表现仍稳定,改这个常量即可

**为什么 fallback 8k**:
- 对未知 model 保守估计,确保不会爆 context
- 应用 prompt overhead + max output 后,实际 input 预算 ~2.5k token,够生成一个简单 section

### 3.3 `LessonGenerator` 改造(消费者侧 safety net)

```python
class LessonGenerator:
    def __init__(self, provider: LLMProvider):
        self._provider = provider
        # Both budgets resolved once per instance, both provider-aware.
        # Capable models get larger max_output so dense source isn't capped;
        # small models stay at 4k. Input budget auto-aligns via the same
        # provider so the two never diverge.
        self._max_output_tokens = lesson_max_output_tokens(provider)
        self._input_token_budget = lesson_input_token_budget(provider)

    async def generate(self, subtitle_chunks, ...):
        combined = "\n\n".join(subtitle_chunks)
        n_tokens = count_tokens(combined)
        if n_tokens > self._input_token_budget:
            logger.warning(
                "Lesson input %d tokens exceeds budget %d for model=%s; "
                "truncating tail. Upstream planner emitted oversized bucket.",
                n_tokens, self._input_token_budget, self._provider.model_id(),
            )
            combined = truncate_to_tokens(combined, self._input_token_budget)

        prompt_text = _PROMPT.render(..., subtitles=combined, ...)
        ...
        response = await self._provider.chat(..., max_tokens=self._max_output, ...)
```

**注意**:
- 这里截断仍然存在,但作为 safety net。正常路径不应触发——触发即说明上游 `SectionPlanner` 违约
- 截断必有 logger.warning,带 model_id + 实际 token 数 + 预算,便于排查
- API 不破坏:`__init__(provider)` 签名不变,所有 caller(course_generator.py:120, lesson_regeneration.py:93)零改动

### 3.4 `SectionPlanner` 改造(生产者侧契约)

#### 3.4.1 `plan()` 接受可选 cap 参数

```python
async def plan(
    self,
    *,
    chunks: list[RawContentChunk],
    analyses: list[AnalyzedChunk],
    embeddings: list[list[float]] | None,
    title: str,
    lesson_input_token_cap: int | None = None,   # NEW
) -> PlanResult:
    """...

    lesson_input_token_cap: when provided, no bucket will exceed this many
    tokens (chunk-boundary greedy split otherwise). Defaults to a
    conservative 8k tokens to keep planner usable from tests/scripts that
    don't compute a real budget.
    """
    cap = lesson_input_token_cap or _CONSERVATIVE_BUCKET_TOKEN_CAP
    ...
```

**为什么传 cap 而不是传 provider**:
- Planner 不需要知道哪个 TaskType 驱动 lesson 生成
- Caller(content_ingestion / lesson_regeneration)负责: provider → cap → planner
- 单元测试只需传一个 int,不需要 mock provider

#### 3.4.2 统一收口: `_finalize_assignments`

提取一个 helper,把"split pass + build stats + return PlanResult"合并:

```python
def _finalize_assignments(
    *,
    raw_assignments: list[BucketAssignment],
    chunks: list[RawContentChunk],
    cap_tokens: int,
    tier: str,
    started: float,
    error: str | None = None,
    short_circuit: bool = False,
    llm_input_tokens: int = 0,
    llm_output_tokens: int = 0,
) -> PlanResult:
    final, split_count = _split_oversized_buckets(raw_assignments, chunks, cap_tokens)
    bucket_token_sizes = _bucket_token_sizes(final, chunks)
    return PlanResult(
        assignments=final,
        stats=_build_stats(
            tier=tier,
            assignments=final,
            elapsed_ms=_elapsed_ms(started),
            error=error,
            short_circuit=short_circuit,
            llm_input_tokens=llm_input_tokens,
            llm_output_tokens=llm_output_tokens,
            bucket_token_sizes=bucket_token_sizes,
            buckets_split_for_size=split_count,
            lesson_input_token_cap=cap_tokens,
        ),
    )
```

`plan()` 的 4 个 return 点(short-circuit / Layer 1-2 success / Layer 3 success / Layer 4 fallback)统一改走 `_finalize_assignments`,避免任何路径绕过 split pass。

#### 3.4.3 `_split_oversized_buckets`

```python
def _split_oversized_buckets(
    assignments: list[BucketAssignment],
    chunks: list[RawContentChunk],
    cap_tokens: int,
) -> tuple[list[BucketAssignment], int]:
    """Re-split any bucket whose joined text exceeds `cap_tokens`.

    Splits along chunk boundaries (never inside a chunk). Topics are
    preserved with a "(Part i/N)" suffix. Returns the new assignments
    and the count of extra buckets created.
    """
    by_bucket = group_chunks_by_bucket(assignments)
    new_assignments = list(assignments)
    next_bid = max((a.bucket_id for a in assignments), default=-1) + 1
    extra = 0

    for bid, chunk_indices in sorted(by_bucket.items()):
        token_sizes = [count_tokens(chunks[i].raw_text or "") for i in chunk_indices]
        join_overhead = 1  # tiktoken treats "\n\n" as ~1 token
        total = sum(token_sizes) + join_overhead * max(0, len(token_sizes) - 1)
        if total <= cap_tokens:
            continue

        # Greedy chunk-boundary packing into sub-buckets <= cap each.
        sub_buckets: list[list[int]] = [[]]
        running = 0
        for idx, sz in zip(chunk_indices, token_sizes):
            if sub_buckets[-1] and running + join_overhead + sz > cap_tokens:
                sub_buckets.append([])
                running = 0
            if sub_buckets[-1]:
                running += join_overhead
            sub_buckets[-1].append(idx)
            running += sz

        n_parts = len(sub_buckets)
        original_topic = next(
            (a.bucket_topic for a in assignments if a.bucket_id == bid), None,
        )
        for part_i, sub in enumerate(sub_buckets):
            new_bid = bid if part_i == 0 else next_bid
            if part_i > 0:
                next_bid += 1
                extra += 1
            new_topic = (
                f"{original_topic} (Part {part_i + 1}/{n_parts})"
                if original_topic and n_parts > 1 else original_topic
            )
            for idx in sub:
                new_assignments[idx] = BucketAssignment(
                    bucket_id=new_bid, bucket_topic=new_topic,
                )

    return new_assignments, extra
```

**为什么按 chunk 边界切**:chunk 是 extractor 的最小语义单位(YouTube 字幕的一行、PDF 的一段),从中间切会破坏字幕完整性,影响 lesson 的上下文连贯性。

**为什么不重新跑 LLM 决定切点**:oversized bucket 是 fallback 路径,再多一次 LLM 调用既慢又脆弱;greedy chunk packing 是确定性、可测试的。

**为什么 `(Part i/N)` 标在 topic 里而非新增字段**:零 schema 改动,UI 自动渲染,deep link 不破。

**为什么不在乎 `_MAX_BUCKETS=12` 被 split 突破**:`_MAX_BUCKETS` 原本约束的是 LLM 自决的合理性(防止 LLM 过度切分),不是物理硬约束。如果一个 12-bucket 的 plan 里有个 bucket 太大被拆成 3 个,合计 14 个 bucket 是更正确的选择,优于丢一半数据。

#### 3.4.4 stats 增强

`_build_stats` 新增 4 个字段:

```python
{
    # ... 现有字段不变 ...
    "bucket_size_tokens_p50": ...,        # 中位 bucket 大小(tokens)
    "bucket_size_tokens_max": ...,        # 最大 bucket 大小(tokens)
    "buckets_split_for_size": split_count, # 因超 cap 被切出的额外 bucket 数
    "lesson_input_token_cap": cap_tokens, # 这次 plan 用的 cap,便于追溯
}
```

### 3.5 调用点改造

#### `worker/tasks/content_ingestion.py`(主路径)

```python
from app.services.llm import TaskType
from app.services.llm.token_budget import lesson_input_token_budget

# 新增:为 SectionPlanner 计算 cap
lesson_provider = await resources.model_router.get_provider(TaskType.CONTENT_ANALYSIS)
lesson_input_cap = lesson_input_token_budget(lesson_provider)

section_planner = SectionPlanner(resources.model_router)
plan_result = await section_planner.plan(
    chunks=result.chunks,
    analyses=analysis.chunks,
    embeddings=chunk_embeddings,
    title=source.title or "Untitled",
    lesson_input_token_cap=lesson_input_cap,   # NEW
)
```

#### `worker/tasks/lesson_regeneration.py`

零改动——它直接调 `LessonGenerator.generate()`,新的 budget 检查在 `__init__` 内完成。

#### `services/course_generator.py`

零改动——它消费 plan 输出的 bucket,bucket 已经在 plan 阶段被 split,直接消费。

## 4. 可观测性

| 信号 | 触发条件 | 谁能看到 |
|---|---|---|
| `logger.warning("Lesson input N tokens exceeds budget M ...")` | LessonGenerator runtime 截断 | 日志/Sentry |
| `stats["buckets_split_for_size"] > 0` | Planner split pass 切出额外 bucket | source.metadata.section_planner_stats |
| `stats["bucket_size_tokens_max"]` | 任何 plan | source.metadata.section_planner_stats |
| `stats["lesson_input_token_cap"]` | 任何 plan | source.metadata.section_planner_stats |

LessonGenerator runtime 截断**不应该发生**(说明上游违约)。如果发生,logger.warning + Sentry capture 让运维立刻发现。

## 5. 测试策略

### 5.1 token_budget 单元测试

- `count_tokens` 对已知字符串返回稳定值
- `lesson_input_token_budget` 对各种 provider mock(含 unknown model)返回正确 budget
- `truncate_to_tokens` 截断结果 token 数 ≤ cap
- 边界:cap=0 / 空字符串 / 超长字符串

### 5.2 section_planner split pass 单元测试

- 单 bucket 100k tokens → 切成 N 个 sub-bucket,每个 ≤ cap
- 多 bucket,只有 1 个超 cap → 只切那一个,其他保持
- 超 cap bucket 有 topic → sub-bucket topic 加 `(Part i/N)`
- 超 cap bucket 无 topic → sub-bucket topic 保持 None
- 边界:cap 极小(单个 chunk 就超) → 每 chunk 1 个 sub-bucket
- 边界:bucket 刚好等于 cap → 不切

### 5.3 lesson_generator runtime 截断测试

- 输入 token 数 < budget → 不警告,不截断
- 输入 token 数 > budget → logger.warning 触发,截断到 budget
- 截断后的内容仍能正常调 LLM(用 mock)

### 5.4 集成回归

跑 `pytest tests/test_section_planner.py tests/test_lesson_generator.py tests/test_content_ingestion.py` 全套。

## 6. Trade-offs 与已知限制

### 6.1 接受的不精确

- tiktoken cl100k_base 对非 OpenAI tokenizer 误差 ~15%(主要中文场景)。被 sweet spot cap (12k) 与 90% margin (split pass cap) 双重吸收。
- Provider context window 表手维护,新加 provider 要更新。可接受——provider 列表变化频率低。

### 6.2 设计上的妥协

- **provider 切换后已生成 plan 不会重计算**:已 ingest 的 source 的 bucket 大小是按摄入时的 provider 算的。如果用户从 Claude 200k 切到 Llama 4k,旧 source 的 bucket 可能爆 budget——此时 LessonGenerator runtime 截断 + warning 兜底。
- **不做单 chunk 内部切分**:如果某单一 chunk 本身就超 cap(比如一个 50k token 的超长 chunk),split pass 会让那个 chunk 单独成 bucket,但其内容仍超 budget,触发 LessonGenerator 截断。这是 extractor 层应该解决的问题(chunk 切得过大),不在 planner 修复范围。

### 6.3 显式不做

- **provider 自适应 tokenizer**:transformers 包重 + 测试矩阵爆炸,不值
- **`LessonGenerator` 自动多次 LLM 调用拼接超长输入**:破坏"1 bucket = 1 lesson"心智模型,成本 ×N
- **从 LiteLLM 包拉 context window 表**:增加依赖,手维护已经够用
- **Anthropic 原生 count_tokens API**:每次摄入打多次 API call,成本 + 延迟不划算

## 7. 兼容性

| 维度 | 影响 |
|---|---|
| 已存在 source 的 `section_bucket` 元数据 | 零影响——已持久化,不会重算 |
| 已存在 course | 零影响 |
| 老 source 触发 course_regeneration | 走新 plan 规则,bucket 数只增不减;UI 自然多出几个 section;part-1 保留原 bucket_id,deep link 不挂 |
| 新摄入 source | 直接走新规则 |
| DB schema | 无需迁移 |
| LessonGenerator API | `__init__(provider)` 签名不变 |
| SectionPlanner API | `plan()` 新增可选参数,调用方不传时 fallback 到保守默认,向后兼容 |

## 8. 改动清单

| # | 文件 | 改动类型 | 内容 |
|---|---|---|---|
| 1 | `backend/pyproject.toml` | 修改 | 添加 `tiktoken>=0.7` 依赖 |
| 2 | `backend/app/services/llm/token_budget.py` | 新建 | `_MODEL_CONTEXT_TOKENS`、`lesson_input_token_budget`、`count_tokens`、`truncate_to_tokens` |
| 3 | `backend/app/services/llm/__init__.py` | 修改 | 导出 `lesson_input_token_budget` 等 |
| 4 | `backend/app/services/lesson_generator.py` | 修改 | 删除 `[:8000]`;`__init__` 计算 budget;`generate()` 添加 token 检查 + warning + truncate |
| 5 | `backend/app/services/section_planner.py` | 修改 | 新增 `_split_oversized_buckets`、`_bucket_token_sizes`、`_finalize_assignments`;`plan()` 接受 `lesson_input_token_cap` 参数;4 个 return 点统一走 `_finalize_assignments`;stats 增 4 字段 |
| 6 | `backend/app/worker/tasks/content_ingestion.py` | 修改 | 调 `lesson_input_token_budget` 算 cap,传给 `plan()` |
| 7 | `backend/tests/test_token_budget.py` | 新建 | budget/count/truncate 单元测试 |
| 8 | `backend/tests/test_section_planner.py` | 修改 | 新增 split pass 测试 + 现有测试如有 break 修复 |
| 9 | `backend/tests/test_lesson_generator.py` | 修改 | 新增 truncate 警告测试 |
| 10 | `docs/design/lesson-input-budget.md` | 新建 | 本文档 |

执行顺序: 1 → 2 → 3 → 4 → 5 → 6 → 7-9 → 跑测试。

## 9. 风险

- **tiktoken 安装**: 纯 Rust 后端,~1MB 包,Python 3.12 支持良好。低风险。
- **stats 字段消费方**: 当前 `source.metadata.section_planner_stats` 只在前端展示,不被任何代码逻辑消费。新增字段无破坏。
- **Course regeneration 时 bucket 数变化**: 旧 source 重生成时可能产生比之前更多 section。记录在 release note,提示用户。

## 10. 后续工作(本次不做)

- 引入 `TaskType.LESSON_GENERATION` 路由,不再借用 `CONTENT_ANALYSIS` 的 provider
- Source-level "generation_warnings" 数组上浮 LessonGenerator 截断告警,在 source 详情页展示健康度
- Provider 切换时自动 re-plan 已有 source(可能影响课程内容,需 UI 确认流)
