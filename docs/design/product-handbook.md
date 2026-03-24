# LearnMentor 产品设计手册

**AI 驱动的自适应学习系统 · 产品设计手册 v2.0**

> 本手册汇总了 LearnMentor 从概念构想到产品规划的全部讨论、调研报告和设计文档，
> 作为开发团队和未来潜在投资者的核心参考文件。

---

## 目录

- [第一部分：产品愿景与定位](#第一部分产品愿景与定位)
- [第二部分：竞品分析与市场洞察](#第二部分竞品分析与市场洞察)
- [第三部分：核心设计哲学](#第三部分核心设计哲学)
- [第四部分：系统架构](#第四部分系统架构)
- [第五部分：Agent Memory 体系设计](#第五部分agent-memory-体系设计)
- [第六部分：核心模块详细设计](#第六部分核心模块详细设计)
- [第七部分：数据模型](#第七部分数据模型)
- [第八部分：商业模式与 PMF 验证](#第八部分商业模式与-pmf-验证)
- [第九部分：产品路线图](#第九部分产品路线图)
- [第十部分：风险分析与应对策略](#第十部分风险分析与应对策略)
- [附录](#附录)

---

# 第一部分：产品愿景与定位

## 1.1 一句话定义

> 一个拥有 Agent 灵魂的学习系统——它不只是播放视频和生成题目，它是一个能理解你、记住你、陪你成长的 AI 导师。

## 1.2 核心问题

传统学习平台解决的是"找到信息"的问题。LearnMentor 解决的是**"学会知识"**的问题。

同一篇论文，对初学者它会抽出核心思想用大白话讲；对进阶学生它会聚焦方法论细节并设计复现实验。这个"因材施教"的层才是 LearnMentor 与 NotebookLM、传统知识库的根本差异。

## 1.3 产品定位

- **目标用户**：通用型（技术 + 非技术学习者均覆盖）
- **初始聚焦**：编程/CS/AI 教育（LLM 亲和度高、YouTube 生态丰富、付费意愿强）
- **发展路径**：先自己用 → 小圈子 beta → 面向公众开放
- **竞争定位**：唯一同时具备「持久学生画像 + 任意内容摄入 + 苏格拉底式 AI 导师 + 主动知识探索」的产品

## 1.4 与竞品的本质差异

| 维度 | NotebookLM | Khanmigo | Duolingo | **LearnMentor** |
|------|-----------|----------|----------|----------------|
| 核心问题 | "资料说了什么？" | "这道题怎么做？" | "今天学了吗？" | **"你怎么才能学会？"** |
| 学生画像 | ❌ 无 | 部分 | ✅ 自适应 | ✅ 持续演化认知模型 |
| 内容来源 | ✅ 多源 | ❌ 自有内容 | ❌ 自有内容 | ✅ 任意来源 |
| Agent 主动性 | ❌ 被动应答 | 部分引导 | ✅ 推送提醒 | ✅ 主动探索+教学 |
| 游戏化 | ❌ | ❌ | ✅ 核心 | 🔜 Phase 2 |
| 记忆体系 | ❌ 无状态 | 会话级 | 行为级 | ✅ 多层级长期记忆 |

---

# 第二部分：竞品分析与市场洞察

## 2.1 AI-Native 学习产品竞争格局

### 2.1.1 内容理解工具（无学习记忆）

**Google NotebookLM**
- 处理 PDF、YouTube 字幕、URL、Google Docs，生成 AI 综合理解
- 免费版支持 100 个笔记本，每个 50 个来源
- NotebookLM Plus 定价 $19.99/月（通过 Google One AI Premium）
- Audio Overviews（播客风格摘要）爆火，验证了将文字内容转化为沉浸式格式的巨大需求
- **关键缺陷**：零学习记忆——每次会话从头开始，无学生画像、无自适应、无间隔重复

### 2.1.2 AI 辅导平台（锁定内容生态）

**Khan Academy Khanmigo**
- 定价 $4/月，2024-25 学年覆盖 70 万 K-12 学生（同比从 4 万增长）
- 苏格拉底式教学法（引导式提问而非直接给答案）是教育 AI 的金标准
- 教师免费使用，加速 B2B2C 通过学区采纳
- **关键限制**：锁定在 Khan Academy 自有内容库

**Synthesis Tutor**
- 面向 5-11 岁儿童的 AI 数学辅导，定价 $119/年
- 2.5 万个家庭，$10M+ 年化收入
- 深度优于广度（仅数学）的策略实现了窄领域的卓越质量

**Coursera Coach**
- 嵌入 98% 的 Coursera 7,000+ 课程
- 推动测验通过率提升 9.5%
- 覆盖 1.91 亿注册学习者

### 2.1.3 游戏化驱动平台（单一领域）

**Duolingo**
- FY2025 收入 $10.38 亿（+39% YoY），调整后 EBITDA $3.059 亿（29.5% 利润率）
- 5,270 万 DAU，DAU/MAU 比率 39.6%（教育类极为罕见）
- 核心引擎是游戏化——连续天数、XP、排行榜、好友互动
- 超过 1,000 万用户保持 1 年以上连续学习
- Duolingo Max（GPT-4 驱动）定价 ~$29.99/月
- **100% 的内容由 GenAI 生成**，生产时间缩短 80%
- **关键启示**：游戏化不是功能——它是教育留存危机的首要解决方案。教育 App Day 30 留存平均仅 2.1%，Duolingo 的游戏化实现了 5 倍于基准的留存

### 2.1.4 警示性失败案例

- **Quizlet Q-Chat**：2025 年 6 月关闭——首个基于 ChatGPT 的 AI 学习助手，因缺乏深度差异化无法存活
- **Google Socratic**：2024 年 10 月悄然关闭，功能被 Google Lens 吸收
- **启示**：没有护城河的 AI 聊天包装层面临生存风险

### 2.1.5 新兴独角兽

- **Speak**：AI 语言学习，2024 年 12 月达 $10 亿估值，$1 亿+ 年化收入，1,000 万+ 学习者
- **MagicSchool AI**：500 万教育者，160 个国家，从 $240 万种子轮到 $6,200 万仅用 17 个月
- **Oboe**：a16z 领投 $2,000 万（2025 年 12 月），从提示生成完整 AI 课程

### 2.1.6 竞品对比矩阵

| 产品 | 自适应画像 | 多源内容 | AI导师 | 游戏化 | 主动探索 | 价格/月 |
|------|:---:|:---:|:---:|:---:|:---:|---:|
| **LearnMentor** | ✅ | ✅ | ✅ | 🔜 | ✅ | 待定 |
| NotebookLM | ❌ | ✅ | ❌ | ❌ | ❌ | $0-20 |
| Khanmigo | 部分 | ❌ | ✅ | ❌ | ❌ | $4 |
| Duolingo Max | ✅ | ❌ | 部分 | ✅ | ❌ | $30 |
| Coursera Coach | ❌ | ❌ | ✅ | ❌ | ❌ | $59 |
| Synthesis Tutor | ✅ | ❌ | ✅ | ✅ | ❌ | $10 |

## 2.2 中国市场

### 硬件主导的特殊格局

中国 AI 教育市场是硬件驱动——学习机（平板）是主要产品形态，2025 Q1 市场规模达 ¥40.2 亿（$5.55 亿），同比增长 15.8%。

- **学而思**：学习平板 ¥2,699-¥6,499，自研 MathGPT 九章大模型（首个 100B+ 参数数学大模型），AI 助手小思 2024 年被调用 2.3 亿次
- **松鼠 AI**：获 TIME 2025 最佳发明，服务 2,400 万学生，2,000+ 实体门店
- **科大讯飞**：自研 Spark X1 模型，幻觉率仅 2.39%（行业平均 6.8%），覆盖 5 万所学校

### LearnMentor 在中国的机会

- 纯软件在 K-12 市场面临硬件垄断
- **Bilibili 视频摄入**是战略级差异化——B站学习区极为热门，没有硬件竞品摄入此内容
- 目标缝隙：成人/职业学习者 + 海外华人学生

### 政策背景

- 2021 年"双减"政策禁止营利性 K-12 补课，但加速了 AI 学习设备的采用
- 2025 年起北京要求中小学每年至少 8 课时 AI 教育，全国推广在即
- 2025 年 9 月起 AI 内容标注要求生效

## 2.3 行业趋势（2025-2026）

1. **Agentic AI 取代聊天包装层**：从生成式 AI（从提示创建内容）到代理式 AI（自主执行多步工作流）
2. **AI 辅导效果获学术验证**：哈佛 2025 年 RCT 研究（发表于 Nature Scientific Reports）证明设计良好的 AI 辅导在学习效果和时间效率上均优于课堂主动学习
3. **监管加速**：EU AI Act 将教育 AI 列为高风险系统（2026 年 8 月 2 日生效）；美国 COPPA 更新（2026 年 4 月生效）
4. **RAG 成为教育 AI 标准架构**：LPITutor 研究实现 86% 回答准确率；GraphRAG 在教育领域因更好表达前置知识关系而优于传统 RAG
5. **融资环境偏向资本效率**：EdTech VC 从 2021 年 $208 亿暴跌至 2024 年 $24 亿，2025 年维持在 ~$28 亿

---

# 第三部分：核心设计哲学

## 3.1 不是工具，是导师

传统学习平台的逻辑：**用户主动操作 → 系统被动响应**

LearnMentor 的逻辑：**导师主动观察 → 理解学生 → 适时引导**

| 传统平台 | LearnMentor |
|----------|-------------|
| 用户搜索课程 | 导师根据目标推荐学习路径 |
| 看完视频做题 | 导师发现你哪里卡住了，调整讲解方式 |
| 千人一面的习题 | 根据薄弱点动态生成针对性练习 |
| 学完就结束 | 导师记得三个月前学了什么，帮你串联知识 |
| 冷冰冰的界面 | 有个性、有温度、会鼓励也会 push 你 |

## 3.2 Agent 设计哲学：LLM + 工具调用 + 循环推理

```
用户行为/消息 或 系统触发器（定时/事件）
    ↓
导师 Agent（LLM 推理）
    ├── 被动模式（用户发起）
    │   └── 用户提问/做题/看视频 → 响应 + 更新画像
    │
    └── 主动模式（Agent 发起）
        ├── 新内容摄入 → 消化 → 关联图谱 → 评估相关性 → 推荐
        ├── 定时巡检 → 扫描薄弱点 → 搜索补强材料 → 生成学习建议
        ├── 知识库变更 → 发现跨源关联 → 主动串联讲解
        └── 学生行为信号 → 连续做错 → 找替代讲解方式
                         → 学习停滞 → 找新鲜内容激发兴趣
                         → 快速进步 → 拉出更高难度内容
```

## 3.3 产品四根支柱

| 支柱 | 解决什么问题 | 核心能力 | 优先级 |
|------|------------|---------|--------|
| **导师 Agent + 学生画像** | "学得好" | 个性化、因材施教 | P0 (MVP) |
| **主动探索 + 知识库** | "学得深" | Agent 自主消化内容、发现关联、主动推送 | P0 (MVP) |
| **游戏化 / 习惯机制** | "回得来" | 留存、习惯养成 | P1 (Phase 2) |
| **内容摄入引擎** | "学得到" | 任意来源变结构化课程 | P0 (MVP, 先 YouTube) |

## 3.4 知识库 = 基础设施层 | 导师 Agent + 学生画像 = 价值层

知识库是底层能力，但不是差异化所在。真正的价值在于导师 Agent 如何利用知识库、结合学生画像，进行个性化、主动的教学。

同一个概念（如 "Tokenization"）可能出现在 Karpathy 的视频、Diego 的博客、BPE 论文中——知识库不存三份独立条目，而是**一个概念节点关联多个来源**。导师可以说：
> "这个概念 Karpathy 在视频第 23 分钟讲过，Diego 的博客也有图解，你想从哪个角度回顾？"

---

# 第四部分：系统架构

## 4.1 技术栈

```
┌─────────────────────────────────────────────────┐
│                   Frontend                       │
│             Next.js 14+ (App Router)             │
│         React · TypeScript · Tailwind CSS        │
│      Monaco Editor · YouTube/Bilibili Embed      │
│           shadcn/ui · D3.js 知识图谱             │
└──────────────────┬──────────────────────────────┘
                   │ REST / WebSocket / SSE
┌──────────────────▼──────────────────────────────┐
│          Backend — Python / FastAPI              │
│                                                  │
│  Agent Engine                                    │
│  ├── MentorAgent (核心推理循环)                    │
│  ├── CourseAgent (课程生成)                        │
│  ├── LabAgent (Lab 设计)                          │
│  ├── EvalAgent (评估判分)                          │
│  └── ProactiveExplorer (主动探索引擎)              │
│                                                  │
│  Tools (Agent 工具集)                             │
│  ├── ContentExtractor (YouTube/Bilibili/PDF/MD/URL)│
│  ├── WebSearcher (网络搜索)                       │
│  ├── CodeRunner (Docker 沙箱)                     │
│  ├── ProfileManager (学生画像)                    │
│  ├── KnowledgeBase (RAG 检索)                    │
│  ├── MemoryManager (记忆体系管理)                 │
│  └── ContentGenerator (教案/习题/Lab)             │
│                                                  │
│  LLM Client: anthropic (Claude API)              │
│  Task Queue: Celery + Redis (异步长任务)           │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│                 Data Layer                        │
│                                                  │
│  PostgreSQL + pgvector         Redis    S3/MinIO │
│  ├── 用户/学生画像              缓存     文件存储 │
│  ├── 课程/章节/知识点           会话     生成内容 │
│  ├── Agent Memory Store        队列              │
│  ├── 学习记录/对话历史                            │
│  └── 向量 embeddings (RAG)                       │
└─────────────────────────────────────────────────┘
```

## 4.2 技术选型理由

| 选型 | 理由 |
|------|------|
| **Next.js** | SSR 对 SEO 友好（未来开放时重要），App Router 支持流式渲染 LLM 输出，生态丰富 |
| **Python / FastAPI** | LLM 生态一等公民（anthropic SDK、pymupdf、whisper 等全原生）；异步原生适配 Agent 并发工具调用；Pydantic 数据模型与 FastAPI 无缝配合 |
| **PostgreSQL + pgvector** | 一个数据库搞定关系数据和向量搜索，运维简单 |
| **Claude API** | Tool use 能力成熟，与 Agent 模式天然契合；流式输出体验好 |
| **Celery + Redis** | 异步处理长任务（视频转录、PDF 解析、批量内容分析） |

## 4.3 多 Agent 协作架构

```
                    ┌──────────────┐
                    │  导师 Agent   │  ← 用户唯一交互入口
                    │  (Mentor)    │
                    └──────┬───────┘
                           │
            ┌──────────────┼──────────────┐
            ↓              ↓              ↓
    ┌──────────────┐ ┌──────────┐ ┌──────────────┐
    │ 课程设计 Agent│ │ Lab Agent│ │ 评估 Agent    │
    │              │ │          │ │              │
    │ - 分析视频    │ │ - 设计练习│ │ - 判定答案    │
    │ - 生成教案    │ │ - 写测试  │ │ - 分析错误    │
    │ - 搜集资料    │ │ - 分级提示│ │ - 更新画像    │
    └──────────────┘ └──────────┘ └──────────────┘
            ↑                              ↑
            └──────────┐  ┌────────────────┘
                    ┌──▼──▼───────┐
                    │ 主动探索引擎 │  ← 后台异步运行
                    │ (Explorer)  │
                    │ - 内容消化   │
                    │ - 跨源关联   │
                    │ - 定时巡检   │
                    └─────────────┘
```

---

# 第五部分：Agent Memory 体系设计

## 5.1 设计原则

贴身私教的核心体验是：**它记得关于你的一切**。不只是你叫什么名字，而是你三周前在哪个概念上卡住了、什么样的解释方式对你最有效、你最近的学习势头如何。

Agent Memory 需要解决三个问题：
1. **LLM 上下文窗口有限**——不能把所有历史都塞进去
2. **需要在正确的时机回忆正确的记忆**——不是什么都回忆，而是精准检索
3. **记忆需要随时间演化**——新的理解应该覆盖旧的、过时的判断

## 5.2 五层记忆架构

```
┌─────────────────────────────────────────────────────────────┐
│                    导师 Agent 的记忆体系                       │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Layer 1: 工作记忆 (Working Memory)                    │    │
│  │ 当前会话的对话历史 + 当前正在处理的内容                    │    │
│  │ 存储：内存 / Redis                                    │    │
│  │ 生命周期：单次会话                                     │    │
│  │ 上限：最近 N 轮对话 + 当前上下文                        │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Layer 2: 学生画像记忆 (Profile Memory)                │    │
│  │ 持续演化的学生认知模型                                  │    │
│  │ 存储：PostgreSQL (JSONB)                              │    │
│  │ 生命周期：永久，持续更新                                │    │
│  │ 包含：能力评估、学习风格、薄弱点、教学策略               │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Layer 3: 情节记忆 (Episodic Memory)                   │    │
│  │ 具体的学习事件和交互片段                                │    │
│  │ 存储：PostgreSQL + pgvector (语义检索)                  │    │
│  │ 生命周期：永久，按重要性衰减                            │    │
│  │ 包含：关键对话、顿悟时刻、困难时刻、错误模式            │    │
│  │ 例如："2024-03-15 在讨论 attention 时，                │    │
│  │       用矩阵乘法的类比解释后学生表示理解了"             │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Layer 4: 课程内容记忆 (Content Memory)                │    │
│  │ 导师"读过"和"教过"的内容                               │    │
│  │ 存储：PostgreSQL + pgvector                           │    │
│  │ 生命周期：永久                                         │    │
│  │ 包含：                                                │    │
│  │ - 哪些内容已摄入、已消化、已教授                        │    │
│  │ - 每个概念用过哪些讲解方式，效果如何                     │    │
│  │ - 不同来源对同一概念的不同解释                          │    │
│  │ - 内容之间的关联和前置依赖                              │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Layer 5: 进度记忆 (Progress Memory)                   │    │
│  │ 学生在每个课程/概念上的学习进度                          │    │
│  │ 存储：PostgreSQL                                      │    │
│  │ 生命周期：永久，实时更新                                │    │
│  │ 包含：                                                │    │
│  │ - 概念掌握度（0-1，基于贝叶斯知识追踪）                 │    │
│  │ - 课程进度（已看/未看/正在看）                          │    │
│  │ - Lab 完成情况 + 耗时 + 正确率                         │    │
│  │ - 习题正确率 + 错误类型分析                            │    │
│  │ - 间隔重复调度（下次复习时间）                          │    │
│  │ - 学习曲线数据（时间 vs 掌握度）                       │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Layer 6: 元认知记忆 (Metacognitive Memory)            │    │
│  │ Agent 对自身教学效果的反思                              │    │
│  │ 存储：PostgreSQL                                      │    │
│  │ 生命周期：永久                                         │    │
│  │ 包含：                                                │    │
│  │ - 哪种教学策略对这个学生有效/无效                       │    │
│  │ - 什么时间段学生学习效果最好                            │    │
│  │ - 学生对不同交互模式（苏格拉底/直接/鼓励）的反应        │    │
│  │ - Agent 的自我改进日志                                 │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 5.3 记忆检索策略

Agent 在每次推理时不会加载所有记忆——它根据当前上下文**精准检索**相关记忆：

```python
class MemoryManager:
    """管理 Agent 的多层记忆检索"""

    async def build_context(self, user_message: str, session_id: str) -> AgentContext:
        """为当前推理构建最优上下文"""

        # Layer 1: 工作记忆 — 始终包含
        working = await self.get_working_memory(session_id)

        # Layer 2: 学生画像 — 始终包含（压缩版）
        profile = await self.get_compressed_profile(student_id)

        # Layer 3: 情节记忆 — 语义检索最相关的 3-5 条
        episodes = await self.search_episodic_memory(
            query=user_message,
            student_id=student_id,
            top_k=5,
            recency_weight=0.3,  # 近期记忆权重更高
        )

        # Layer 4: 内容记忆 — 基于当前话题检索
        content = await self.search_content_memory(
            query=user_message,
            course_id=current_course_id,
            top_k=3,
        )

        # Layer 5: 进度记忆 — 检索相关概念的掌握度
        progress = await self.get_relevant_progress(
            query=user_message,
            student_id=student_id,
        )

        # Layer 6: 元认知 — 检索有效教学策略
        meta = await self.get_teaching_strategies(student_id)

        return AgentContext(
            working_memory=working,
            profile=profile,
            relevant_episodes=episodes,
            relevant_content=content,
            progress=progress,
            teaching_strategies=meta,
        )
```

## 5.4 记忆写入与更新

每次交互后，Agent 异步更新多层记忆：

```python
async def post_interaction_update(self, interaction: Interaction):
    """交互后异步更新记忆（不阻塞响应）"""

    # 1. 更新学生画像（LLM 推断）
    profile_update = await self.llm.analyze(
        "基于这次交互，学生画像需要更新什么？"
        "注意：观察 1 次记录但不更新；3 次一致标记'可能'；5 次确认"
    )
    if profile_update.confidence > THRESHOLD:
        await self.update_profile(profile_update)

    # 2. 判断是否值得存入情节记忆
    importance = await self.assess_episode_importance(interaction)
    if importance > 0.6:  # 只存重要事件
        await self.store_episode(
            summary=interaction.summary,
            embedding=await self.embed(interaction.summary),
            importance=importance,
            tags=interaction.concepts,
        )

    # 3. 更新进度记忆
    if interaction.involves_assessment:
        await self.update_concept_mastery(
            concept_id=interaction.concept_id,
            correct=interaction.was_correct,
            response_time=interaction.duration,
        )

    # 4. 更新元认知记忆
    if interaction.teaching_strategy_used:
        await self.log_strategy_effectiveness(
            strategy=interaction.teaching_strategy_used,
            student_response=interaction.student_sentiment,
            learning_outcome=interaction.outcome,
        )
```

## 5.5 记忆在 System Prompt 中的注入

```python
def build_system_prompt(self, context: AgentContext) -> str:
    return f"""你是 LearnMentor 的导师 Agent。

## 你的学生（画像摘要）
姓名：{context.profile.name}
学习目标：{context.profile.learning_goals}
当前水平：{context.profile.competency_summary}
学习风格：{context.profile.learning_style_summary}
薄弱点：{context.profile.weak_spots}

## 你对这个学生的记忆
{self.format_episodes(context.relevant_episodes)}

## 相关课程内容
{self.format_content(context.relevant_content)}

## 学生在相关概念上的进度
{self.format_progress(context.progress)}

## 有效的教学策略
{self.format_strategies(context.teaching_strategies)}

## 你的行为准则
- 苏格拉底式引导优先于直接给答案
- 根据学生 pace 和 learning_style 调整讲解
- 如果学生 prefers_code_first，先代码后概念
- 利用情节记忆中记录的有效讲解方式
- 回答时引用知识库中的具体来源
- 发现学生可能不知道的关联知识时主动提出
"""
```

## 5.6 记忆体系与冷启动

新用户没有记忆是"贴身私教"体验的最大挑战。解决方案：

1. **Day 0 诊断评估**：5-10 个自适应问题，快速建立初始画像
2. **人口先验**：基于相似用户群体的统计数据初始化推荐
3. **快速渐进式填充**：前 3 次会话内高频更新画像
4. **降级体验独立优秀**：即使没有记忆，基础 AI 辅导体验也必须好用

---

# 第六部分：核心模块详细设计

## 6.1 统一内容摄入引擎

```
任意来源
  ├── YouTube URL    → youtube-transcript-api 提取字幕
  ├── Bilibili URL   → bilibili-api 提取字幕
  ├── PDF 文件       → pymupdf / marker 提取文本+结构
  ├── Markdown 文件  → 原生解析
  └── URL / HTML     → httpx + readability-lxml 提取正文
         ↓
统一 ContentChunk 输出
         ↓
LLM 结构化分析（分段 → 概念提取 → 难度评估 → 前置知识推断）
         ↓
知识库写入（文本分块 → embedding → 概念图谱 → 跨来源关联）
```

### 实现骨架

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel

class ContentChunk(BaseModel):
    source_type: str           # "youtube" | "bilibili" | "pdf" | "markdown" | "url"
    raw_text: str
    metadata: dict = {}        # {"start_time": 180} or {"page": 3}
    media_url: str | None = None

class ContentExtractor(ABC):
    @abstractmethod
    async def extract(self, source: str) -> list[ContentChunk]: ...

# 工厂模式
EXTRACTORS: dict[str, type[ContentExtractor]] = {
    "youtube": YouTubeExtractor,
    "bilibili": BilibiliExtractor,
    "pdf": PDFExtractor,
    "markdown": MarkdownExtractor,
    "url": URLExtractor,
}
```

### 长视频处理策略

超长内容（如 Karpathy 3.5 小时视频）可能超过 LLM 上下文限制：
1. 按时间/章节切分为 10-15 分钟片段
2. 每个片段独立分析
3. 最后一次 LLM 调用做全局整合（只输入每片段摘要）

## 6.2 导师 Agent 核心循环

```python
class MentorAgent:
    def __init__(self, llm, tools, memory_manager, profile):
        self.llm = llm
        self.tools = tools
        self.memory = memory_manager
        self.profile = profile

    async def process(self, user_message: str) -> AsyncIterator[str]:
        # 1. 构建上下文（记忆检索）
        context = await self.memory.build_context(user_message, self.session_id)

        # 2. 构建 system prompt（注入记忆 + 画像 + 策略）
        system = self.build_system_prompt(context)

        # 3. Agent 推理循环（支持多轮工具调用）
        while True:
            response = await self.llm.messages.create(
                model="claude-sonnet-4-20250514",
                system=system,
                messages=self.conversation,
                tools=[t.schema() for t in self.tools],
                stream=True,
            )

            tool_calls = []
            async for event in response:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield event.delta.text
                # ... 处理工具调用

            if tool_calls:
                # 执行工具 → 将结果反馈给 LLM → 继续循环
                ...
                continue
            break

        # 4. 异步更新记忆（不阻塞响应）
        asyncio.create_task(self.memory.post_interaction_update(...))
```

## 6.3 导师交互模式

| 模式 | 导师行为 | 触发条件 |
|------|----------|----------|
| **答疑** | 直接回答但追问诊断理解偏差 | 学生提问 |
| **苏格拉底** | 不给答案，用问题引导思考 | 做练习时、概念性问题 |
| **主动关怀** | 主动发消息关心学习状态 | 学习中断、连续做对/做错 |
| **复习** | 基于遗忘曲线提醒复习 | 定时检查 |
| **项目导师** | Review 代码、引导定位问题 | 做项目时 |

## 6.4 主动探索引擎

```python
class ProactiveExplorer:
    """后台异步运行的主动探索引擎"""

    async def on_content_ingested(self, source_id, student_id):
        """新内容摄入后：消化 → 关联 → 评估相关性 → 推荐"""
        concepts = await self.extract_concepts(source_id)
        links = await self.link_to_knowledge_graph(concepts)
        relevance = await self.assess_relevance(concepts, profile)
        if relevance.score > 0.7:
            await self.create_proactive_message(...)

    async def daily_review(self, student_id):
        """每日巡检：薄弱点 → 搜索补强材料 → 间隔重复"""
        ...

    async def discover_cross_source_links(self, concept_id):
        """跨源关联发现：新概念入库时检查语义相似但不同来源的概念"""
        ...
```

## 6.5 代码 Lab 运行环境

- **MVP**：Monaco Editor 前端 + Docker 沙箱后端执行
- **成熟期**：Sandpack 或 WebContainer 浏览器内环境

## 6.6 视频嵌入播放

```typescript
// YouTube: IFrame Player API
<iframe src={`https://www.youtube.com/embed/${videoId}?enablejsapi=1`} />

// Bilibili: 嵌入播放器
<iframe src={`//player.bilibili.com/player.html?bvid=${bvid}&page=1`} />

// 关键能力：视频进度与教案联动
```

---

# 第七部分：数据模型

```sql
-- 用户 + 学生画像
users (id, email, name, student_profile JSONB, created_at)

-- 内容来源
sources (id, type, url, title, raw_content, metadata JSONB, status, created_by, created_at)

-- 课程
courses (id, title, description, source_ids UUID[], created_by, created_at)

-- 课程章节
sections (id, course_id, title, order_index, source_id, source_start, source_end, content JSONB, difficulty)

-- 知识点 / 概念图谱
concepts (id, name, description, category, prerequisites UUID[], embedding vector(1536))

-- 概念 ↔ 来源关联
concept_sources (concept_id, source_id, context TEXT)

-- 内容块（RAG 检索）
content_chunks (id, source_id, section_id, text, embedding vector(1536), metadata JSONB)

-- Agent 情节记忆
episodic_memories (id, student_id, summary, embedding vector(1536), importance FLOAT,
                   tags TEXT[], interaction_type, created_at)

-- Agent 元认知记忆
teaching_logs (id, student_id, strategy_used, student_response, outcome, concept_id, created_at)

-- 进度追踪
concept_mastery (id, student_id, concept_id, mastery_level FLOAT, attempts INT,
                 last_correct BOOL, next_review_at TIMESTAMPTZ, updated_at)

-- Lab
labs (id, section_id, title, description, difficulty, starter_code, solution, test_cases JSONB, hints JSONB)

-- 习题
exercises (id, section_id, type, question, options JSONB, answer, explanation, difficulty, concepts UUID[])

-- 学习记录
learning_records (id, user_id, course_id, section_id, type, data JSONB, created_at)

-- 对话历史
conversations (id, user_id, course_id, mode, messages JSONB, created_at, updated_at)
```

---

# 第八部分：商业模式与 PMF 验证

## 8.1 定价策略

| 层级 | 价格 | 功能 | 逻辑 |
|------|------|------|------|
| **免费版** | $0 | 3 个内容源、10 次 AI/天、基础画像 | 有机增长靠免费版 |
| **Pro** | $9.99/月 ($79/年) | 无限源、无限 AI、高级画像、间隔重复 | Khanmigo($4) 和 Duolingo Max($30) 之间 |
| **Teams/B2B** | $15-35/学生/年 | 管理后台、班级分析、批量内容管理 | 参考 Khanmigo 学区定价 |

## 8.2 LLM 成本估算

- 20 次 AI 交互/活跃用户/天，~800 token/次
- 70/20/10 模型路由（预算模型/Sonnet/Opus）
- 估算：$0.30-1.50/活跃用户/月
- $9.99 订阅价格下 AI 成本毛利率 70-85%

## 8.3 市场规模

- **TAM**（全球 e-learning）：2025 年 $3,000-3,700 亿，2030 年 $6,500-8,500 亿
- **SAM**（AI in education）：2025 年 $60-80 亿，2030 年 $300-500 亿
- **SOM**（AI 自适应辅导）：2025 年 $20-50 亿

## 8.4 PMF 验证指标

| 指标 | 目标 | 参考 |
|------|------|------|
| DAU（北极星指标） | 持续增长 | Duolingo 以 DAU 为核心 |
| DAU/MAU 比率 | >20% | 教育平均 10-15% |
| Day 7 留存 | >40% | |
| Day 30 留存 | >5% | 教育平均 2.1% |
| 免费转付费 | >5% | |
| 有机增长率 | >50% | |
| 首次价值感知时间 | <5 分钟 | |

## 8.5 GTM 策略

1. 聚焦编程/CS 教育（LLM 亲和度高、付费意愿强）
2. 合作 5-10 个教育类 YouTuber/B站 UP 主做 beta 测试
3. 开源部分组件（学生画像框架、间隔重复引擎）建立信任
4. 根据用户需求扩展到数据科学、语言学习、STEM
5. 有可量化学习效果后开始学校/机构试点

---

# 第九部分：产品路线图

## Phase 1: MVP（第 1-9 周）

**核心：单内容源 + 单 Agent + 基础记忆**

- [ ] FastAPI 项目 + Next.js 项目 + Docker Compose
- [ ] YouTube 字幕提取 + LLM 内容分析管线
- [ ] 导师 Agent 核心循环（Claude API + 苏格拉底式引导）
- [ ] 学生画像 v1（JSON + Pydantic + 对话推断更新）
- [ ] 记忆体系 v1（工作记忆 + 画像记忆 + 基础进度记忆）
- [ ] 基础 RAG（pgvector + 内容检索）
- [ ] 冷启动：5-10 题自适应诊断评估
- [ ] 前端：课程创建 + 视频播放 + 导师对话（SSE 流式）
- [ ] 基础间隔重复

**成功标准**：100 beta 用户，Day 7 留存 >40%

## Phase 2: 内容扩展 + 游戏化 + 记忆深化（第 3-6 个月）

- [ ] 5 种内容源全部上线（YouTube/Bilibili/PDF/MD/URL）
- [ ] **游戏化 v1**：连续天数、每日微目标、进度可视化
- [ ] 记忆体系 v2：情节记忆 + 内容记忆 + 元认知记忆
- [ ] 主动探索引擎（新内容消化 + 跨源关联 + 定时巡检）
- [ ] 贝叶斯知识追踪（BKT）升级进度记忆
- [ ] 知识图谱 v1
- [ ] 基础分析仪表盘

**成功标准**：1,000 活跃用户，DAU/MAU >15%

## Phase 3: 增长 + 变现（第 6-9 个月）

- [ ] 付费版上线
- [ ] 多 Agent 架构（课程 Agent + Lab Agent + 评估 Agent）
- [ ] Lab + 习题生成 + Docker 代码沙箱
- [ ] 社交功能（共享学习路径、学习小组）
- [ ] 教育者工具（内容策展、学生进度视图）
- [ ] B2B 学校/机构试点

**成功标准**：$10K MRR，5,000 活跃用户，付费转化 >5%

## Phase 4: 平台化（第 9-18 个月）

- [ ] 移动端（iOS/Android）
- [ ] 课程市场（用户创建和分享课程）
- [ ] 高级神经知识追踪（DKT）
- [ ] 语音辅导
- [ ] API / LMS 集成（Canvas、Moodle）
- [ ] 企业/培训版
- [ ] 区域定价

**成功标准**：$100K MRR，50,000 活跃用户，平台网络效应显现

---

# 第十部分：风险分析与应对策略

## 10.1 产品风险

| 风险 | 严重性 | 应对策略 |
|------|--------|----------|
| Day 30 留存极低（教育类平均 2.1%） | 🔴 致命 | Phase 2 优先实现游戏化；参考 Duolingo 习惯机制 |
| 冷启动体验差（新用户无画像） | 🟠 高 | 自适应诊断 + 人口先验 + 降级体验独立优秀 |
| LLM 幻觉导致错误教学 | 🟠 高 | 所有回答基于 RAG 检索+来源引用；内容质量自检 |
| Agent 记忆不准确（画像推断错误） | 🟡 中 | 渐进式置信（1次记录→3次可能→5次确认→主动验证） |
| 内容摄入质量参差（PDF 排版、无字幕视频） | 🟡 中 | 质量评分 + fallback 策略（如 Whisper 转录） |

## 10.2 技术风险

| 风险 | 应对策略 |
|------|----------|
| LLM API 成本超预期 | 模型路由（70% 预算模型）+ 缓存 + 响应压缩 |
| 上下文窗口限制 | 分层记忆架构 + 精准检索代替全量加载 |
| 长视频处理超时 | 分片处理 + Celery 异步队列 + 进度条反馈 |
| 向量搜索性能瓶颈 | pgvector 索引优化 + 缓存热门查询 |

## 10.3 市场风险

| 风险 | 应对策略 |
|------|----------|
| Google/OpenAI 直接进入教育市场 | 护城河：长期学生画像数据 + 内容网络效应 + 社区 |
| EdTech 融资环境持续低迷 | 资本效率优先；早期证明单位经济 |
| 监管（EU AI Act 教育高风险） | 从 Day 1 做 privacy-first 架构；保留审计轨迹 |
| 中国市场硬件垄断 | 定位成人/职业学习者 + 海外华人 + Bilibili 差异化 |

## 10.4 竞争风险

| 风险 | 应对策略 |
|------|----------|
| NotebookLM 加入学习记忆 | 先发优势 + 更深的教学设计（Lab/习题/项目） |
| Khanmigo 开放内容来源 | 多源摄入 + 通用型定位 vs K-12 聚焦 |
| Quizlet 教训（AI 包装层无护城河） | 三层护城河：画像数据 + 内容网络 + 社区 |

---

# 附录

## A. 学术研究支持

1. **哈佛 2025 RCT**（Nature Scientific Reports）：AI 辅导在学习效果和时间效率上优于课堂主动学习
2. **Stanford Tutor CoPilot**：使用 AI 辅助的学生数学通过率高 4 个百分点（新手教师高 9 个百分点）
3. **GenMentor (WWW 2025)**：LLM 多 Agent 框架实现技能识别 + 学习路径调度 + 内容个性化
4. **LPITutor (2025)**：RAG + 领域索引实现 86% 回答准确率
5. **认知外包警示**：研究发现被动接受 AI 输出会导致记忆力下降，强化了苏格拉底式方法论的重要性

## B. 项目结构

```
learnmentor/
├── frontend/                      # Next.js
│   ├── app/                       # App Router 页面
│   ├── components/                # VideoPlayer, MentorChat, CodeEditor, KnowledgeGraph
│   └── lib/                       # API 客户端
├── backend/                       # Python / FastAPI
│   ├── app/
│   │   ├── main.py
│   │   ├── api/routes/            # courses, chat, labs, exercises, sources
│   │   ├── agent/                 # mentor, course_agent, lab_agent, eval_agent, explorer
│   │   │   └── prompts/           # System prompt 模板
│   │   ├── tools/                 # extractors/, search, code_runner, knowledge, profile
│   │   ├── memory/                # manager, episodic, progress, metacognitive
│   │   ├── models/                # Pydantic models
│   │   ├── db/                    # SQLAlchemy + Alembic
│   │   └── services/              # embedding, llm, tasks
│   └── tests/
├── sandbox/                       # Docker 沙箱镜像
├── docker-compose.yml
└── README.md
```

## C. 关键依赖

```
# Backend
fastapi, uvicorn, sse-starlette, anthropic, sqlalchemy[asyncio], asyncpg,
alembic, pgvector, youtube-transcript-api, pymupdf, readability-lxml,
httpx, openai (embedding), celery[redis], redis, docker, pydantic

# Frontend
next, react, typescript, tailwindcss, @shadcn/ui, monaco-editor, d3
```

## D. 成本估算（个人使用阶段）

| 项目 | 月成本 |
|------|--------|
| LLM API（Claude Sonnet 为主，Haiku 辅助） | $20-50 |
| Embedding API（text-embedding-3-small） | $1-5 |
| 服务器（本地 Docker 或小型 VPS） | $0-20 |
| **总计** | **$20-75/月** |

## E. 参考竞品链接

- [Google NotebookLM](https://notebooklm.google.com)
- [Khan Academy Khanmigo](https://www.khanmigo.ai)
- [Duolingo](https://www.duolingo.com)
- [Coursera Coach](https://blog.coursera.org)
- [Synthesis Tutor](https://www.synthesis.com/tutor)
- [Speak](https://www.speak.com)
- [MagicSchool AI](https://www.magicschool.ai)
- [Oboe](https://oboe.so)
- [Squirrel AI 松鼠AI](https://squirrelai.com)

---

*LearnMentor 产品设计手册 v2.0*
*技术栈：Next.js + Python (FastAPI) + PostgreSQL/pgvector + Claude API*
*最后更新：2025*
