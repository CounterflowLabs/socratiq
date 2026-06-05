# Visual Ingestion — Subtitle-Sparse-Triggered Keyframe Vision Pass

**Status**: 草案 v1 · 待评审
**作者**: catundercar
**日期**: 2026-05-16
**关联 issue**: 待开
**关联文档**:
- [lesson-input-budget.md](./lesson-input-budget.md)
- [competitive-analysis.md](./competitive-analysis.md)
- [llm-providers.md](../llm-providers.md)

---

## 1. 背景与现状

### 1.1 字幕单通道的硬伤

当前 Socratiq 的视频摄入完全依赖字幕:

```text
BilibiliExtractor / YouTubeExtractor
  └─ priority: CC subtitle → AI auto-subtitle → Whisper ASR fallback
       └─ RawContentChunk(raw_text=subtitle_text, metadata={start_time, end_time})
            └─ ContentAnalyzer → SectionPlanner → LessonGenerator
```

`backend/app/tools/extractors/bilibili.py:19-29` 注释里把"CC → AI → Whisper"列得很清楚,但隐含的前提是 **`raw_text` 一定能完整还原视频核心信息**。这个前提在以下场景失败:

| 场景 | 字幕状态 | 实际信息载体 | 当前管线表现 |
|---|---|---|---|
| 编程教学(全程屏幕共享 + 简短口播) | 字幕只覆盖口播 | 屏幕上的代码 / 终端输出 | 课时几乎全在解释"他说了什么",代码看不到 |
| 数学/科学讲解(白板/幻灯片) | 字幕只口播公式名 | 幻灯片的公式 / 推导步骤 | LLM 只能瞎猜公式 |
| 演示型视频(无旁白纯演示) | 整段字幕空 | 演示画面 | Whisper 也救不了 → 空 chunk |
| BGM 段 / 转场 / Demo | 字幕零散 | 视觉变化 | 摄入静默丢失这部分时间区间 |
| 静音视频 / Vlog | 字幕零散 | 画面叙事 | 同上 |

竞品 memories.ai 把 "watches like a human"(读屏幕文字、看画面、区分讲话人)放在 Bilibili Summarizer 落地页首屏作为核心卖点,在视频内容覆盖广度上对 Socratiq 形成不对称威胁——他们做学习层只需"在多模态底座上加一层",而我们做视觉底座要重写 extractor 管线。

### 1.2 不做"全程多模态"的理由

memories.ai 把多模态当卖点,但 Socratiq 的产品定位是"学习导师"而非"视频摘要器"。每秒抽帧的全程视觉处理会:

- 摄入成本 3-5x(vision LLM 单价远高于纯文本 LLM)
- 摄入延迟 2-4x(大量串行 vision call,即使并发也受 rate limit 约束)
- 大量低价值帧浪费 token(讲师特写 / 黑屏 / 转场 / 静态幻灯片重复出现)
- 与"学习"定位错配——我们不需要识别每一个画面元素

合理的策略是**按需视觉**:绝大多数视频字幕足够,只在字幕信息密度低的时间段触发视觉补足。

## 2. 目标 / 非目标

### 目标

- **闭合 extractor 的盲区**:字幕稀疏/空的时间段被视觉描述补齐,送入 SectionPlanner 时不再有"信息黑洞"
- **成本可控**:对已字幕完整的视频,视觉成本接近 0;对字幕空白率 50% 的视频,新增摄入成本控制在 1.5x 以内
- **符合 LLM 抽象层契约**:不引入新的 SDK 直调,vision 走 `LLMProvider` 抽象 + `TaskType.VISION_DESCRIPTION` 路由,与现有 `MENTOR_CHAT` / `CONTENT_ANALYSIS` 同构
- **不破坏 chunk 语义**:vision 产出的描述与字幕在 chunk 层融合,SectionPlanner / ContentAnalyzer 无需感知"这是视觉文本还是口播文本"
- **可降级**:vision provider 不可用 / 抽帧失败 / 视频文件不可获取 → 跌回字幕单通道,摄入不报错
- **可观测**:摄入完成后能看到"vision_chunk_count、vision_token_cost、vision_skipped_reason",而不是黑盒

### 非目标

- **不做全程多模态视觉**(参见 §1.2)。如果将来某些素材类型确实需要(纯演示视频),走素材级别的开关而非全局
- **不做讲话人 diarization**。Bilibili 单讲师为主,投入产出比低
- **不做画面 OCR 单独通道**。OCR 当作 vision 的子任务由 vision LLM 一次完成,不引入 PaddleOCR/Tesseract 等额外依赖
- **不在 PDF extractor 加视觉**。PDF 已有页级文本 + 标题结构,视觉收益有限,后续工作再议
- **不动 SectionPlanner 的 tier 路由架构**。视觉描述作为新的 chunk 类型注入,planner 无感
- **不重训练任何模型**。完全走外部 vision LLM(Anthropic / OpenAI / Qwen-VL)

## 3. 设计

### 3.1 架构概览

```text
┌────────────────────────────────────────────────────────────────────┐
│ BilibiliExtractor / YouTubeExtractor (existing)                    │
│  └─ subtitle chunks: RawContentChunk(source_type="bilibili", ...)  │
│       metadata={"start_time": .., "end_time": ..}                  │
│       raw_text = subtitle text (may be empty)                      │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ SubtitleDensityAnalyzer            [NEW]                           │
│  → identify sparse time windows                                    │
│     (raw_text字符密度低于阈值 OR 字幕空段持续 > N 秒)              │
│  → emit list[SparseWindow]                                         │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ sparse windows
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ FrameSampler                       [NEW]                           │
│  → for each window:                                                │
│     • download stream (cache to MinIO; reuse if exists)            │
│     • ffmpeg-based keyframe extraction                             │
│     • dedup by perceptual hash (drop near-identical frames)        │
│  → emit list[KeyFrame] with timestamp + image bytes                │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ keyframes
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ VisionDescriber                    [NEW]                           │
│  → for each keyframe (or batch of N frames per call):              │
│     provider = router.get_provider(TaskType.VISION_DESCRIPTION)    │
│     resp = await provider.describe_image(image_bytes, prompt=...)  │
│  → emit RawContentChunk(source_type="bilibili_visual", ...)        │
│     raw_text = vision LLM description                              │
│     metadata = {start_time, end_time, vision_source: "keyframe"}   │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ visual chunks
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ ChunkMerger                        [NEW]                           │
│  → time-sort: interleave subtitle + visual chunks                  │
│  → guarantee chunk ordering monotonic in start_time                │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ merged chunks
                               ▼
        existing ContentAnalyzer → SectionPlanner → LessonGenerator
```

整个视觉通路只在 extractor 阶段之后、ContentAnalyzer 之前插入。下游所有模块零改动。

### 3.2 触发策略:`SubtitleDensityAnalyzer`

#### 3.2.1 何为"稀疏"

把视频时间轴切成 30 秒窗口(可配置),对每个窗口计算:

```python
char_density = total_subtitle_chars / window_seconds
```

| 状态 | 判定 |
|---|---|
| 致密 | `char_density >= DENSE_THRESHOLD` (中文默认 6 / 英文默认 12) |
| 稀疏 | `char_density < SPARSE_THRESHOLD` (中文默认 2 / 英文默认 4) 或字幕完全空段 ≥ `MIN_EMPTY_GAP_SECONDS`(默认 8s) |
| 中等 | 介于两者之间,不触发视觉 |

阈值是字符密度而非 token 密度——稀疏判断走 char 即可,不引入 tokenizer。中英文阈值差异是因为中文每秒口播字数显著低于英文(2-3x)。

#### 3.2.2 合并相邻稀疏窗口

相邻稀疏窗口合并成一个 `SparseWindow(start, end)`,避免对短间隔反复抽帧。合并规则:

- 两个稀疏窗口间隔 < `MERGE_GAP_SECONDS`(默认 15s) → 合并
- 单个 `SparseWindow` 长度 > `MAX_WINDOW_SECONDS`(默认 180s) → 拆成多段,避免一段视觉描述长度失控

#### 3.2.3 早退路径

```python
if total_sparse_seconds / total_duration < ENABLE_VISION_RATIO:  # 默认 0.1
    return []  # 字幕已经够好,完全跳过视觉
```

10% 是经验值——稀疏比例低于这个,视觉补足的边际收益不抵触发成本。

### 3.3 抽帧:`FrameSampler`

#### 3.3.1 流来源

视频文件本身,Socratiq 当前 extractor 只下载字幕。`FrameSampler` 新增视频流下载能力:

- **Bilibili**: `bilibili_api.video.Video.get_download_url()` 取最低可用分辨率(360p 足够 OCR),`yt-dlp` fallback
- **YouTube**: `yt-dlp` 走 `worstvideo[ext=mp4]` 格式 selector
- **PDF**: N/A(本设计不覆盖)

视频文件用 MinIO 作 cache(key = source_id),避免一次摄入失败重试要重新下载几百 MB。

#### 3.3.2 抽帧方式

```python
# ffmpeg -ss <start> -to <end> -i <video> -vf "select='eq(pict_type,I)'" frames/%d.jpg
keyframes = ffmpeg_extract_iframes(video_path, window.start, window.end)
```

只抽 I-frame(关键帧),原因:

- I-frame 通常对应场景切换 / 内容变化,信息密度高
- 数量自然控制(720p 30fps 视频 30s 窗口大约 5-15 个 I-frame)
- ffmpeg 原生支持,无需额外感知场景切换库

如果某个窗口的 I-frame 仍超过 `MAX_FRAMES_PER_WINDOW`(默认 8),用均匀降采样保留 8 帧。

#### 3.3.3 感知哈希去重

讲师全程一张幻灯片不动 → I-frame 也可能近似重复。用 `imagehash.phash` 去重:

```python
hashes = [phash(f) for f in frames]
deduped = []
for f, h in zip(frames, hashes):
    if all(hamming(h, h2) >= PHASH_THRESHOLD for h2 in [x.hash for x in deduped]):
        deduped.append(KeyFrame(image=f, hash=h, timestamp=...))
```

`PHASH_THRESHOLD = 8`(64-bit hash 上经验值)——汉明距离低于 8 视为重复。

### 3.4 描述:`VisionDescriber`

#### 3.4.1 LLM 抽象层扩展

CLAUDE.md 明令"Agent 层和业务层不直接调用 Provider SDK",vision 也必须走抽象层。在 `app/services/llm/base.py` 给 `LLMProvider` 加可选方法:

```python
class LLMProvider(ABC):
    # ... 现有方法不变 ...

    async def describe_image(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,                  # "image/jpeg" | "image/png"
        prompt: str,
        max_tokens: int = 800,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Describe an image.

        Default raises NotImplementedError. Providers that support vision
        override this. Returned LLMResponse uses the same shape as chat()
        so downstream code can treat description text uniformly.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support vision"
        )

    def supports_vision(self) -> bool:
        """Whether describe_image() is implemented."""
        return False
```

支持的 provider:

| Provider | 实现路径 | 备注 |
|---|---|---|
| `AnthropicProvider` | Messages API 已支持 `image` content block | 复用现有 `_anthropic_client`,在 `describe_image` 中构造 `image_url` + `text` 双 content block |
| `OpenAICompatProvider` | `chat.completions` 支持 `image_url` content type | OpenAI 系/Qwen-VL/DeepSeek-VL/Llava via Ollama 全部走这条 |
| `CodexProvider` | 不实现 | Codex 不支持 vision,`supports_vision()` 返回 False |

`describe_image` 而非"复用 chat + image content block"的原因:

- 视觉调用语义清晰(单图 → 单描述),不需要多轮 messages 抽象
- 不同 provider 对 image content block 的封装差异显著(Anthropic 用 `source.type=base64`、OpenAI 用 `image_url`、Qwen 用 `image` 字段),用 `describe_image` 在 provider 内部各自封装,调用方零分支
- batch 多图调用走另一个方法 `describe_images(image_bytes_list, prompt)`,实现里走 provider 的 multi-image 能力或退化为并发单图

#### 3.4.2 新增 `TaskType.VISION_DESCRIPTION`

```python
# app/services/llm/router.py
class TaskType(str, Enum):
    MENTOR_CHAT = "mentor_chat"
    CONTENT_ANALYSIS = "content_analysis"
    EVALUATION = "evaluation"
    STRUCTURE_PLANNING = "structure_planning"
    VISION_DESCRIPTION = "vision_description"   # NEW
    EMBEDDING = "embedding"
```

`ModelConfigManager` 需要在 `provider_capability` 表(或类似配置)校验:配给 `VISION_DESCRIPTION` 的 model 必须 `supports_vision=True`,否则在路由阶段抛 `LLMError`,与现有 EMBEDDING 路由的 model_type 校验对称。

#### 3.4.3 prompt 模板

新增 `backend/app/services/prompts/vision_describe.md`:

```text
你正在为一段在线学习视频补足画面描述,字幕本身在这段时间内空缺或稀疏。
请从下面这张关键帧中提取**对学习者有价值**的内容,严格遵守:

1. 屏幕上可见的文字、代码、公式、UI、图表 — 完整转录
2. 当前画面上正在发生的核心动作或讲解 — 一句话总结
3. 不要描述讲师外观 / 背景装饰 / 与教学无关的细节

输出格式:
[T={timestamp}s] {one-line gist}
{multi-line transcript of on-screen content, blank if none}

绝不输出任何与画面无关的推测。如果画面完全没有可读教学信息(纯过渡 / BGM),输出单行 "(transitional)"。
```

模板里的 `(transitional)` 让下游可识别"这帧没价值,可以丢"。

#### 3.4.4 并发与速率控制

- 每个 source 内部:keyframe 描述用 `asyncio.gather` 并发,但受 `VISION_MAX_CONCURRENCY`(默认 4)信号量约束
- 跨 source:走 Celery worker 自身的并发模型,不额外限流
- provider 侧 rate limit error → 指数退避重试 3 次,仍失败则该帧 skipped,记 stats 不阻塞整个摄入

### 3.5 chunk 模型扩展

`RawContentChunk` schema 极小改动(仅扩展 `source_type` 取值,不改字段):

```python
# app/tools/extractors/base.py
class RawContentChunk(BaseModel):
    source_type: str
    # "bilibili" | "pdf" | "youtube"
    # NEW: "bilibili_visual" | "youtube_visual" — visual-augmented chunks
    raw_text: str
    metadata: dict = Field(default_factory=dict)
    # NEW for *_visual:
    #   {"start_time": .., "end_time": ..,
    #    "vision_source": "keyframe",
    #    "frame_count": 5,
    #    "vision_model": "claude-3-5-sonnet-20241022"}
    media_url: str | None = None
```

不引入新 schema 类的原因:

- ContentAnalyzer / SectionPlanner / LessonGenerator 全程把 chunk 当作"带时间戳的文本块",视觉 chunk 在它们眼里就是文本
- metadata 的 `vision_source` 字段保留可观测信号,前端 / 调试可识别"这段内容来自画面"

### 3.6 chunk 合并:`ChunkMerger`

```python
def merge_chunks(
    subtitle_chunks: list[RawContentChunk],
    visual_chunks: list[RawContentChunk],
) -> list[RawContentChunk]:
    """Interleave subtitle and visual chunks by start_time.

    Both lists are assumed already sorted by start_time. Visual chunks
    are placed at their window's start_time. Ties: subtitle first
    (subtitle is the human-author signal; visual is augmentation).
    """
    all_chunks = sorted(
        subtitle_chunks + visual_chunks,
        key=lambda c: (c.metadata.get("start_time", 0), 0 if "_visual" not in c.source_type else 1),
    )
    return all_chunks
```

### 3.7 集成点改造

#### `worker/tasks/content_ingestion.py`

```python
# 现有 (line 266-271):
result = await extractor.extract(source.url or "")
source.raw_content = "\n\n".join(c.raw_text for c in result.chunks)

# 改成:
result = await extractor.extract(source.url or "")

# NEW: vision augmentation (subtitle-sparse-triggered)
if source.type in {"bilibili", "youtube"} and settings.VISION_ENABLED:
    from app.services.vision import augment_with_vision
    visual_chunks = await augment_with_vision(
        source=source,
        subtitle_chunks=result.chunks,
        model_router=resources.model_router,
    )
    if visual_chunks:
        result = result.copy(update={
            "chunks": ChunkMerger.merge_chunks(result.chunks, visual_chunks),
        })
        source.metadata = {
            **(source.metadata or {}),
            "vision_augmentation": {
                "visual_chunk_count": len(visual_chunks),
                "vision_model": visual_chunks[0].metadata.get("vision_model"),
            },
        }

source.raw_content = "\n\n".join(c.raw_text for c in result.chunks)
```

`augment_with_vision` 内部封装 §3.2 → §3.3 → §3.4 → §3.5 → §3.6 全部流程,失败时 return `[]`(降级)。

#### `services/section_planner.py` & `services/lesson_generator.py`

零改动。chunk 在它们眼里就是 chunk,视觉 chunk 走同样的 SectionPlanner tier 路由,与字幕 chunk 一起被 bucketing。

#### `services/content_analyzer.py`

零改动。视觉 chunk 的 `raw_text` 已经是可分析的自然语言,analyzer 不需要知道它的来源。

但有一个**软约束**:`content_analyzer` 的 prompt 里目前可能有"如果这段是字幕"的措辞——需要审视一遍,确保中性描述(用"内容片段"而非"字幕")。

## 4. 可观测性

| 信号 | 触发条件 | 写入位置 |
|---|---|---|
| `logger.info("Vision augmentation: %d sparse windows, %d frames sampled, %d visual chunks emitted")` | 视觉通路启用 | 日志 |
| `logger.warning("Vision describe failed for frame at T=%ds: %s; skipping")` | 单帧描述失败 | 日志 + Sentry |
| `logger.info("Vision skipped: sparse_ratio=%.2f below threshold %.2f")` | 早退 | 日志 |
| `source.metadata.vision_augmentation.visual_chunk_count` | 摄入完成 | DB |
| `source.metadata.vision_augmentation.frames_sampled` | 摄入完成 | DB |
| `source.metadata.vision_augmentation.frames_deduped` | 摄入完成 | DB |
| `source.metadata.vision_augmentation.input_tokens` | 摄入完成 | DB |
| `source.metadata.vision_augmentation.output_tokens` | 摄入完成 | DB |
| `source.metadata.vision_augmentation.estimated_cost_usd` | 摄入完成 | DB(基于 provider 价格表) |
| `source.metadata.vision_augmentation.skipped_reason` | 早退 / provider 不可用 | DB |

前端在 Sources 页面新增一个小标签"含画面理解"(当 `visual_chunk_count > 0`),让用户感知到产品形态。

## 5. 测试策略

### 5.1 `SubtitleDensityAnalyzer` 单元测试

- 致密字幕 → 无 sparse window
- 全空字幕 → 整段 sparse window
- 间歇空字幕 → 正确合并相邻稀疏窗口
- 长视频(2 小时)无字幕 → window 被 `MAX_WINDOW_SECONDS` 拆分
- 中文字符密度阈值 vs 英文阈值
- `ENABLE_VISION_RATIO` 早退路径

### 5.2 `FrameSampler` 单元测试

用一个 60s 的测试视频(checked into `backend/tests/fixtures/`),验证:

- I-frame 抽帧数量在合理范围
- phash 去重生效(全程同一帧的视频应只剩 1 帧)
- `MAX_FRAMES_PER_WINDOW` 截断生效
- ffmpeg 不存在时 raise `FrameSamplerError` 而非 silent

### 5.3 `VisionDescriber` 单元测试

- `AnthropicProvider.describe_image` 用 record/replay(VCR-style)验证 image content block 构造
- `OpenAICompatProvider.describe_image` 同上(用 Qwen-VL endpoint mock)
- 不支持 vision 的 provider(Codex)→ 抛 NotImplementedError
- `(transitional)` 描述被识别并丢弃

### 5.4 端到端集成测试

`tests/test_content_ingestion_vision.py`:

- 测试视频 + 完整字幕 → 视觉通路跳过,管线退化为纯字幕(无回归)
- 测试视频 + 空字幕 → 视觉通路触发,chunks 中包含 `_visual` source_type
- vision provider 路由未配置 → 摄入仍成功,降级到纯字幕,`source.metadata.vision_augmentation.skipped_reason="no_provider"`
- vision provider 全部失败 → 摄入仍成功,降级,记 skipped_reason

### 5.5 现有测试回归

跑 `pytest tests/test_section_planner.py tests/tools/extractors/ tests/test_content_ingestion.py` 验证视觉通路关闭(`VISION_ENABLED=False`)时零行为变化。

## 6. Trade-offs 与已知限制

### 6.1 接受的不精确

- **phash 阈值是经验值**。复杂渐变(动画场景)可能被误判为重复,但学习视频里这类内容稀少
- **I-frame 不等于"重要帧"**。某些编码器会在均匀间隔强制 I-frame,可能错过场景内的关键时刻。短期接受,后续可换 `select='gt(scene\,0.4)'` 场景检测
- **vision LLM 描述非确定性**。同一帧两次描述会有差异,影响 idempotent ingestion。可接受——chunk 内容本来就被 LLM 重新生成,vision 多一个不确定性源不增加用户可见的波动

### 6.2 设计上的妥协

- **MinIO 视频 cache 占空间**。720p 30 分钟视频约 300MB。Cache 加 TTL(默认 7 天)+ 单 source 大小上限,超出自动清理
- **抽帧失败 → 整段视觉降级**。某些视频流不可下载(地区限制 / DRM / 私有视频)→ 跌回纯字幕。在 stats 显式标注 `skipped_reason="stream_unavailable"`
- **vision 描述无法精确对齐字幕时间轴**。视觉 chunk 的 timestamp = 关键帧 timestamp,但口播可能在帧前后展开。SectionPlanner 已经按时间窗口聚合 chunk,不要求精确对齐

### 6.3 显式不做

- **讲话人识别**。投入产出比低,放后续工作
- **OCR 单独通道**。vision LLM 自带 OCR 能力,加 PaddleOCR/Tesseract 等于增加依赖矩阵换边际精度
- **关键帧采用 ML 场景检测**。短期 ffmpeg I-frame + phash 足够,工程复杂度低
- **视觉描述的 embedding 入 RAG**。当前管线把所有 chunk(含视觉)的 raw_text embed,无需特殊处理。视觉 chunk 自动进 RAG 检索

## 7. 兼容性

| 维度 | 影响 |
|---|---|
| 已存在 source 的 chunks | 零影响——不会重新摄入 |
| 已存在 course / lesson | 零影响 |
| 新摄入 source(visual_enabled=False) | 完全等同当前行为 |
| 新摄入 source(visual_enabled=True) | chunks 增加视觉条目,SectionPlanner 自然多出 / 增大 bucket;触发 lesson-input-budget.md 中的 split pass 保护 |
| DB schema | source.metadata 增加 `vision_augmentation` 嵌套字段,无需迁移 |
| LLMProvider API | 新增 `describe_image()` / `supports_vision()`,默认实现保持向后兼容 |
| ModelRouter API | 新增 `TaskType.VISION_DESCRIPTION`,不传不路由,向后兼容 |

## 8. 改动清单

| # | 文件 | 改动类型 | 内容 |
|---|---|---|---|
| 1 | `backend/pyproject.toml` | 修改 | 添加 `ffmpeg-python>=0.2`, `imagehash>=4.3`, `yt-dlp>=2024.7` 依赖 |
| 2 | `backend/app/services/llm/base.py` | 修改 | `LLMProvider` 加 `describe_image()` / `supports_vision()` |
| 3 | `backend/app/services/llm/anthropic.py` | 修改 | 实现 `describe_image()`,使用 Anthropic vision content block |
| 4 | `backend/app/services/llm/openai_compat.py` | 修改 | 实现 `describe_image()`,使用 OpenAI `image_url` content type |
| 5 | `backend/app/services/llm/router.py` | 修改 | `TaskType.VISION_DESCRIPTION` 枚举值 + 路由校验 `supports_vision` |
| 6 | `backend/app/services/llm/config.py` | 修改 | model 配置加 `supports_vision` 字段 |
| 7 | `backend/app/services/vision/__init__.py` | 新建 | 导出 `augment_with_vision` 入口 |
| 8 | `backend/app/services/vision/density.py` | 新建 | `SubtitleDensityAnalyzer` + `SparseWindow` |
| 9 | `backend/app/services/vision/sampler.py` | 新建 | `FrameSampler` + ffmpeg I-frame + phash dedup |
| 10 | `backend/app/services/vision/stream_cache.py` | 新建 | MinIO 视频流缓存 |
| 11 | `backend/app/services/vision/describer.py` | 新建 | `VisionDescriber` + 并发控制 + 重试 |
| 12 | `backend/app/services/vision/merger.py` | 新建 | `ChunkMerger.merge_chunks()` |
| 13 | `backend/app/services/vision/orchestrator.py` | 新建 | `augment_with_vision()` 串联 density → sampler → describer → merger + 失败降级 |
| 14 | `backend/app/services/prompts/vision_describe.md` | 新建 | vision LLM prompt 模板 |
| 15 | `backend/app/tools/extractors/base.py` | 修改 | `RawContentChunk.source_type` 注释更新(允许 `*_visual` 后缀) |
| 16 | `backend/app/worker/tasks/content_ingestion.py` | 修改 | 在 extract 之后、analyzer 之前调 `augment_with_vision` |
| 17 | `backend/app/core/config.py` | 修改 | 加 `VISION_ENABLED`, `VISION_MAX_CONCURRENCY`, `MIN_EMPTY_GAP_SECONDS` 等设置 |
| 18 | `backend/tests/services/vision/test_density.py` | 新建 | §5.1 单测 |
| 19 | `backend/tests/services/vision/test_sampler.py` | 新建 | §5.2 单测 + 60s fixture 视频 |
| 20 | `backend/tests/services/vision/test_describer.py` | 新建 | §5.3 单测 |
| 21 | `backend/tests/test_content_ingestion_vision.py` | 新建 | §5.4 端到端 |
| 22 | `frontend/src/app/sources/page.tsx` | 修改 | 列表项加"含画面理解"标签 |
| 23 | `docs/design/visual-ingestion.md` | 新建 | 本文档 |

执行顺序: 1 → 2-6 (provider 抽象层) → 7-14 (视觉服务) → 15-17 (接线) → 18-21 (测试) → 22 (前端) → 23。

## 9. 风险

- **ffmpeg 部署依赖**。Docker 镜像需 apt install ffmpeg。已有镜像加这一行即可,无 Python 端复杂度
- **视频流下载合规**。Bilibili / YouTube 的 ToS 对自动化下载有限制。降低分辨率(360p 足够)+ 仅 source owner 触发摄入,降低风险。MinIO cache 不公开访问
- **vision LLM 价格波动**。Anthropic vision 单价是文本的 ~2x。可观测性章节的 cost 上报让运营层能监控成本
- **空字幕视频比例高时摄入耗时翻倍**。即使有早退路径,极端情况(纯演示视频)摄入仍可能比当前慢 50-100%。前端轮询进度页要更新文案,告知"正在分析画面"
- **provider 不支持 vision 的 fallback**。`OpenAICompatProvider` 当面对的是 DeepSeek-chat(非 VL 版本)时,vision 调用会失败。`supports_vision` 校验放在路由层,在 `ModelConfigManager` 加载配置时验证

## 10. 后续工作(本次不做)

- **PDF 视觉摄入**。学术 PDF 里大量图表当前完全被丢弃。后续单独设计:每页 → vision LLM → 图表描述并入 chunk
- **场景检测替换 I-frame**。换成 ffmpeg `select='gt(scene\,N)'` 或 PySceneDetect,关键帧质量更高
- **讲话人 diarization**。多嘉宾访谈类视频可能需要,但产品形态决定优先级
- **Vision 描述 quality 评估**。EvalAgent 引入"画面描述是否被 lesson 实际利用"的 metric,作为 vision provider 选型的反馈信号
- **Vision provider tier 路由**。引入"快速便宜的 vision"(Qwen-VL-Plus / GPT-4o-mini)与"精确的 vision"(Claude 3.5 Sonnet)分层,按视频类型路由
- **视觉 chunk 重要性加权**。SectionPlanner 当前对所有 chunk 等同处理,后续可让视觉 chunk(含 OCR 文字)在 bucketing 时有更高权重
- **provider 切换时自动 re-augment**:同 lesson-input-budget §10
