FROM oven/bun:1.3.14-slim@sha256:d56a2534ffd262e92c12fd3249d3924d296d97086da773f821d7d0477435ea04 AS frontend
WORKDIR /build/packages/peixian-console
COPY packages/peixian-console/package.json packages/peixian-console/bun.lock ./
RUN bun install --frozen-lockfile --ignore-scripts
COPY packages/peixian-console/src ./src
COPY packages/peixian-console/index.html packages/peixian-console/vite.config.ts packages/peixian-console/tsconfig.json ./
COPY packages/ui/src/styles/theme.css /build/packages/ui/src/styles/theme.css
RUN bun typecheck && bun run build

FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
ARG BUILD_MODE=dev
ARG SOURCE_COMMIT=
ARG INPUT_DIGEST=
ARG FRONTEND_BASE=oven/bun:1.3.14-slim@sha256:d56a2534ffd262e92c12fd3249d3924d296d97086da773f821d7d0477435ea04
ARG RUNTIME_BASE=python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
LABEL org.peixian.control.schema.min="0" org.peixian.control.schema.max="5"
LABEL org.peixian.control.config.max="4" org.peixian.runtime.protocol="2"
LABEL org.peixian.worker.capabilities="runtime_pool_v1,runtime_pool_wait_v1,idle_activity_v1"
LABEL org.peixian.worker.protocol="2"
LABEL org.peixian.control.delivery.format="1" org.peixian.control.delivery.mode="$BUILD_MODE"
LABEL org.opencontainers.image.revision="$SOURCE_COMMIT"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CONSOLE_REQUIRE_STATIC=1
WORKDIR /app
COPY services/peixian-control/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock && useradd -u 10001 -m peixian
COPY services/peixian-control/control /app/control
COPY services/peixian-control/shared /app/shared
COPY --from=frontend /build/packages/peixian-console/dist /app/static
RUN python -m shared.control_delivery --static /app/static --output /app/build-manifest.json \
    --mode "$BUILD_MODE" --source-commit "$SOURCE_COMMIT" --input-digest "$INPUT_DIGEST" \
    --frontend-base "$FRONTEND_BASE" --runtime-base "$RUNTIME_BASE"
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn","control.app:app","--host","0.0.0.0","--port","8080","--no-access-log","--timeout-graceful-shutdown","5"]
