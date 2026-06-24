FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /code

COPY ./pyproject.toml ./index.html ./main.py ./

# Directly install dependencies to avoid Hatchling packaging issues
RUN uv pip install --system --no-cache fastapi uvicorn google-adk[gcp] google-cloud-aiplatform[agent-engines]

EXPOSE 8081

CMD ["python", "main.py"]
