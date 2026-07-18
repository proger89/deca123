FROM ghcr.io/astral-sh/uv:0.7.2@sha256:8c2534159d236ad1722f1e763a8fa4b49743e1cdf5ec4ca2b119459c6d69d3da AS uv

FROM cyberbotics/webots:R2025a-ubuntu22.04@sha256:f0023e30daf38b172e4e6ad24ed345909bcd9551df34d63d824e121a7cebf099

USER root
ARG UV_VERSION=0.7.2
ARG PYTHON_VERSION=3.12.10

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONHASHSEED=0 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:/usr/local/webots:${PATH}

COPY --from=uv /uv /uvx /bin/
RUN test "$(uv --version)" = "uv ${UV_VERSION}" \
    && uv python install "${PYTHON_VERSION}" \
    && uv venv --python "${PYTHON_VERSION}" /opt/venv

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE .gitignore ./
RUN uv sync --frozen --group dev --no-install-project

COPY src ./src
COPY tests ./tests
COPY tools ./tools
COPY config ./config
COPY assets ./assets
COPY criteria ./criteria
COPY docs ./docs
COPY run_scenario.py ./run_scenario.py
RUN uv sync --frozen --group dev

ENTRYPOINT ["python", "run_scenario.py"]
CMD ["doctor", "--inside-container"]
