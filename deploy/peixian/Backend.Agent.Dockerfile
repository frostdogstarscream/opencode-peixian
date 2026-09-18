# Context: this Dockerfile and the compiled Linux x64 binary named opencode.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
LABEL org.peixian.runtime.capabilities="idle_activity_v1,durable_run_v1"
# Build channel names must never select a different production session database.
ENV OPENCODE_DISABLE_CHANNEL_DB=1
COPY opencode /usr/local/bin/opencode
