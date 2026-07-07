# Stage 1: Build the React frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Package Python and serve
FROM python:3.12-slim
WORKDIR /app

# Install build dependencies and fonts.
# fonts-dejavu-core + fonts-liberation give the PDF renderer real scalable TrueType
# fonts (matching the /usr/share/fonts paths the code looks for); without them Pillow
# falls back to a tiny fixed bitmap and all PDF text renders microscopic.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    fonts-dejavu-core \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy uv binary for fast pip installations
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy and install frozen dependencies
COPY requirements.txt ./
RUN uv pip install --system -r requirements.txt

# Copy built frontend from Stage 1
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Copy the backend code and workspace files
COPY . .

# Expose port and run server
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.fast_api_app:app --host 0.0.0.0 --port $PORT"]
