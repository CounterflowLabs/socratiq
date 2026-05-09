"""Whisper ASR service — audio-to-text fallback when subtitles are unavailable."""

import asyncio
import math
import logging
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

MAX_API_AUDIO_BYTES = 24 * 1024 * 1024
TARGET_API_CHUNK_BYTES = 20 * 1024 * 1024
API_AUDIO_BITRATE = "32k"
API_AUDIO_SAMPLE_RATE = "16000"

LOCAL_MODE = "local"
WHISPERCPP_MODE = "whispercpp"
OPENAI_COMPAT_MODES = {"api", "openai_compat", "groq", "openai", "siliconflow"}


class WhisperService:
    """Audio-to-text transcription via a Whisper-compatible HTTP API or local model.

    `mode` selects the transport:
      - ``local`` — in-process ``openai-whisper`` library (requires the
        optional ``[whisper]`` extra installed in the runtime).
      - ``whispercpp`` — call a host-run ``whisper.cpp`` server's
        ``POST <base>/inference`` endpoint (no auth header sent).
      - any of ``api`` / ``openai_compat`` / ``groq`` / ``openai`` /
        ``siliconflow`` — call ``POST <base>/audio/transcriptions`` with a
        Bearer token, OpenAI-compatible multipart upload.
    """

    def __init__(
        self,
        mode: str = "openai_compat",
        model: str = "base",
        api_key: str = "",
        api_base_url: str = "https://api.groq.com/openai/v1",
        api_model: str = "whisper-large-v3",
    ):
        self._mode = mode
        self._model = model
        self._api_key = api_key
        self._api_base_url = api_base_url
        self._api_model = api_model

    async def transcribe(self, url: str) -> list[dict]:
        """Download audio from URL and transcribe to timed segments."""
        audio_path = await self._download_audio(url)
        cleanup_paths: list[Path] = []
        try:
            if self._mode == LOCAL_MODE:
                return await self._transcribe_local(audio_path)
            segments, extra_paths = await self._transcribe_remote(audio_path)
            cleanup_paths.extend(extra_paths)
            return segments
        finally:
            audio_path.unlink(missing_ok=True)
            for path in cleanup_paths:
                path.unlink(missing_ok=True)
            try:
                audio_path.parent.rmdir()
            except OSError:
                pass

    async def _download_audio(self, url: str) -> Path:
        """Download audio via yt-dlp as mp3 to reduce upload size."""
        tmp_dir = tempfile.mkdtemp(prefix="socratiq_asr_")
        output_path = Path(tmp_dir) / "audio.mp3"
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "5",
            "--no-playlist",
            "-o",
            str(output_path),
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"yt-dlp audio download failed (exit {proc.returncode}): {stderr.decode()[:500]}"
            )
        if not output_path.exists():
            audio_files = list(Path(tmp_dir).glob("audio.*"))
            if audio_files:
                output_path = audio_files[0]
            else:
                raise RuntimeError("yt-dlp produced no output file")
        try:
            size = output_path.stat().st_size
        except OSError:
            size = "?"
        logger.info("Downloaded audio: %s (%s bytes)", output_path, size)
        return output_path

    async def _transcribe_remote(self, audio_path: Path) -> tuple[list[dict], list[Path]]:
        """Transcribe via a Whisper-compatible HTTP service, chunking oversized files."""
        url, extra_data, headers = self._build_remote_request()

        upload_paths: list[tuple[Path, float]] = [(audio_path, 0.0)]
        cleanup_paths: list[Path] = []

        if audio_path.stat().st_size > MAX_API_AUDIO_BYTES:
            upload_paths, cleanup_paths = await self._prepare_api_chunks(audio_path)

        segments: list[dict] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
            for chunk_path, offset in upload_paths:
                with chunk_path.open("rb") as fp:
                    files = {"file": (chunk_path.name, fp, "audio/mpeg")}
                    response = await client.post(
                        url, headers=headers, data=extra_data, files=files
                    )
                if response.status_code == 413:
                    raise RuntimeError(
                        "Whisper 音频文件仍然过大，已超过转写服务的上传限制。"
                        " 可以换更短的视频，或改用带现成字幕的内容。"
                    )
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"Whisper {self._mode} 转写失败 (HTTP {response.status_code}): "
                        f"{response.text[:500]}"
                    )
                body = response.json()
                for seg in body.get("segments") or []:
                    segments.append(
                        {
                            "text": (seg.get("text") or "").strip(),
                            "start": float(seg["start"]) + offset,
                            "end": float(seg["end"]) + offset,
                        }
                    )

        logger.info(
            "Whisper (%s) transcribed %s segments across %s upload(s)",
            self._mode,
            len(segments),
            len(upload_paths),
        )
        return segments, cleanup_paths

    def _build_remote_request(self) -> tuple[str, dict, dict]:
        """Build (url, form-data, headers) for the configured Whisper mode.

        Returns a fully-qualified URL — base_url is treated as the service root,
        and the per-mode endpoint suffix is appended here.
        """
        base = (self._api_base_url or "").rstrip("/")
        if not base:
            raise RuntimeError("Whisper API Base URL 未配置。")

        if self._mode == WHISPERCPP_MODE:
            return (
                f"{base}/inference",
                {"response_format": "verbose_json"},
                {},
            )

        if self._mode in OPENAI_COMPAT_MODES:
            if not self._api_key:
                raise RuntimeError(
                    "Whisper API 未配置。请在设置页填写 API Key，或切换到本地 Whisper 模式。"
                )
            return (
                f"{base}/audio/transcriptions",
                {
                    "model": self._api_model,
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "segment",
                },
                {"Authorization": f"Bearer {self._api_key}"},
            )

        raise RuntimeError(f"Whisper 未知 mode: {self._mode!r}")

    async def _transcribe_local(self, audio_path: Path) -> list[dict]:
        """Transcribe via local whisper model."""

        def _run():
            import whisper

            model = whisper.load_model(self._model)
            return model.transcribe(str(audio_path))

        result = await asyncio.to_thread(_run)
        segments = []
        for seg in result.get("segments", []):
            segments.append(
                {
                    "text": seg["text"].strip(),
                    "start": seg["start"],
                    "end": seg["end"],
                }
            )
        logger.info("Local Whisper transcribed %s segments", len(segments))
        return segments

    async def _prepare_api_chunks(self, audio_path: Path) -> tuple[list[tuple[Path, float]], list[Path]]:
        """Re-encode and split oversized audio into API-safe chunks."""
        logger.info(
            "Audio exceeds API upload limit (%s bytes), recompressing for chunked upload",
            MAX_API_AUDIO_BYTES,
        )

        compressed_path = audio_path.with_name("audio_api.mp3")
        await self._run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(audio_path),
                "-ac",
                "1",
                "-ar",
                API_AUDIO_SAMPLE_RATE,
                "-b:a",
                API_AUDIO_BITRATE,
                str(compressed_path),
            ],
            "ffmpeg recompress failed",
        )

        cleanup_paths = [compressed_path]
        compressed_size = compressed_path.stat().st_size
        if compressed_size <= MAX_API_AUDIO_BYTES:
            logger.info("Recompressed audio now fits API upload limit: %s bytes", compressed_size)
            return [(compressed_path, 0.0)], cleanup_paths

        duration = await self._probe_duration_seconds(compressed_path)
        chunk_count = max(2, math.ceil(compressed_size / TARGET_API_CHUNK_BYTES))
        chunk_duration = duration / chunk_count
        logger.info(
            "Splitting recompressed audio (%s bytes, %.2fs) into %s chunks (~%.2fs each)",
            compressed_size,
            duration,
            chunk_count,
            chunk_duration,
        )

        chunks: list[tuple[Path, float]] = []
        for index in range(chunk_count):
            start = chunk_duration * index
            remaining = max(0.0, duration - start)
            if remaining <= 0:
                break
            this_duration = min(chunk_duration, remaining)
            chunk_path = audio_path.with_name(f"audio_chunk_{index:02d}.mp3")
            await self._run_ffmpeg(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{start:.3f}",
                    "-t",
                    f"{this_duration:.3f}",
                    "-i",
                    str(compressed_path),
                    "-ac",
                    "1",
                    "-ar",
                    API_AUDIO_SAMPLE_RATE,
                    "-b:a",
                    API_AUDIO_BITRATE,
                    str(chunk_path),
                ],
                f"ffmpeg chunking failed for segment {index}",
            )
            cleanup_paths.append(chunk_path)
            chunk_size = chunk_path.stat().st_size
            if chunk_size > MAX_API_AUDIO_BYTES:
                raise RuntimeError(
                    "音频切分后仍然超过转写服务上传限制，请换更短的视频或改用现成字幕。"
                )
            chunks.append((chunk_path, start))

        return chunks, cleanup_paths

    async def _probe_duration_seconds(self, audio_path: Path) -> float:
        """Read media duration via ffprobe."""
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffprobe duration failed: {stderr.decode()[:300]}")
        try:
            return float(stdout.decode().strip())
        except ValueError as exc:
            raise RuntimeError("无法读取音频时长，无法对 Whisper 上传进行分段。") from exc

    async def _run_ffmpeg(self, args: list[str], error_prefix: str) -> None:
        """Run an ffmpeg subprocess and surface a readable error on failure."""
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"{error_prefix}: {stderr.decode()[:500]}")
