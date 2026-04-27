FROM python:3.12-slim

# Cài đặt thư viện hệ thống cần thiết cho Postgres và xử lý ảnh (OpenCV/Face Recognition)
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt Poetry
ENV POETRY_VERSION=1.8.0
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Copy file cấu hình dependencies để tận dụng Docker cache
COPY pyproject.toml poetry.lock ./

# Cài đặt thư viện (không tạo môi trường ảo vì Docker đã là một môi trường cô lập)
RUN poetry config virtualenvs.create false \
    && poetry lock \
    && poetry install --only main --no-interaction --no-root

# Copy toàn bộ mã nguồn
COPY . .

COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]