# lakecheck — zero-JVM data quality CLI. No JRE/Spark needed (delta-rs + PyIceberg
# + PyArrow are pure Python/native), so the image is small and starts instantly.

# Stage 1: builder
FROM python:3.11-slim AS builder
WORKDIR /app
COPY pyproject.toml .
COPY lakecheck/ lakecheck/
RUN pip install --user --no-warn-script-location .

# Stage 2: minimal runtime, non-root
FROM python:3.11-slim
RUN groupadd -g 10001 lakecheck && \
    useradd -u 10001 -g lakecheck -s /bin/bash -m lakecheck
COPY --from=builder /root/.local /home/lakecheck/.local
COPY --from=builder /app /app
ENV PATH=/home/lakecheck/.local/bin:$PATH
USER 10001
WORKDIR /app
ENTRYPOINT ["lakecheck"]
