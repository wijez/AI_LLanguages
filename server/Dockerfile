FROM python:3.10-slim

# Cài Poetry
RUN pip install --no-cache-dir poetry

# Tạo thư mục làm việc
WORKDIR /app

# Copy file poetry trước để cache dependencies
COPY pyproject.toml poetry.lock* ./

# Cài đặt dependencies (không cài dev dependencies trong container)
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root


# Copy toàn bộ source code
COPY . .

# Lệnh mặc định (sẽ override trong docker-compose)
CMD ["poetry", "run", "python", "manage.py", "runserver", "0.0.0.0:8000"]
