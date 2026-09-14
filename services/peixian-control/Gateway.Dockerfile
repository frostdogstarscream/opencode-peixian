FROM oven/bun:1.3.14-slim@sha256:d56a2534ffd262e92c12fd3249d3924d296d97086da773f821d7d0477435ea04 AS bun
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun
COPY services/peixian-control/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock && useradd -u 10001 -m peixian
COPY services/peixian-control/gateway /app/gateway
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn","gateway.app:app","--host","0.0.0.0","--port","8080","--no-access-log"]
