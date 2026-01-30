# Transcription MCP Server

An MCP server that enables Claude Code to transcribe audio/video files using the Speechmatics Batch API.

## Requirements

- Python 3.11+
- ffmpeg (for `ffprobe` to get audio duration)
- Speechmatics API key

## Installation

1. Install ffmpeg if not already installed:
   ```bash
   # macOS
   brew install ffmpeg

   # Ubuntu/Debian
   sudo apt install ffmpeg
   ```

2. Install dependencies:
   ```bash
   cd /Users/archiemcmullan/Documents/transcription-mcp
   uv sync
   ```

3. Set your Speechmatics API key:
   ```bash
   export SPEECHMATICS_API_KEY="your-key-here"
   ```

## MCP Server Registration

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "transcription": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/archiemcmullan/Documents/transcription-mcp",
        "run",
        "python",
        "server.py"
      ],
      "env": {
        "SPEECHMATICS_API_KEY": "your-key-here"
      }
    }
  }
}
```

## Tools

### transcribe_file

Transcribe a single audio/video file.

**Parameters:**
- `file_path` (required): Absolute path to media file
- `accuracy`: "standard" or "enhanced" (default: "standard")
- `with_timestamps`: Include word-level timestamps (default: false)

**Output:**
- Default: `{filename}.transcript.txt` (plain text with header)
- With timestamps: `{filename}.transcript.json` (JSON with word timings)

### transcribe_directory

Transcribe all media files in a directory with parallel processing.

**Parameters:**
- `directory` (required): Path to directory
- `file_types`: Extensions to include (default: mp3, mp4, wav, m4a, webm, ogg, flac, mov, avi)
- `accuracy`: "standard" or "enhanced"
- `with_timestamps`: Include word-level timestamps
- `recursive`: Search subdirectories (default: false)
- `max_concurrent`: Max parallel jobs (default: 10)

### get_transcript

Read an existing transcript file.

**Parameters:**
- `file_path`: Path to media file OR transcript file

### get_usage

Get Speechmatics API usage statistics for the current month.

## Output Formats

### Plain text (.transcript.txt)

```
# Transcribed: 2024-01-30T14:32:00Z
# Source: meeting.mp4
# Duration: 12:34
# Accuracy: standard

[Plain text transcript here...]
```

### JSON with timestamps (.transcript.json)

```json
{
  "metadata": {
    "source": "meeting.mp4",
    "transcribed_at": "2024-01-30T14:32:00Z",
    "duration_seconds": 754,
    "accuracy": "standard"
  },
  "transcript": "Full plain text...",
  "words": [
    {"word": "Hello", "start": 0.0, "end": 0.5, "confidence": 0.98}
  ]
}
```

## Searching Transcripts

After transcribing, use Claude's native Grep tool to search the `.transcript.txt` files:

```
# Find mentions of "budget" in all transcripts
Grep: pattern="budget", glob="*.transcript.txt", path="/path/to/media"

# Search with context
Grep: pattern="quarterly results", glob="*.transcript.txt", -C=3
```

## License

MIT
