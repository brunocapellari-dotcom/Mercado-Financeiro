FROM python:3.12.14-bookworm@sha256:dbbe4ceb97851e2e5fa83798b239811f871cb743b259ba3563737349f6bcfaa0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts

RUN python -m pip install --upgrade 'pip>=26.2.1' 'setuptools>=83' wheel \
    && pip install '.[cloud]'

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

ENTRYPOINT ["python", "scripts/run_operational_cycle.py"]
CMD ["--mode", "full", "--output", "/tmp/mercado-financeiro-operational-evidence.json"]
