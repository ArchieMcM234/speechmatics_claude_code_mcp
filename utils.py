"""Utility functions for transcription MCP server."""

import json
import os
import subprocess
from pathlib import Path

DEFAULT_FILE_TYPES = ["mp3", "mp4", "wav", "m4a", "webm", "ogg", "flac", "mov", "avi"]


def get_audio_duration(file_path: str) -> float:
    """Get duration in seconds using ffprobe.

    Args:
        file_path: Path to audio/video file

    Returns:
        Duration in seconds

    Raises:
        RuntimeError: If ffprobe fails or duration cannot be determined
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                file_path
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr}")

        data = json.loads(result.stdout)
        duration = data.get("format", {}).get("duration")

        if duration is None:
            raise RuntimeError("Could not determine duration from ffprobe output")

        return float(duration)

    except subprocess.TimeoutExpired:
        raise RuntimeError("ffprobe timed out")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse ffprobe output: {e}")
    except FileNotFoundError:
        raise RuntimeError("ffprobe not found. Please install ffmpeg.")


def format_duration(seconds: float) -> str:
    """Format duration as MM:SS or HH:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def find_media_files(
    directory: str,
    file_types: list[str] | None = None,
    recursive: bool = False
) -> list[str]:
    """Find all media files in directory.

    Args:
        directory: Path to directory to search
        file_types: List of file extensions to include (without dots)
        recursive: Whether to search subdirectories

    Returns:
        List of absolute paths to media files
    """
    if file_types is None:
        file_types = DEFAULT_FILE_TYPES

    # Normalize extensions to lowercase without dots
    extensions = {ext.lower().lstrip('.') for ext in file_types}

    directory_path = Path(directory)
    if not directory_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    if not directory_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    media_files = []

    if recursive:
        pattern_func = directory_path.rglob
    else:
        pattern_func = directory_path.glob

    for ext in extensions:
        # Match both lowercase and uppercase extensions
        for pattern in [f"*.{ext}", f"*.{ext.upper()}"]:
            for file_path in pattern_func(pattern):
                if file_path.is_file():
                    abs_path = str(file_path.resolve())
                    if abs_path not in media_files:
                        media_files.append(abs_path)

    return sorted(media_files)


def find_transcript(media_path: str) -> str | None:
    """Find transcript file for a media file.

    Args:
        media_path: Path to the media file

    Returns:
        Path to transcript file if found, None otherwise
    """
    for ext in [".transcript.txt", ".transcript.json"]:
        transcript_path = media_path + ext
        if os.path.exists(transcript_path):
            return transcript_path
    return None


def get_transcript_path(media_path: str, with_timestamps: bool = False) -> str:
    """Get the transcript output path for a media file.

    Args:
        media_path: Path to the media file
        with_timestamps: Whether timestamps are included

    Returns:
        Path where transcript should be saved
    """
    ext = ".transcript.json" if with_timestamps else ".transcript.txt"
    return media_path + ext


def is_media_file(file_path: str, file_types: list[str] | None = None) -> bool:
    """Check if a file is a supported media file.

    Args:
        file_path: Path to file
        file_types: List of supported extensions

    Returns:
        True if file is a supported media type
    """
    if file_types is None:
        file_types = DEFAULT_FILE_TYPES

    extensions = {ext.lower().lstrip('.') for ext in file_types}
    file_ext = Path(file_path).suffix.lower().lstrip('.')

    return file_ext in extensions
