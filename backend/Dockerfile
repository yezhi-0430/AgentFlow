FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
WORKDIR /app
COPY pyproject.toml README.md requirements.txt LICENSE ./
COPY agentflow ./agentflow
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "agentflow.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
