# LLM Document Parser

A command-line tool that sends PDF and image files to the Anthropic API and returns structured JSON extracted from the document. Designed for technical document parsing in engineering and operational workflows where consistent, machine-readable output is more useful than raw text.

---

## What It Does

`parser.py` accepts a single PDF or image file, sends it to Claude Sonnet 4.6 via the Anthropic API, and prints a structured JSON object containing:

| Field | Description |
|---|---|
| `document_type` | Classification of the document (e.g. invoice, datasheet, work order, schematic) |
| `key_entities` | Named entities extracted with type labels (person, organization, date, amount, location, product, ID) |
| `summary` | A 2–3 sentence plain-language summary of the document's content |
| `tables` | Every table found, with headers and row data preserved |
| `lists` | Every bulleted or numbered list found, with items preserved |

Output is written to stdout, making it composable with `jq`, shell pipelines, log aggregators, and downstream services.

---

## Use Case

Engineering and operations teams regularly receive documents that need to be ingested into systems — purchase orders, equipment datasheets, inspection reports, compliance certificates, scanned work orders, and field photos. Manually re-keying this information is error-prone and does not scale.

This tool provides a repeatable extraction layer that turns unstructured documents into structured data that can be:

- Validated and loaded into databases or ERP systems
- Routed to the correct team or workflow based on `document_type`
- Diffed against existing records to detect discrepancies
- Stored alongside the original file as a sidecar JSON for search indexing

It handles both digitally-created PDFs (with selectable text) and scanned or photographed documents equally, since the model processes the visual content directly.

---

## Requirements

- Python 3.11 or later
- An [Anthropic API key](https://console.anthropic.com/)
- The following Python packages (see `requirements.txt`):
  - `anthropic >= 0.40.0`
  - `python-dotenv >= 1.0.0`

**Supported file formats:** `.pdf`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`

---

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd llm-doc-parser
```

### 2. Create and activate a virtual environment

**macOS / Linux**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows**
```cmd
python -m venv venv
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure your API key

Copy the example env file and add your key:

```bash
cp .env.example .env
```

Edit `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

The script loads this automatically via `python-dotenv`. The `.env` file is not committed to version control.

---

## Usage

```
python parser.py <file> [--pretty]
```

| Argument | Description |
|---|---|
| `file` | Path to the PDF or image file to parse (required) |
| `--pretty` | Pretty-print JSON with 2-space indentation (optional) |

### Parse a PDF

```bash
python parser.py documents/inspection_report.pdf --pretty
```

### Parse an image

```bash
python parser.py photos/equipment_label.png --pretty
```

### Compact output for piping

```bash
python parser.py invoice.pdf | jq '.key_entities[] | select(.type == "amount")'
```

### Redirect output to a file

```bash
python parser.py work_order.pdf --pretty > work_order_parsed.json
```

### Batch processing with a shell loop

```bash
for f in docs/*.pdf; do
  python parser.py "$f" > "${f%.pdf}.json"
done
```

---

## Sample Output

Input: a scanned purchase order PDF.

```json
{
  "document_type": "purchase order",
  "key_entities": [
    { "type": "organization", "value": "Acme Industrial Supply" },
    { "type": "organization", "value": "Pharosys Labs" },
    { "type": "id",           "value": "PO-2024-00847" },
    { "type": "date",         "value": "2024-11-12" },
    { "type": "date",         "value": "2024-11-30" },
    { "type": "person",       "value": "R. Kowalski" },
    { "type": "amount",       "value": "$14,350.00" },
    { "type": "location",     "value": "Austin, TX 78701" }
  ],
  "summary": "Purchase order PO-2024-00847 from Pharosys Labs to Acme Industrial Supply for three line items totalling $14,350.00. Requested delivery by November 30, 2024 to the Austin facility. Approved by R. Kowalski.",
  "tables": [
    {
      "title": "Line Items",
      "headers": ["Item", "Part No.", "Qty", "Unit Price", "Total"],
      "rows": [
        ["Pressure Sensor Module", "PS-441-B", "10", "$325.00",   "$3,250.00"],
        ["Relay Assembly",         "RA-220-X", "20", "$180.00",   "$3,600.00"],
        ["Control Board Rev 3",   "CB-003-R3",  "5", "$1,500.00", "$7,500.00"]
      ]
    }
  ],
  "lists": [
    {
      "title": "Delivery Requirements",
      "items": [
        "Ship via approved carrier only",
        "Include packing slip with each carton",
        "Fragile items must be double-boxed"
      ]
    }
  ]
}
```

---

## Error Handling

The script exits with code `1` and prints a descriptive message to stderr for all failure conditions:

| Condition | Message |
|---|---|
| File not found | `Error: File not found: <path>` |
| Unsupported file type | `Error: Unsupported file type '.xyz'. Supported types: ...` |
| Invalid or missing API key | `Error: Authentication failed. Check that ANTHROPIC_API_KEY is set correctly...` |
| Rate limit exceeded | `Error: Rate limit exceeded. Please wait a moment and try again.` |
| Network failure | `Error: Could not connect to the Anthropic API. Check your internet connection.` |
| API error | `Error: Anthropic API error (HTTP 5xx) — <message>` |

This makes the tool safe to use in scripts — callers can check the exit code and capture stderr independently from the JSON output on stdout.

---

## Extending to a REST API or Internal Tooling Platform

The core logic in `parser.py` is contained in three functions (`read_and_encode`, `build_content`, `parse_document`) with no framework dependencies. Wrapping this in a service requires minimal additional code.

### FastAPI REST endpoint

```python
from fastapi import FastAPI, UploadFile, HTTPException
import tempfile, shutil
from pathlib import Path
from parser import parse_document, ALL_SUPPORTED

app = FastAPI()

@app.post("/parse")
async def parse(file: UploadFile):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALL_SUPPORTED:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {suffix}")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        result = parse_document(Path(tmp.name))

    return result
```

Run with `uvicorn api:app --reload`. The endpoint accepts a multipart file upload and returns the same JSON structure produced by the CLI.

### Internal tooling integrations

**Document intake queue** — wrap `parse_document` in a Celery or RQ worker. Drop files into a watched folder or S3 bucket; the worker picks them up, calls the parser, and writes results to a database or message queue for downstream consumers.

**Web upload UI** — pair the FastAPI endpoint with a simple HTML form or a Streamlit app. Non-technical staff upload documents through a browser; the parsed JSON is displayed for review and forwarded to the appropriate system.

**ERP / CMMS connector** — post the parsed JSON to an internal webhook that maps `key_entities` and `tables` to fields in your ERP, CMMS, or ticketing system. The `document_type` field can drive routing logic (work orders to one queue, invoices to another).

**Audit trail** — store the original file, the parsed JSON, and the API response metadata (`model`, token counts, timestamp) together in object storage. This creates a verifiable record of what was extracted and when, useful for compliance workflows.

**Confidence gating** — extend `parse_document` to return the raw `response.usage` alongside the result. Flag extractions with unexpectedly low output token counts (which can indicate the model found little to extract) for human review before ingestion.
