"""Whisper ASR service — audio-to-text fallback when subtitles are unavailable."""
import asyncio
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

class WhisperService:
    """Audio-to-text transcription via Whisper-compatible API or local model."""

    def __init__(
        self,
        mode: str = "api",
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
        try:
            if self._mode == "api":
                return await self._transcribe_api(audio_path)
            else:
                return await self._transcribe_local(audio_path)
        finally:
            audio_path.unlink(missing_ok=True)

    async def _download_audio(self, url: str) -> Path:
        """Download audio via yt-dlp as mp3 (compressed, fits API size limits)."""
        tmp_dir = tempfile.mkdtemp(prefix="socratiq_asr_")
        output_path = Path(tmp_dir) / "audio.mp3"
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "5",
            "--no-playlist", "-o", str(output_path), url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp audio download failed (exit {proc.returncode}): {stderr.decode()[:500]}")
        if not output_path.exists():
            wav_files = list(Path(tmp_dir).glob("audio.*"))
            if wav_files:
                output_path = wav_files[0]
            else:
                raise RuntimeError("yt-dlp produced no output file")
        try:
            size = output_path.stat().st_size
        except OSError:
            size = "?"
        logger.info(f"Downloaded audio: {output_path} ({size} bytes)")
        return output_path

    async def _transcribe_api(self, audio_path: Path) -> list[dict]:
        """Transcribe via Whisper-compatible API (Groq, OpenAI, SiliconFlow, etc.)."""
        import openai
        client = openai.AsyncOpenAI(
            api_key=self._api_key or None,
            base_url=self._api_base_url or None,
        )
        response = await client.audio.transcriptions.create(
            model=self._api_model, file=audio_path,
            response_format="verbose_json", timestamp_granularities=["segment"],
        )
        segments = []
        for seg in response.segments or []:
            segments.append({"text": seg.text.strip(), "start": seg.start, "end": seg.end})
        logger.info(f"Whisper API transcribed {len(segments)} segments")
        return segments

    async def _transcribe_local(self, audio_path: Path) -> list[dict]:
        """Transcribe via local whisper model."""
        def _run():
            import whisper
            model = whisper.load_model(self._model)
            return model.transcribe(str(audio_path))
        result = await asyncio.to_thread(_run)
        segments = []
        for seg in result.get("segments", []):
            segments.append({"text": seg["text"].strip(), "start": seg["start"], "end": seg["end"]})
        logger.info(f"Local Whisper transcribed {len(segments)} segments")
        return segments
