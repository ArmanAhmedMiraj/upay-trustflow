# Stage 1: build the phone app
FROM node:22-slim AS web
WORKDIR /web
COPY wallet-app/package.json wallet-app/package-lock.json ./
RUN npm ci
COPY wallet-app/ ./
RUN npm run build

# Stage 2: the service (wallet API + Shield + the built phone app)
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt
COPY deploy ./deploy
COPY wallet-api ./wallet-api
COPY shield-api ./shield-api
COPY simulator ./simulator
COPY reports/module1/metrics.json ./reports/module1/metrics.json
COPY --from=web /web/dist ./wallet-app/dist
ENV PYTHONUNBUFFERED=1
EXPOSE 10000
CMD ["sh", "-c", "uvicorn deploy.app:app --host 0.0.0.0 --port ${PORT:-10000}"]
