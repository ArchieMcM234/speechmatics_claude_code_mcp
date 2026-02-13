"""Speechmatics Batch API transcriber wrapper."""

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from speechmatics.batch import AsyncClient, TranscriptionConfig, OperatingPoint

# Load .env file from the same directory as this script
load_dotenv(Path(__file__).parent / ".env")
from httpx import HTTPStatusError


@dataclass
class TranscriptionResult:
    """Result of a transcription job."""
    file_path: str
    transcript: str
    words: list[dict] | None
    duration_seconds: float
    accuracy: str
    diarization: bool
    status: str  # "success" or "error"
    error_message: str | None = None
    job_id: str | None = None


class SpeechmaticsTranscriber:
    """Wrapper for Speechmatics Batch API."""

    def __init__(self, api_key: str | None = None):
        """Initialize the transcriber.

        Args:
            api_key: Speechmatics API key. If None, reads from SPEECHMATICS_API_KEY env var.
        """
        self.api_key = api_key or os.environ.get("SPEECHMATICS_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Speechmatics API key not provided. "
                "Set SPEECHMATICS_API_KEY environment variable or pass api_key parameter."
            )

    async def transcribe(
        self,
        file_path: str,
        accuracy: str = "standard",
        language: str = "en",
        duration_seconds: float | None = None,
        diarize: bool = False
    ) -> TranscriptionResult:
        """Transcribe a single audio/video file.

        Args:
            file_path: Path to the media file
            accuracy: "standard" or "enhanced"
            language: Language code (default: "en")
            duration_seconds: Pre-computed duration (optional, for efficiency)
            diarize: Enable speaker diarization (default: False)

        Returns:
            TranscriptionResult with transcript and metadata
        """
        if not os.path.exists(file_path):
            return TranscriptionResult(
                file_path=file_path,
                transcript="",
                words=None,
                duration_seconds=0,
                accuracy=accuracy,
                diarization=diarize,
                status="error",
                error_message=f"File not found: {file_path}"
            )

        client = AsyncClient(api_key=self.api_key)
        try:
            op = OperatingPoint.ENHANCED if accuracy == "enhanced" else OperatingPoint.STANDARD
            config = TranscriptionConfig(
                language=language,
                operating_point=op,
                diarization="speaker" if diarize else None
            )

            job = await client.submit_job(
                file_path,
                transcription_config=config
            )

            result = await client.wait_for_completion(job.id)

            # Extract transcript text and words
            transcript_text = result.transcript_text if hasattr(result, 'transcript_text') else ""
            words = self._extract_words(result)

            return TranscriptionResult(
                file_path=file_path,
                transcript=transcript_text,
                words=words,
                duration_seconds=duration_seconds or 0,
                accuracy=accuracy,
                diarization=diarize,
                status="success",
                job_id=job.id
            )

        except HTTPStatusError as e:
            error_msg = self._handle_http_error(e)
            return TranscriptionResult(
                file_path=file_path,
                transcript="",
                words=None,
                duration_seconds=duration_seconds or 0,
                accuracy=accuracy,
                diarization=diarize,
                status="error",
                error_message=error_msg
            )
        except Exception as e:
            return TranscriptionResult(
                file_path=file_path,
                transcript="",
                words=None,
                duration_seconds=duration_seconds or 0,
                accuracy=accuracy,
                diarization=diarize,
                status="error",
                error_message=str(e)
            )
        finally:
            await client.close()

    def _extract_words(self, result) -> list[dict] | None:
        """Extract word-level timing from API result."""
        # Try to access results attribute
        if not hasattr(result, 'results'):
            return None

        words = []
        for item in result.results:
            if getattr(item, 'type', None) == 'word':
                alternatives = getattr(item, 'alternatives', [])
                if alternatives:
                    alt = alternatives[0]
                    words.append({
                        "word": getattr(alt, 'content', ''),
                        "start": getattr(item, 'start_time', 0),
                        "end": getattr(item, 'end_time', 0),
                        "confidence": getattr(alt, 'confidence', 0)
                    })

        return words if words else None

    def _handle_http_error(self, error: HTTPStatusError) -> str:
        """Convert HTTP error to user-friendly message."""
        status = error.response.status_code

        if status == 429:
            return "Rate limited by Speechmatics API. Please wait and try again."
        elif status == 403:
            return "API quota exceeded or invalid API key. Check your Speechmatics account."
        elif status == 401:
            return "Invalid Speechmatics API key."
        elif status == 400:
            try:
                detail = error.response.json().get("detail", str(error))
            except Exception:
                detail = str(error)
            return f"Invalid request: {detail}"
        else:
            return f"API error ({status}): {error}"

    async def transcribe_batch(
        self,
        files: list[tuple[str, float]],  # List of (file_path, duration) tuples
        accuracy: str = "standard",
        language: str = "en",
        max_concurrent: int = 10,
        progress_callback: Callable | None = None,
        diarize: bool = False
    ) -> list[TranscriptionResult]:
        """Transcribe multiple files with concurrency control.

        Args:
            files: List of (file_path, duration_seconds) tuples
            accuracy: "standard" or "enhanced"
            language: Language code
            max_concurrent: Maximum concurrent transcription jobs
            progress_callback: Optional callback(completed, total, current_file)
            diarize: Enable speaker diarization (default: False)

        Returns:
            List of TranscriptionResult objects
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        completed = 0
        total = len(files)

        async def transcribe_with_limit(file_path: str, duration: float) -> TranscriptionResult:
            nonlocal completed
            async with semaphore:
                result = await self.transcribe(
                    file_path,
                    accuracy=accuracy,
                    language=language,
                    duration_seconds=duration,
                    diarize=diarize
                )
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, file_path)
                return result

        tasks = [
            transcribe_with_limit(file_path, duration)
            for file_path, duration in files
        ]

        return await asyncio.gather(*tasks)

    async def get_usage(self) -> dict:
        """Get API usage statistics.

        Returns:
            Dict with usage information
        """
        client = AsyncClient(api_key=self.api_key)
        try:
            # Get job list to count jobs this month
            jobs = await client.list_jobs()

            # Count jobs from current month
            now = datetime.utcnow()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            jobs_this_month = 0
            total_duration_seconds = 0

            for job in jobs:
                created = getattr(job, 'created_at', None)
                if created:
                    try:
                        if isinstance(created, str):
                            job_date = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        else:
                            job_date = created
                        if job_date.replace(tzinfo=None) >= month_start:
                            jobs_this_month += 1
                            duration = getattr(job, 'duration', 0) or 0
                            total_duration_seconds += duration
                    except (ValueError, TypeError):
                        pass

            hours_used = total_duration_seconds / 3600

            return {
                "hours_used_this_month": round(hours_used, 2),
                "monthly_limit_hours": None,  # Not available from API
                "hours_remaining": None,  # Not available from API
                "jobs_this_month": jobs_this_month
            }
        except Exception as e:
            return {
                "error": str(e),
                "hours_used_this_month": None,
                "monthly_limit_hours": None,
                "hours_remaining": None,
                "jobs_this_month": None
            }
        finally:
            await client.close()
