FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code + template + web UI
COPY *.py ./
COPY template.pptx ./
COPY support.png ./
COPY signature.png ./
COPY templates/ templates/

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
