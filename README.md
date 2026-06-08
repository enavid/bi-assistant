# BI Assistant

Natural-language HR questions answered with controlled SQL queries against a PostgreSQL analytics view, powered by locally-hosted LLMs via Ollama.

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Python 3.12 |
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS |
| App DB | PostgreSQL (projects, sessions, messages) |
| HR DB | PostgreSQL (HR analytics view) |
| LLM | Ollama (local) |
| ORM | SQLAlchemy async + Alembic |
| Proxy | Nginx |

## Requirements

- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node 20+
- PostgreSQL 14+
- Ollama running locally or accessible via network

## Local development

```bash
git clone git@github.com:enavid/bi-assistant.git
cd bi-assistant

cp .env.example .env
# edit .env and fill in all values
```

**Backend:**

```bash
cd backend
make install     # uv sync (creates .venv and installs all deps)
make dev         # start API server with hot-reload
```

**Frontend:**

```bash
cd frontend
make install     # npm install
make dev         # start Vite dev server (http://localhost:5173)
```

API docs available at `http://localhost:8000/docs`.

## Running tests

**Backend unit tests:**

```bash
cd backend
make test
```

**Backend routing evaluation (golden test suite):**

```bash
cd backend
make eval
```

This runs 44 labeled test cases covering all routing categories (ACCESS\_DENIED, OUT\_OF\_SCOPE, DATA\_GAP, ANALYTICAL\_GAP, SQL) and prints a full result table.

**Frontend:**

```bash
cd frontend
make test        # vitest unit/component tests
make type-check  # TypeScript type checking
```

**Full pre-commit check:**

```bash
cd backend && make check   # lint + test + eval
cd frontend && make check  # lint + type-check + build
```

## Production deployment

```bash
# 1. copy SSL certs
sudo mkdir -p /etc/ssl/bi-assistant
sudo cp fullchain.pem privkey.pem /etc/ssl/bi-assistant/

# 2. create basic auth
mkdir -p nginx/auth
docker run --rm httpd:alpine htpasswd -nb YOUR_USER YOUR_PASSWORD > nginx/auth/.htpasswd

# 3. configure env
cp .env.example .env
nano .env

# 4. start
docker compose up -d
```

**Update:**

```bash
docker compose pull && docker compose up -d
```

**Database migrations:**

```bash
cd backend
alembic revision --autogenerate -m "description"
alembic upgrade head
```
