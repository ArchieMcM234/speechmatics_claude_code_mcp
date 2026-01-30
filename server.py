"""MCP server for audio/video transcription using Speechmatics."""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env file from the same directory as this script
load_dotenv(Path(__file__).parent / ".env")

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from transcriber import SpeechmaticsTranscriber, TranscriptionResult
from utils import (
    get_audio_duration,
    format_duration,
    find_media_files,
    find_transcript,
    get_transcript_path,
    is_media_file,
    DEFAULT_FILE_TYPES
)

# Initialize MCP server
server = Server("transcription")


def get_transcriber() -> SpeechmaticsTranscriber:
    """Get transcriber instance, loading API key from environment."""
    return SpeechmaticsTranscriber()


def write_transcript_file(
    result: TranscriptionResult,
    with_timestamps: bool = False
) -> str:
    """Write transcript to file.

    Args:
        result: Transcription result
        with_timestamps: Whether to include word-level timestamps

    Returns:
        Path to written transcript file
    """
    output_path = get_transcript_path(result.file_path, with_timestamps)
    source_name = Path(result.file_path).name
    timestamp = datetime.now(timezone.utc).isoformat()

    if with_timestamps:
        # JSON format with word timings
        output = {
            "metadata": {
                "source": source_name,
                "transcribed_at": timestamp,
                "duration_seconds": result.duration_seconds,
                "accuracy": result.accuracy
            },
            "transcript": result.transcript,
            "words": result.words or []
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
    else:
        # Plain text format with header
        duration_str = format_duration(result.duration_seconds) if result.duration_seconds else "unknown"
        header = f"""# Transcribed: {timestamp}
# Source: {source_name}
# Duration: {duration_str}
# Accuracy: {result.accuracy}

"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(header + result.transcript)

    return output_path


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available transcription tools."""
    return [
        Tool(
            name="transcribe_file",
            description="Transcribe a single audio/video file using Speechmatics API",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the media file"
                    },
                    "accuracy": {
                        "type": "string",
                        "enum": ["standard", "enhanced"],
                        "default": "standard",
                        "description": "Transcription accuracy level"
                    },
                    "with_timestamps": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include word-level timestamps (outputs JSON instead of TXT)"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="transcribe_directory",
            description="Transcribe all media files in a directory (parallel processing)",
            inputSchema={
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Path to directory containing media files"
                    },
                    "file_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": DEFAULT_FILE_TYPES,
                        "description": "File extensions to include (without dots)"
                    },
                    "accuracy": {
                        "type": "string",
                        "enum": ["standard", "enhanced"],
                        "default": "standard",
                        "description": "Transcription accuracy level"
                    },
                    "with_timestamps": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include word-level timestamps"
                    },
                    "recursive": {
                        "type": "boolean",
                        "default": False,
                        "description": "Search subdirectories"
                    },
                    "max_concurrent": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Maximum parallel transcription jobs"
                    }
                },
                "required": ["directory"]
            }
        ),
        Tool(
            name="get_transcript",
            description="Read an existing transcript file",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to media file OR transcript file"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="get_usage",
            description="Get Speechmatics API usage statistics for the current month",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""

    if name == "transcribe_file":
        return await handle_transcribe_file(arguments)
    elif name == "transcribe_directory":
        return await handle_transcribe_directory(arguments)
    elif name == "get_transcript":
        return await handle_get_transcript(arguments)
    elif name == "get_usage":
        return await handle_get_usage(arguments)
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def handle_transcribe_file(arguments: dict) -> list[TextContent]:
    """Handle transcribe_file tool call."""
    file_path = arguments["file_path"]
    accuracy = arguments.get("accuracy", "standard")
    with_timestamps = arguments.get("with_timestamps", False)

    # Validate file exists
    if not os.path.exists(file_path):
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error_message": f"File not found: {file_path}"
        }, indent=2))]

    # Get duration
    try:
        duration = get_audio_duration(file_path)
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error_message": f"Could not determine audio duration: {e}"
        }, indent=2))]

    # Transcribe
    try:
        transcriber = get_transcriber()
        result = await transcriber.transcribe(
            file_path,
            accuracy=accuracy,
            duration_seconds=duration
        )

        if result.status == "error":
            return [TextContent(type="text", text=json.dumps({
                "status": "error",
                "error_message": result.error_message
            }, indent=2))]

        # Write transcript file
        transcript_path = write_transcript_file(result, with_timestamps)

        return [TextContent(type="text", text=json.dumps({
            "status": "success",
            "transcript_path": transcript_path,
            "duration_seconds": duration,
            "duration_formatted": format_duration(duration),
            "accuracy": accuracy
        }, indent=2))]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error_message": str(e)
        }, indent=2))]


async def handle_transcribe_directory(arguments: dict) -> list[TextContent]:
    """Handle transcribe_directory tool call."""
    directory = arguments["directory"]
    file_types = arguments.get("file_types", DEFAULT_FILE_TYPES)
    accuracy = arguments.get("accuracy", "standard")
    with_timestamps = arguments.get("with_timestamps", False)
    recursive = arguments.get("recursive", False)
    max_concurrent = arguments.get("max_concurrent", 10)

    # Find media files
    try:
        media_files = find_media_files(directory, file_types, recursive)
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error_message": str(e)
        }, indent=2))]

    if not media_files:
        return [TextContent(type="text", text=json.dumps({
            "status": "success",
            "files_processed": 0,
            "files_failed": 0,
            "transcripts": [],
            "total_duration_seconds": 0,
            "message": "No media files found in directory"
        }, indent=2))]

    # Get durations for all files
    files_with_duration = []
    for file_path in media_files:
        try:
            duration = get_audio_duration(file_path)
            files_with_duration.append((file_path, duration))
        except Exception:
            files_with_duration.append((file_path, 0))

    # Transcribe all files
    try:
        transcriber = get_transcriber()
        results = await transcriber.transcribe_batch(
            files_with_duration,
            accuracy=accuracy,
            max_concurrent=max_concurrent
        )
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error_message": str(e)
        }, indent=2))]

    # Process results and write transcripts
    transcripts = []
    files_processed = 0
    files_failed = 0
    total_duration = 0

    for result in results:
        if result.status == "success":
            transcript_path = write_transcript_file(result, with_timestamps)
            files_processed += 1
            total_duration += result.duration_seconds
            transcripts.append({
                "file": result.file_path,
                "transcript_path": transcript_path,
                "duration_seconds": result.duration_seconds,
                "status": "success"
            })
        else:
            files_failed += 1
            transcripts.append({
                "file": result.file_path,
                "transcript_path": None,
                "duration_seconds": result.duration_seconds,
                "status": "error",
                "error_message": result.error_message
            })

    return [TextContent(type="text", text=json.dumps({
        "status": "success",
        "files_processed": files_processed,
        "files_failed": files_failed,
        "transcripts": transcripts,
        "total_duration_seconds": total_duration,
        "total_duration_formatted": format_duration(total_duration)
    }, indent=2))]


async def handle_get_transcript(arguments: dict) -> list[TextContent]:
    """Handle get_transcript tool call."""
    file_path = arguments["file_path"]

    # Determine if this is a transcript file or media file
    if file_path.endswith(".transcript.txt") or file_path.endswith(".transcript.json"):
        transcript_path = file_path
        # Extract source media path
        if file_path.endswith(".transcript.txt"):
            source_media = file_path[:-15]  # Remove ".transcript.txt"
        else:
            source_media = file_path[:-16]  # Remove ".transcript.json"
    else:
        # It's a media file, find the transcript
        transcript_path = find_transcript(file_path)
        source_media = file_path

        if not transcript_path:
            return [TextContent(type="text", text=json.dumps({
                "status": "error",
                "error_message": f"No transcript found for: {file_path}"
            }, indent=2))]

    # Read transcript
    if not os.path.exists(transcript_path):
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error_message": f"Transcript file not found: {transcript_path}"
        }, indent=2))]

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse based on file type
        if transcript_path.endswith(".json"):
            data = json.loads(content)
            return [TextContent(type="text", text=json.dumps({
                "status": "success",
                "transcript": data.get("transcript", ""),
                "source_media": source_media,
                "duration_seconds": data.get("metadata", {}).get("duration_seconds"),
                "has_timestamps": True,
                "word_count": len(data.get("words", []))
            }, indent=2))]
        else:
            # Plain text - extract transcript (skip header)
            lines = content.split("\n")
            transcript_lines = []
            past_header = False
            for line in lines:
                if past_header:
                    transcript_lines.append(line)
                elif line == "":
                    past_header = True

            transcript = "\n".join(transcript_lines).strip()

            # Try to extract duration from header
            duration = None
            for line in lines[:5]:
                if line.startswith("# Duration:"):
                    duration_str = line.split(":", 1)[1].strip()
                    # Parse MM:SS or HH:MM:SS
                    parts = duration_str.split(":")
                    if len(parts) == 2:
                        duration = int(parts[0]) * 60 + int(parts[1])
                    elif len(parts) == 3:
                        duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    break

            return [TextContent(type="text", text=json.dumps({
                "status": "success",
                "transcript": transcript,
                "source_media": source_media,
                "duration_seconds": duration,
                "has_timestamps": False
            }, indent=2))]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error_message": f"Failed to read transcript: {e}"
        }, indent=2))]


async def handle_get_usage(arguments: dict) -> list[TextContent]:
    """Handle get_usage tool call."""
    try:
        transcriber = get_transcriber()
        usage = await transcriber.get_usage()

        return [TextContent(type="text", text=json.dumps({
            "status": "success",
            **usage
        }, indent=2))]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error_message": str(e)
        }, indent=2))]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
