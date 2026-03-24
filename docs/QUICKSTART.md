# LearnMentor 开发快速启动指南

## 从 Cowork 设计原型到 Claude Code 开发的丝滑过渡

---

## Step 0: 安装 Superpowers 插件

Superpowers 是一个 Claude Code 开发方法论框架，核心流程：

```
头脑风暴 → 设计文档 → Git Worktree 隔离 → 拆分计划 → Subagent 并行开发 → 代码审查 → 合并
```

### 安装方式（任选其一）

```bash
# 方式 1：从 superpowers marketplace 安装（推荐）
# 在 Claude Code 中执行：
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace

# 方式 2：从官方目录安装
/plugin install superpowers@claude-plugins-official

# 安装后重启 Claude Code
```

### Superpowers 核心工作流

| 阶段 | Skill | 做什么 |
|------|-------|--------|
| 1 | **brainstorming** | 在写代码前先讨论需求、探索方案、生成设计文档 |
| 2 | **using-git-worktrees** | 设计确认后创建隔离工作分支，验证测试基线 |
| 3 | **writing-plans** | 把设计拆成 2-5 分钟的小任务，每个任务有精确文件路径和验证步骤 |
| 4 | **subagent-driven-development** | 每个任务派发独立 subagent 执行，完成后两阶段审查（规格+质量） |
| 5 | **finishing-a-development-branch** | 验证测试通过 → merge/PR/保留/丢弃 → 清理 worktree |

关键原则：**先设计再编码、TDD (红-绿-重构)、YAGNI、每个任务隔离执行**

---

## Step 1: 创建项目

```bash
# 创建项目目录
mkdir learnmentor && cd learnmentor
git init

# 把 Cowork 生成的文件拷贝过来
# CLAUDE.md 已经为你准备好了（见同目录下的 CLAUDE.md）
cp /path/to/learnmentor-bootstrap/CLAUDE.md ./CLAUDE.md
```

---

## Step 2: 启动 Claude Code + Superpowers 开发

```bash
# 在项目根目录启动 Claude Code
claude
```

### 推荐的第一条指令

直接把下面这段话贴给 Claude Code，它会按 Superpowers 流程启动：

```
我要开发 LearnMentor —— 一个 AI 驱动的自适应学习系统。

请先阅读 CLAUDE.md 了解项目全貌。

我们现在要开始 MVP Phase 1 开发。我已经有完整的产品方案和交互原型。
请按 superpowers 流程来：先 brainstorm 确认技术方案，再拆任务，再逐个执行。

MVP 的第一个里程碑是：
1. Docker Compose 基础设施 (PostgreSQL + pgvector + Redis)
2. FastAPI 后端骨架 + 数据库 migration
3. Next.js 前端骨架 + 基础路由
4. YouTube 字幕提取管线
5. MentorAgent 核心循环 (Claude API tool use)

让我们开始 brainstorming。
```

---

## Step 3: Superpowers 流程详解

### 阶段 1: Brainstorming（它会自动触发）

Claude Code 不会直接写代码。它会：
- 提问澄清需求细节
- 探索技术方案替代选项
- 逐段展示设计文档让你确认
- 最终保存一份 `design.md` 设计文档

**你的角色**：回答问题、确认或修改设计

### 阶段 2: Git Worktree 隔离

确认设计后，它会：
- 创建 `worktree/feature-xxx` 分支
- 运行项目初始化
- 验证测试基线是干净的

### 阶段 3: Writing Plans

把设计文档拆成 **2-5 分钟**的小任务：
```
Task 1: 创建 docker-compose.yml (PostgreSQL + pgvector + Redis)
  - 文件: docker-compose.yml, docker-compose.dev.yml
  - 验证: docker compose up -d && docker compose ps

Task 2: 初始化 FastAPI 项目结构
  - 文件: backend/app/main.py, pyproject.toml, ...
  - 验证: pytest passes, uvicorn starts

...
```

### 阶段 4: Subagent-Driven Development

**核心机制**：每个任务派一个独立 subagent（新鲜上下文）去执行

```
主 Agent ──→ Subagent 1 ──→ Task 1 ──→ 两阶段审查 ✓
         ──→ Subagent 2 ──→ Task 2 ──→ 两阶段审查 ✓
         ──→ ...
```

两阶段审查：
1. **规格合规性**：代码是否满足设计文档要求？
2. **代码质量**：命名、结构、测试覆盖、边界情况？

### 阶段 5: 完成分支

所有任务完成后：
- 运行全部测试
- 提供选择：merge 到 main / 创建 PR / 保留 / 丢弃

---

## 推荐的开发节奏

### Week 1-2: 基础设施 + 内容摄入

```
Session 1: Docker Compose + DB schema + migrations
Session 2: FastAPI 骨架 + API routes 框架
Session 3: Next.js 骨架 + 基础路由 + Tailwind + shadcn/ui
Session 4: YouTube 字幕提取 ContentExtractor
Session 5: LLM 内容分析管线 (概念提取 + 难度评估)
```

### Week 3-4: Agent 核心

```
Session 6: MentorAgent 核心循环 (Claude tool use)
Session 7: 学生画像 v1 (Pydantic model + JSONB)
Session 8: 记忆体系 v1 (MemoryManager + 工作记忆 + 画像记忆)
Session 9: RAG 管线 (pgvector + embedding + 检索)
Session 10: 冷启动自适应诊断
```

### Week 5-7: 前端 + 联调

```
Session 11: 导入页 + 视频分析 loading
Session 12: 自适应评估页
Session 13: 学习路径页 + 课程创建
Session 14: 视频学习页 (VideoPlayer + MentorChat)
Session 15: SSE 流式聊天联调
Session 16: 练习 + 反馈页
Session 17: Dashboard + 间隔重复
```

### Week 8-9: 打磨 + 测试

```
Session 18: 端到端测试 + bug 修复
Session 19: 性能优化 + 错误处理
Session 20: 部署配置 + CI/CD
```

---

## 关键参考文件

| 文件 | 位置 | 用途 |
|------|------|------|
| CLAUDE.md | `./CLAUDE.md` | Claude Code 项目上下文（已准备好） |
| 产品设计手册 | 你的文档文件夹 | 完整产品方案 v2.0 |
| 交互原型 | `LearnMentor-Prototype.jsx` | 可运行的 React 原型（Cowork 产出） |
| 系统设计文档 | 你的文档文件夹 | 详细系统架构设计 |

---

## Tips

1. **每次 Session 聚焦一个功能模块**，不要一次做太多
2. **用 superpowers 的 brainstorming 代替直接写代码**，前期设计省后期返工
3. **TDD**：先写测试再写实现，superpowers 会强制执行
4. **Git worktree 隔离**：每个功能在独立分支开发，main 始终可用
5. **Subagent 并行**：大任务拆小后并行执行，大幅提速
6. **经常 commit**：superpowers 的 finishing-a-development-branch 会帮你管理
