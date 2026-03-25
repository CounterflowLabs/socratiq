# 🧠 LearnMentor

把 B 站编程教程变成交互式课程。

导入视频合集 → AI 自动生成结构化课文、流程图、代码 Lab、诊断测评 → 苏格拉底式 AI 导师辅导学习。

## ✨ 特性

- **视频 → 课程**：导入 B 站/YouTube 编程教程合集，自动生成完整交互式课程
- **结构化课文**：视频字幕智能重组为书面语 + 流程图 + 步骤分解 + 代码高亮
- **Lab 练习**：自动生成代码骨架（TODO）+ 测试，像 MIT 课程一样动手写代码
- **AI 导师**：苏格拉底式教学，追问引导而不是直接给答案
- **学习诊断**：基于课程内容自动出题，测试你真正掌握了多少
- **间隔复习**：SM-2 算法安排复习时间，学了不会忘
- **知识图谱**：D3.js 可视化概念关系和掌握度
- **完全本地**：支持 Ollama 本地模型，数据不出你的电脑

## 🚀 快速开始

### Docker Compose（推荐）

```bash
git clone https://github.com/xxx/learnmentor.git
cd learnmentor
cp .env.example .env
docker compose up
```

打开 http://localhost:3000 ，按引导配置 AI 模型即可开始。

### 本地开发

```bash
# 启动数据库
docker compose up -d db redis

# 后端
cd backend
uv sync
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --reload-dir app --port 8000

# 前端
cd frontend
npm install
npm run dev
```

## 📋 系统要求

- Docker + Docker Compose
- **使用 Ollama 本地模型**：8GB+ 内存（推荐 16GB）
- **使用云端 API**：任意 OpenAI / Anthropic API Key，无本地计算要求

## 🤖 支持的 AI 模型

| Provider | 示例模型 | 备注 |
|----------|---------|------|
| Ollama（本地） | qwen2.5, llama3, deepseek-v2 | 免费，数据私有 |
| OpenAI | gpt-4o, gpt-4o-mini | 需 API Key |
| Anthropic | Claude Sonnet, Claude Haiku | 需 API Key |
| OpenAI 兼容 | DeepSeek, 通义千问, Moonshot | 第三方 API |

## 📁 项目结构

```
learnmentor/
├── backend/          # FastAPI + Python
│   ├── app/
│   │   ├── api/      # API 路由
│   │   ├── agent/    # MentorAgent + 工具
│   │   ├── services/ # 核心服务
│   │   └── db/       # 数据库模型
│   └── tests/
├── frontend/         # Next.js + React + TypeScript
│   └── src/
│       ├── app/      # 页面
│       ├── components/ # 组件
│       └── lib/      # API 客户端 + 工具
└── docker-compose.yml
```

## 🗺 路线图

- [x] v0.1.0 — 视频 → 交互式课程（当前）
- [ ] v0.2.0 — AI 主动探索补充材料 + 课程导出为静态网站
- [ ] v0.3.0 — 代码沙箱执行 + 笔记系统 + 学习统计
- [ ] v0.4.0 — 插件系统 + 课程社区分享

## 🤝 贡献

欢迎 PR 和 Issue！

## 📄 License

[MIT](LICENSE)
