FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
LABEL org.peixian.control.schema.min="0" org.peixian.control.schema.max="3"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY services/peixian-control/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock && useradd -u 10001 -m peixian
COPY services/peixian-control/control /app/control
COPY services/peixian-control/shared /app/shared
COPY packages/peixian-console/dist /app/static
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn","control.app:app","--host","0.0.0.0","--port","8080","--no-access-log"]
