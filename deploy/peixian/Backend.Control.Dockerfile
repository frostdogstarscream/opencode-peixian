# Backend-only release: inherit the already deployed frontend unchanged.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
LABEL org.peixian.control.schema.max="8" org.peixian.business.run.protocol="1"
ENV PX_BACKEND_V6=1
COPY services/peixian-control/control /app/control
COPY services/peixian-control/shared /app/shared
