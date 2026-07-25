# Nipuna AI — Backend Monorepo

This repo hosts the backend and infrastructure side of **Nipuna AI**: a
LangGraph-powered assistant with source-grounded answers, a multi-tenant
FastAPI orchestration API, AWS infrastructure-as-code, and a desktop agent
for local integrations (Tally).

![python](https://img.shields.io/badge/python-FastAPI%20%2B%20LangGraph-009688) ![db](https://img.shields.io/badge/db-PostgreSQL%20%2B%20Redis-336791) ![infra](https://img.shields.io/badge/infra-AWS%20CDK-FF9900) ![desktop](https://img.shields.io/badge/desktop-Electron-47848F) ![automation](https://img.shields.io/badge/automation-n8n%20(vendored)-EA4B71)

---

## Repo layout

```
├── graph.py, main.py, schemas.py, nodes/, tools/     # Nipuna AI Assistant (LangGraph service)
├── evals/                                             # Local eval suite for the assistant
├── nipuna-backend/                                    # Multi-tenant orchestration API (FastAPI)
├── nipuna-desktop/                                     # Electron desktop agent (Tally MCP bridge)
├── infrastructure/                                      # AWS CDK stacks
├── agents-nipuna-ai-workflow/                            # Vendored/customized n8n (workflow engine)
├── templates/clerk/                                       # Clerk auth email templates
└── lefthook.yml                                            # Git hooks config
```

Each subproject is documented below; `nipuna-backend/` and `nipuna-desktop/`
also have their own more detailed docs (`CLAUDE.md`, `README.md`).

---

## 1. Nipuna AI Assistant (repo root)

A production-grade business Q&A backend built on **LangGraph**, with explicit
source routing, grounding, and citation metadata — it doesn't answer from
unverified context, and branches to a clarification step instead of guessing.

**Graph flow:**

```
classify_intent -> route_to_source -> retrieve -> ground_and_verify -> generate_answer
```

- If the query is ambiguous or retrieval returns nothing reliable, the graph
  branches to `clarify`.
- **Gmail** is the reference integration end-to-end (`gmail_search_emails`,
  `gmail_get_email`, `gmail_send_email`), with a deterministic local fixture
  connector for dev/evals, and a Composio-backed live connector
  (`NIPUNA_AI_GMAIL_MODE=live`).

**API**

`POST /chat` — body: `{"thread_id": "...", "message": "..."}` → returns
`answer`, `citations`, `sources_queried`, `confidence`, `needs_clarification`,
`clarification_question`.

`POST /chat/stream` — same input, server-sent events.

**Run**

```bash
uvicorn main:app --reload
```

**Eval**

```bash
pytest evals/test_answers.py -q
```

---

## 2. `nipuna-backend/` — Multi-tenant orchestration API

The core FastAPI backend that Nipuna's frontend (`nipuna-vision`) talks to.

- **Framework**: FastAPI (Python) with async SQLAlchemy over PostgreSQL
- **Migrations**: Alembic
- **Background processing**: Celery workers over Redis/SQS
- **Auth**: Outsourced to Clerk (JWT validation)
- **Domain model**: `Organization` (tenant, seats, credits) → `User` →
  `Agent` (functional entity with a domain/objective) → `Conversation`
- **Multi-tenancy** enforced via `org_id` on most tables
- **Middleware**: logging, security headers, rate limiting (`slowapi`)
- All endpoints are versioned under `/api/v1`
- Integrations via **Composio**, payments via **Razorpay**, error tracking via
  **Sentry**, webhooks via **Svix**

**Local dev**

```bash
cd nipuna-backend
docker compose up -d postgres redis    # infra
alembic upgrade head                    # migrate
docker compose up -d api worker          # start services
pytest                                    # run tests
```

See `nipuna-backend/CLAUDE.md` for the fuller architecture writeup.

---

## 3. `nipuna-desktop/` — Desktop agent

An **Electron** app that runs a local **Tally MCP server** (bundled from
`nipuna-backend/1766393040_tally_mcp_server_v6`) and bridges it to the Nipuna
backend, so agents can read/write local Tally accounting data.

**Sign-in flow**: the agent opens the browser to
`http://localhost:5173/desktop-auth?redirect_uri=http://localhost:41731/callback`;
after Clerk sign-in the web app redirects back with a token, which the agent
captures and uses to connect to the backend.

**Run / build**

```bash
cd nipuna-desktop
npm install
npm start              # run locally
npm run build:win       # Windows installer (nsis)
npm run build:mac        # macOS installer (dmg)
```

---

## 4. `infrastructure/` — AWS CDK

Infrastructure-as-code (compiled JS + `.d.ts`, so likely built from a
TypeScript CDK app) defining the AWS stacks Nipuna runs on:

| Stack | Purpose |
| --- | --- |
| `vpc-stack` | Networking |
| `ecr-stack` | Container image registry |
| `ecs-stack` | Container orchestration (API/worker) |
| `rds-stack` | PostgreSQL |
| `elasticache-stack` | Redis |
| `opensearch-stack` | Search/indexing |
| `pipeline-role-stack` | CI/CD IAM roles |

Entry point: `infrastructure/bin/app.js`.

---

## 5. `agents-nipuna-ai-workflow/` — Vendored n8n

A customized copy of **n8n** (workflow automation engine) — the full
`packages/nodes-base/nodes/*` catalogue of 300+ integration nodes (Gmail,
Slack, Airtable, Postgres, Stripe, OpenAI, HighLevel, etc.), used as the
workflow/automation runtime behind Nipuna's workflow-builder feature. This is
vendored rather than a plain npm dependency, implying local node
customizations — diff against upstream n8n before assuming any given node is
unmodified.

---

## 6. `templates/clerk/`

HTML email templates for Clerk auth flows (`verification_code.html`,
`reset_password_code.html`).

---

## Tooling

- **lefthook.yml** — git hooks config (currently the stock example; not yet
  wired to real lint/test commands).

---

## License

No license specified — treat as a private/proprietary codebase.
