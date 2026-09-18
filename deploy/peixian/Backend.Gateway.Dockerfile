ARG BASE_IMAGE
FROM ${BASE_IMAGE}
LABEL org.peixian.business.run.protocol="1"
COPY services/peixian-control/gateway /app/gateway
COPY services/peixian-control/shared /app/shared
