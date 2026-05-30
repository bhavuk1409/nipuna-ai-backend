# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands
- **Infrastructure Setup**: `docker compose up -d postgres redis` (Starts DB and Cache)
- **Database Migrations**: `alembic upgrade head`
- **Start Services**: `docker compose up -d api worker`
- **Run Tests**: `pytest` (Ensure environment variables from `.env` are set)
- **Run a Single Test**: `pytest path/to/test_file.py::test_function_name`
- **Environment Setup**: `bash scripts/setup_dev.sh` (Full dev environment boot)

## Architecture Overview
The project is a multi-tenant AI Agent orchestration backend.

### Core Structure
- **Framework**: FastAPI (Python)
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Migrations**: Alembic
- **Background Processing**: Distributed worker architecture using Redis
- **Authentication**: Outsourced to Clerk (JWT validation)

### Domain Model
- **Organization**: The top-level tenant. Controls seats, AI credits, and ownership of all other entities.
- **User**: Belongs to an organization; authenticated via Clerk.
- **Agent**: The primary functional entity with a specific domain and objective.
- **Conversation**: Links users and agents to maintain stateful interactions.

### Key Implementation Details
- **Multi-tenancy**: Enforced via `org_id` on most tables.
- **Middleware**: Includes custom logging, security headers, and rate limiting (`slowapi`).
- **API Versioning**: All endpoints are prefixed with `/api/v1`.
- **Frontend Integration**: Communicates with `nipuna-vision` (TanStack Start app) via JSON REST API with Bearer token authentication.
