FROM python:3.11-slim

# Keeps Python from buffering stdout/stderr so logs appear immediately
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (separate layer for better cache reuse)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY parser.py .

# Mount point for documents passed in from the host
VOLUME ["/docs"]

ENTRYPOINT ["python", "parser.py"]
