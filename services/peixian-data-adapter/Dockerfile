FROM python:3.12-slim

WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY app.py models.py providers.py settings.py ./
COPY fixtures ./fixtures

RUN useradd --create-home --uid 10001 adapter
USER adapter
EXPOSE 8091
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8091", "--no-access-log"]
