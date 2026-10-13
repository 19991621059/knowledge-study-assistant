FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json tsconfig.json ./
COPY frontend ./frontend
RUN npm ci && npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 STUDY_DATA_DIR=/app/data STUDY_PROJECT_ROOT=/app
WORKDIR /app
COPY backend ./backend
RUN pip install --no-cache-dir -r backend/requirements.lock && pip install --no-cache-dir --no-deps ./backend
COPY examples ./examples
COPY --from=frontend /build/frontend/dist ./frontend/dist
RUN mkdir -p /app/data && chown -R 10001:10001 /app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["python", "-m", "study_assistant", "serve", "--host", "0.0.0.0"]
