# Context contains only the compiled binary and this Dockerfile.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision="${SOURCE_REVISION}" org.peixian.runtime.capabilities="idle_activity_v1,durable_run_v1"
ENV OPENCODE_DISABLE_CHANNEL_DB=1
COPY opencode /usr/local/bin/opencode
