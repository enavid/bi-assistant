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

- Python 3.12
- Node 18+
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
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

alembic upgrade head
uvicorn app.main:app --reload
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

**Tests:**

```bash
cd backend
source venv/bin/activate
pytest tests -q
```

API docs available at `http://localhost:8000/docs`.

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
