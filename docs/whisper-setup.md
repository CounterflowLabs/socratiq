# Whisper 转写配置

YouTube / Bilibili 视频没有现成字幕时，后端会回退到 Whisper 把音频转成文字（见 `backend/app/tools/extractors/asr.py`）。
转写是内容摄入管线里最耗时的一环，建议按下面的优先级选方案。

## 优先级一览

| 方案 | 适用场景 | 速度 | 折腾度 |
|------|---------|------|--------|
| 1. 大厂 Whisper API | 默认推荐 | 快 | 低 |
| 2. 宿主机跑 Whisper 服务 | 离线 / 隐私 / 本地优先 | 中 | 中 |
| 3. 装进 backend 镜像 | 不能改宿主环境 | 慢（纯 CPU） | 低 |

---

## 方案 1：大厂 Whisper API（首选）

转写量不大、不在意走外网时，直接用云端 API 体验最好。

| 服务 | API base URL | 模型 | 备注 |
|------|--------------|------|------|
| **Groq** | `https://api.groq.com/openai/v1` | `whisper-large-v3` | 免费额度大、速度极快，**首选** |
| OpenAI | `https://api.openai.com/v1` | `whisper-1` | 稳定，按量计费 |
| SiliconFlow | `https://api.siliconflow.cn/v1` | `FunAudioLLM/SenseVoiceSmall` | 国内可用 |

**配置：** Settings → Whisper 语音识别 → 模式选 `API` → 填 base URL / 模型 / Key → 保存。

---

## 方案 2：宿主机跑 Whisper 服务（推荐的本地方案）

为什么不把 Whisper 装进 backend 镜像（即旧的「local 模式」）？

- **Docker Desktop on Mac 不透传 Metal/GPU**，容器里的 Whisper 只能 CPU 跑，medium 以上慢到不可用
- 模型动辄 1–3 GB，塞进镜像会让镜像体积爆炸，重建一次心痛一次
- 独立服务可以单独重启、调参、给其他工具复用

推荐做法：**宿主机跑一个 OpenAI 兼容的 Whisper 服务**，后端容器通过 `host.docker.internal` 调它，这样既能吃满本机硬件加速，又不需要改 `asr.py` 一行代码（已经是 OpenAI 兼容协议）。

> `docker-compose.yml` 里 `backend` 和 `worker` 已经配了 `extra_hosts: ["host.docker.internal:host-gateway"]`，开箱即用。

### 2A. `speaches`（推荐，开箱即用）

[`speaches`](https://github.com/speaches-ai/speaches)（前身 `faster-whisper-server`）基于 faster-whisper（CTranslate2），原生 OpenAI 兼容，CPU 上用 int8 量化跑得很快，Linux + NVIDIA 还能 GPU 加速。

**Mac / Linux 通用 — 在宿主机另开一个 Docker 容器：**

```bash
# CPU 版本（Mac 唯一可选）
docker run -d --name speaches -p 8001:8000 \
  -v ~/.cache/huggingface:/home/ubuntu/.cache/huggingface \
  ghcr.io/speaches-ai/speaches:latest-cpu

# Linux + NVIDIA：把 latest-cpu 换成 latest-cuda 并加 --gpus all
```

**在 Socratiq 设置页配置：**

- 模式：`API`
- API Base URL：`http://host.docker.internal:8001/v1`
- 模型：`Systran/faster-whisper-base`（或 `…-small` / `…-large-v3`）
- API Key：随便填一串非空字符（speaches 默认不校验）

第一次请求会自动下载模型到 `~/.cache/huggingface`，之后命中本地。

### 2B. `whisper.cpp`（追求 Metal 加速，需要小适配器）

`whisper.cpp` 是 Mac 上 Metal 加速最成熟的实现，但它的 server 默认走 `/inference` 端点，**不完全 OpenAI 兼容**，目前的 `asr.py` 不能直接用。两条出路：

1. 在它前面套一层薄代理，把 `/v1/audio/transcriptions` 转成 `/inference`
2. 给 `WhisperService` 加一个 `whispercpp` mode（约 30 行代码）

如果只是日常开发，速度上 `speaches` 已经够用，不建议折腾这条路。真要上：

```bash
brew install whisper-cpp                     # 或 git clone + make
whisper-cli --download-model base.en         # 下模型
# 启动 server（默认 8080 端口）
whisper-server -m ~/.cache/whisper.cpp/ggml-base.en.bin --port 8001
```

---

## 方案 3：装进 backend 镜像（兜底）

只有在「不能改宿主环境、必须容器自包含」时再走这条。性能差但配置简单。

修改 `backend/Dockerfile`：

```dockerfile
ARG INSTALL_WHISPER=0
ARG WHISPER_MODEL=base
RUN if [ "$INSTALL_WHISPER" = "1" ]; then \
      uv pip install --system -e ".[whisper]" && \
      python -c "import whisper; whisper.load_model('${WHISPER_MODEL}')"; \
    else \
      uv pip install --system -e .; \
    fi
```

`docker-compose.yml` 给 `backend` 和 `worker` 都加：

```yaml
build:
  context: ./backend
  args:
    INSTALL_WHISPER: "1"
    WHISPER_MODEL: "base"
volumes:
  - whispercache:/root/.cache/whisper
```

设置页选 `本地模型` + `base` / `tiny`。**别选 medium 以上**，纯 CPU 跑会超时。

---

## 排错

- **「Whisper API 未配置」**：API mode 但没填 Key（speaches 也要填一个非空字符串）
- **`Connection refused` to `host.docker.internal`**：宿主机的 Whisper 服务没起来，或绑定到了 `127.0.0.1` 而不是 `0.0.0.0`
- **音频文件过大**：`asr.py` 已经会自动重压缩 + 切片到 24 MB 以下，云端 API 仍报 413 时换更短视频
- **转写质量差**：升级到 `large-v3` 模型；中文场景试 SiliconFlow 的 SenseVoice
