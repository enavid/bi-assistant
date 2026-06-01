# BI Assistant

[![CI](https://github.com/enavid/bi-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/enavid/bi-assistant/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![React](https://img.shields.io/badge/react-18-61dafb.svg)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Natural-language HR questions → PostgreSQL queries, powered by locally hosted LLMs via Ollama.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS |
| Backend | FastAPI + Python 3.12 |
| ORM | SQLAlchemy async + Alembic |
| App DB | PostgreSQL (projects, sessions, messages) |
| HR DB | PostgreSQL (HR data — query target) |
| LLM | Ollama |
| Proxy | Nginx + SSL + Basic Auth |
| CI | GitHub Actions → ghcr.io |

---

## Local development

```bash
git clone git@github.com:enavid/bi-assistant.git
cd bi-assistant

cp .env.example .env
# fill in all values

# backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# frontend (new terminal)
cd frontend
npm install
npm run dev
```

---

## Production deployment

```bash
# 1. copy SSL certs
sudo mkdir -p /etc/ssl/bi-assistant
sudo cp fullchain.pem privkey.pem /etc/ssl/bi-assistant/

# 2. create basic auth
mkdir -p nginx/auth
docker run --rm httpd:alpine htpasswd -nb YOUR_USER YOUR_PASSWORD > nginx/auth/.htpasswd

# 3. configure env
cp .env.example .env && nano .env

# 4. start
docker compose pull
docker compose up -d
```

## Update

```bash
docker compose pull && docker compose up -d
```

## Database migrations

```bash
cd backend
alembic revision --autogenerate -m "description"
alembic upgrade head
```
