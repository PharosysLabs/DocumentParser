#!/usr/bin/env python3
"""
parser.py - Document and image parser using the Anthropic API.

Usage:
    python parser.py path/to/file.pdf
    python parser.py path/to/image.png --pretty

Extracts structured JSON containing:
    - document_type
    - key_entities
    - summary
    - tables
    - lists
"""

import sys
import json
import base64
import argparse
from pathlib import Path

from dotenv import load_dotenv
import anthropic

# Load ANTHROPIC_API_KEY (and any other vars) from .env in the current directory
load_dotenv()

SUPPORTED_IMAGES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

SUPPORTED_PDFS = {".pdf": "application/pdf"}

ALL_SUPPORTED = {**SUPPORTED_IMAGES, **SUPPORTED_PDFS}

EXTRACTION_PROMPT = """\
Analyze this document or image and extract structured information.

Return ONLY valid JSON — no markdown fences, no explanation, no extra text.
Use exactly this structure:

{
  "document_type": "<type of document, e.g. invoice, contract, receipt, report, form, letter, screenshot, photograph, etc.>",
  "key_entities": [
    {"type": "<entity category: person | organization | date | amount | location | product | id | other>", "value": "<entity value>"}
  ],
  "summary": "<concise 2-3 sentence summary of the content>",
  "tables": [
    {
      "title": "<table heading or brief description, empty string if none>",
      "headers": ["<column 1>", "<column 2>"],
      "rows": [["<r1c1>", "<r1c2>"], ["<r2c1>", "<r2c2>"]]
    }
  ],
  "lists": [
    {
      "title": "<list heading or brief description, empty string if none>",
      "items": ["<item 1>", "<item 2>"]
    }
  ]
}

Rules:
- Extract every meaningful entity (names, dates, amounts, addresses, IDs, etc.).
- Capture every table and every bulleted/numbered list present.
- If there are no tables, use "tables": [].
- If there are no lists, use "lists": [].
- Do NOT wrap the JSON in ```json``` or any other markdown."""


def read_and_encode(file_path: Path) -> tuple[str, str]:
    """Return (base64_data, media_type) for the given file."""
    with open(file_path, "rb") as fh:
        data = base64.standard_b64encode(fh.read()).decode("utf-8")
    media_type = ALL_SUPPORTED[file_path.suffix.lower()]
    return data, media_type


def build_content(file_path: Path) -> list:
    """Construct the message content blocks for the API request."""
    b64_data, media_type = read_and_encode(file_path)
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        file_block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": b64_data,
            },
        }
    else:
        file_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": b64_data,
            },
        }

    return [file_block, {"type": "text", "text": EXTRACTION_PROMPT}]


def strip_code_fence(text: str) -> str:
    """Remove markdown ```json ... ``` wrappers if the model added them anyway."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop the opening fence line and, if present, the closing fence
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end]).strip()
    return text


def parse_document(file_path: Path) -> dict:
    """Send the file to Claude and return the parsed JSON dict."""
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": build_content(file_path),
            }
        ],
    )

    text_block = next(
        (block for block in response.content if block.type == "text"), None
    )
    if not text_block:
        raise ValueError("API returned no text content.")

    raw = strip_code_fence(text_block.text)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"API response was not valid JSON.\n"
            f"Raw response:\n{raw}\n\nJSON error: {exc}"
        ) from exc


def main() -> None:
    arg_parser = argparse.ArgumentParser(
        description="Extract structured JSON from a PDF or image using Claude.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Supported formats: "
            + ", ".join(sorted(ALL_SUPPORTED))
            + "\n\n"
            "Set ANTHROPIC_API_KEY in a .env file (or as an environment variable).\n"
            "Example .env:\n"
            "  ANTHROPIC_API_KEY=sk-ant-..."
        ),
    )
    arg_parser.add_argument(
        "file",
        help="Path to a PDF or image file to parse.",
    )
    arg_parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON output (2-space indent).",
    )
    args = arg_parser.parse_args()

    file_path = Path(args.file)

    # --- Validate input ---
    if not file_path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    if not file_path.is_file():
        print(f"Error: Path is not a file: {file_path}", file=sys.stderr)
        sys.exit(1)

    suffix = file_path.suffix.lower()
    if suffix not in ALL_SUPPORTED:
        supported_str = ", ".join(sorted(ALL_SUPPORTED))
        print(
            f"Error: Unsupported file type '{suffix}'.\n"
            f"Supported types: {supported_str}",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Call the API ---
    try:
        result = parse_document(file_path)
    except anthropic.AuthenticationError:
        print(
            "Error: Authentication failed. Check that ANTHROPIC_API_KEY is set "
            "correctly in your .env file or environment.",
            file=sys.stderr,
        )
        sys.exit(1)
    except anthropic.PermissionDeniedError:
        print(
            "Error: API key does not have permission to use this model.",
            file=sys.stderr,
        )
        sys.exit(1)
    except anthropic.BadRequestError as exc:
        print(f"Error: Bad request — {exc.message}", file=sys.stderr)
        sys.exit(1)
    except anthropic.RateLimitError:
        print(
            "Error: Rate limit exceeded. Please wait a moment and try again.",
            file=sys.stderr,
        )
        sys.exit(1)
    except anthropic.APIStatusError as exc:
        print(
            f"Error: Anthropic API error (HTTP {exc.status_code}) — {exc.message}",
            file=sys.stderr,
        )
        sys.exit(1)
    except anthropic.APIConnectionError:
        print(
            "Error: Could not connect to the Anthropic API. "
            "Check your internet connection.",
            file=sys.stderr,
        )
        sys.exit(1)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # --- Output ---
    indent = 2 if args.pretty else None
    print(json.dumps(result, indent=indent, ensure_ascii=False))


if __name__ == "__main__":
    main()
