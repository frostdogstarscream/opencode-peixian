# Matched schema v9 backend + compiled console, no runtime data or downloads.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision="${SOURCE_REVISION}" org.peixian.control.schema.max="10" org.peixian.business.run.protocol="1"
ENV PX_BACKEND_V6=1
COPY services/peixian-control/control /app/control
COPY services/peixian-control/shared /app/shared
COPY packages/peixian-console/dist /app/static
