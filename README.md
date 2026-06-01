# BI Assistant

[![CI](https://github.com/enavid/bi-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/enavid/bi-assistant/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![React](https://img.shields.io/badge/react-18-61dafb.svg)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

An open-source BI chat assistant that converts natural-language questions into PostgreSQL queries using locally hosted LLMs via Ollama, with a block-based prompt engineering studio.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS |
| Backend | FastAPI + Python 3.12 |
| LLM | Ollama (llama3-sqlcoder) |
| Database | PostgreSQL |
| Proxy | Nginx with SSL + Basic Auth |
| CI | GitHub Actions → ghcr.io |

---

## Project structure

```
bi-assistant/
├── backend/
│   ├── app/
│   │   ├── api/routes/     chat.py · templates.py · ollama.py
│   │   ├── core/           config.py
│   │   ├── models/         domain.py
│   │   ├── schemas/        requests.py
│   │   ├── services/       llm_service · db_service · prompt_service · storage_service
│   │   └── main.py
│   ├── data/               schema_context.txt · prompts.json (gitignored)
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/     Sidebar.tsx
│   │   ├── hooks/          useOllamaHealth · useTemplates · useSessions
│   │   ├── pages/          ChatPage · BuilderPage · SettingsPage
│   │   ├── services/       apiClient.ts · api.ts
│   │   ├── store/          appStore.ts
│   │   └── types/          index.ts
│   └── Dockerfile
├── nginx/                  nginx.conf
├── docker-compose.yml
└── .github/workflows/      ci.yml
```

---

## Local development

```bash
git clone git@github.com:enavid/bi-assistant.git
cd bi-assistant

cp backend/.env.example backend/.env
# fill in backend/.env

# add your schema
cp /path/to/schema_context.txt backend/data/

# backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload

# frontend (new terminal)
cd frontend && npm install && npm run dev
```

---

## Production deployment

```bash
# 1. pull images
docker compose pull

# 2. copy SSL certs
sudo mkdir -p /etc/ssl/bi-assistant
sudo cp fullchain.pem privkey.pem /etc/ssl/bi-assistant/

# 3. create basic auth
mkdir -p nginx/auth
docker run --rm httpd:alpine htpasswd -nb YOUR_USER YOUR_PASSWORD > nginx/auth/.htpasswd

# 4. configure env
cp backend/.env.example backend/.env && nano backend/.env

# 5. add runtime data
touch backend/data/prompts.json backend/data/sessions.json
cp schema_context.txt backend/data/

# 6. start
docker compose up -d
```

---

## Update

```bash
docker compose pull && docker compose up -d
```
