# Recognition Service API

**Version:** 1.0.0  
**API Version:** v1  
**Contract Version:** 0.1.1

## Overview

The Recognition/Review microservice for the Employee Management & Rewards System. Handles performance reviews, multi-category tagging, automatic points calculation, and wallet integration.

## Features

- ✅ **Contract-Compliant** — Fully implements API contract v0.1.1
- ✅ **Role-Based Access Control** — Granular permissions for EMPLOYEE, MANAGER, HR_ADMIN, SUPER_ADMIN
- ✅ **Multi-Category Tagging** — 1–5 category tags per review; multipliers frozen as snapshots at write time
- ✅ **Points Engine** — Stateless calculation: `sum(category_multipliers) × reviewer_weight`
- ✅ **Two-Tier Caching** — L1 in-process + L2 Redis with per-entity TTL strategy
- ✅ **Wallet Integration** — Auto-credits receiver on review creation; adjusts delta on update
- ✅ **Audit Trail** — Full `created_by` / `updated_by` / `created_at` / `updated_at` on all writes
- ✅ **Pagination** — Consistent pagination metadata across all list endpoints
- ✅ **Standardised Error Handling** — Uniform error shape with HTTP status codes
- ✅ **OpenTelemetry Tracing** — Distributed tracing via OTLP exporter (Jaeger-compatible)
- ✅ **Digest Worker** — Background async task for scheduled email digest delivery
- ✅ **Rate Limiting** — Per-request middleware rate limiting

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.115.0 |
| Database | PostgreSQL via Prisma ORM (prisma-client-py) |
| Cache | Redis (L2) + in-process dict (L1) |
| Auth | OAuth 2.0 Bearer Token (validated against Auth Service) |
| Tracing | OpenTelemetry SDK + OTLP gRPC exporter |
| Python | 3.11+ |

---

## API Endpoints

All endpoints are prefixed with `/v1/recognitions` (service root path).

### Review Categories

| Method | Endpoint | Description | Roles |
|--------|----------|-------------|-------|
| GET | `/v1/recognitions/review-categories` | List categories (paginated) | EMPLOYEE, MANAGER, HR_ADMIN, SUPER_ADMIN |
| POST | `/v1/recognitions/review-categories` | Create a new category | HR_ADMIN, SUPER_ADMIN |
| PUT | `/v1/recognitions/review-categories/{id}` | Update an existing category | HR_ADMIN, SUPER_ADMIN |

### Reviews

| Method | Endpoint | Description | Roles |
|--------|----------|-------------|-------|
| GET | `/v1/recognitions/reviews` | List reviews (paginated) | EMPLOYEE, MANAGER, HR_ADMIN, SUPER_ADMIN |
| GET | `/v1/recognitions/reviews/{id}` | Get a specific review | Reviewer, Receiver, HR_ADMIN, SUPER_ADMIN |
| POST | `/v1/recognitions/reviews` | Create a new review | EMPLOYEE, MANAGER, HR_ADMIN, SUPER_ADMIN |
| PUT | `/v1/recognitions/reviews/{id}` | Update an existing review | Review owner, HR_ADMIN, SUPER_ADMIN |

### Digest

| Method | Endpoint | Description | Roles |
|--------|----------|-------------|-------|
| GET | `/v1/recognitions/digest` | View recognition digest | EMPLOYEE, MANAGER, HR_ADMIN, SUPER_ADMIN |
| POST | `/v1/recognitions/digest/send` | Trigger digest send | HR_ADMIN, SUPER_ADMIN |

---

## Installation

### Prerequisites

- Python 3.11+
- PostgreSQL database
- Redis instance (optional — caching degrades gracefully to DB-only if Redis is unavailable)
- A running Auth Service for token validation

### Setup

1. **Navigate to the project**
   ```bash
   cd recognition-service
   ```

2. **Create and activate a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables** — create a `.env` file:
   ```env
   DATABASE_URL="postgresql://user:password@host:port/database?sslmode=require"
   AUTH_SERVICE_URL="http://localhost:8001/v1/auth/validate"
   REDIS_URL="redis://localhost:6379/0"
   FRONTEND_CORS_ORIGINS="http://localhost:3000,https://app.yourdomain.com"
   SMTP_HOST="smtp.yourdomain.com"
   SMTP_PORT="587"
   SMTP_USER="noreply@yourdomain.com"
   SMTP_PASSWORD="your-smtp-password"
   OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
   ```

5. **Generate Prisma client**
   ```bash
   prisma generate
   ```

6. **Run database migrations**
   ```bash
   prisma migrate deploy
   ```

7. **Start the service**
   ```bash
   uvicorn src.recognition.main:app --host 0.0.0.0 --port 8005 --reload
   ```

---

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | ✓ |
| `AUTH_SERVICE_URL` | Auth service token validation endpoint | ✓ |
| `FRONTEND_CORS_ORIGINS` | Comma-separated list of allowed CORS origins | ✓ |
| `REDIS_URL` | Redis connection URL | Recommended |
| `SMTP_HOST` | SMTP server hostname | For digest emails |
| `SMTP_PORT` | SMTP server port (default: 587) | For digest emails |
| `SMTP_USER` | SMTP username / sender address | For digest emails |
| `SMTP_PASSWORD` | SMTP password | For digest emails |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP gRPC endpoint for distributed tracing | For observability |

> **Note:** The service starts and operates without Redis or SMTP configured — caching falls back to direct DB queries, and digest emails are logged as failed rather than crashing the service.

---

## API Documentation

With the service running, visit:

- **Swagger UI** → http://localhost:8005/v1/recognitions/docs
- **ReDoc** → http://localhost:8005/v1/recognitions/redoc
- **OpenAPI JSON** → http://localhost:8005/v1/recognitions/openapi.json

---

## Request & Response Examples

### Review Categories

#### List Categories — `GET /v1/recognitions/review-categories`

```bash
curl "http://localhost:8005/v1/recognitions/review-categories?active_only=true" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response (200 OK)**
```json
{
  "data": [
    {
      "category_id": "770e8400-e29b-41d4-a716-446655440001",
      "category_code": "INNOVATION",
      "category_name": "Innovation",
      "multiplier": 1.4,
      "description": "Recognises creative problem-solving and novel ideas",
      "is_active": true
    }
  ],
  "pagination": {
    "current_page": 1,
    "per_page": 20,
    "total": 5,
    "total_pages": 1,
    "has_next": false,
    "has_previous": false
  }
}
```

#### Create Category — `POST /v1/recognitions/review-categories`

> `is_active` is not accepted on creation — all new categories are active by default. Use `PUT` to deactivate.

```bash
curl -X POST http://localhost:8005/v1/recognitions/review-categories \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "category_code": "INNOVATION",
    "category_name": "Innovation",
    "multiplier": 1.4,
    "description": "Recognises creative problem-solving and novel ideas"
  }'
```

**Response (201 Created)**
```json
{
  "category_id": "770e8400-e29b-41d4-a716-446655440001",
  "category_code": "INNOVATION",
  "category_name": "Innovation",
  "multiplier": 1.4,
  "description": "Recognises creative problem-solving and novel ideas",
  "is_active": true
}
```

#### Update Category — `PUT /v1/recognitions/review-categories/{id}`

At least one field required. `is_active` is the only way to deactivate a category after creation.

> ⚠️ Changing `multiplier` only affects **future** reviews. Historical reviews are unaffected — each review freezes multiplier values as snapshots at write time.

```bash
curl -X PUT http://localhost:8005/v1/recognitions/review-categories/770e8400-e29b-41d4-a716-446655440001 \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "multiplier": 1.5, "is_active": false }'
```

**Response (200 OK)**
```json
{
  "category_id": "770e8400-e29b-41d4-a716-446655440001",
  "category_code": "INNOVATION",
  "category_name": "Innovation",
  "multiplier": 1.5,
  "description": "Recognises creative problem-solving and novel ideas",
  "is_active": false
}
```

---

### Reviews

#### List Reviews — `GET /v1/recognitions/reviews`

```bash
curl "http://localhost:8005/v1/recognitions/reviews?page=1&page_size=20" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response (200 OK)**
```json
{
  "data": [
    {
      "review_id": "990e8400-e29b-41d4-a716-446655440004",
      "reviewer_id": "880e8400-e29b-41d4-a716-446655440000",
      "receiver_id": "550e8400-e29b-41d4-a716-446655440000",
      "comment": "Excellent work on the Q1 project.",
      "category_tags": [
        { "category_id": "770e8400-e29b-41d4-a716-446655440001", "category_code": "INNOVATION", "multiplier_snapshot": 1.4 },
        { "category_id": "770e8400-e29b-41d4-a716-446655440002", "category_code": "TEAMWORK",   "multiplier_snapshot": 1.2 }
      ],
      "category_ids":   ["770e8400-e29b-41d4-a716-446655440001", "770e8400-e29b-41d4-a716-446655440002"],
      "category_codes": ["INNOVATION", "TEAMWORK"],
      "raw_points": 2.6,
      "image_url": null,
      "video_url": null,
      "status_id": "aa0e8400-e29b-41d4-a716-446655440005",
      "review_at":  "2026-02-06T10:30:00.000Z",
      "created_at": "2026-02-06T10:30:00.000Z",
      "created_by": "880e8400-e29b-41d4-a716-446655440000",
      "updated_at": "2026-02-06T10:30:00.000Z",
      "updated_by": "880e8400-e29b-41d4-a716-446655440000"
    }
  ],
  "pagination": {
    "current_page": 1,
    "per_page": 20,
    "total": 150,
    "total_pages": 8,
    "has_next": true,
    "has_previous": false
  }
}
```

> **raw_points** above = (1.4 + 1.2) × reviewer_weight(1.0) = **2.6**

#### Create Review — `POST /v1/recognitions/reviews`

Steps: call `GET /v1/recognitions/review-categories` first to obtain valid `category_id` UUIDs, then submit the review.

```bash
curl -X POST http://localhost:8005/v1/recognitions/reviews \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver_id":  "550e8400-e29b-41d4-a716-446655440000",
    "category_ids": [
      "770e8400-e29b-41d4-a716-446655440001",
      "770e8400-e29b-41d4-a716-446655440002"
    ],
    "comment": "Excellent work on the Q1 project. Great collaboration and technical skills."
  }'
```

**Response (201 Created)** — same shape as the list item above.

#### Update Review — `PUT /v1/recognitions/reviews/{id}`

At least one field required. Supplying `category_ids` replaces all existing tags and triggers points recalculation; the receiver's wallet is adjusted by the delta.

```bash
curl -X PUT http://localhost:8005/v1/recognitions/reviews/990e8400-e29b-41d4-a716-446655440004 \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "comment": "Updated: outstanding performance throughout the quarter."
  }'
```

---

## Points Calculation

```
raw_points = sum(category_multipliers) × reviewer_weight
```

| Input | Source |
|---|---|
| `category_multipliers` | Summed from each selected `review_categories.multiplier` value |
| `reviewer_weight` | Resolved from `roles.reviewer_weight` for the reviewer's highest-priority role |

**Example:** selecting INNOVATION (1.4) + TEAMWORK (1.2) with a reviewer_weight of 1.0 gives `raw_points = 2.6`.

Multipliers are frozen as snapshots in `review_category_tags` at write time, so historical point totals remain reproducible even if an admin later edits a category's multiplier.

> **Note:** The README previously showed a formula including `rating` and `seasonal_multiplier`. These fields are not part of the current points calculation — `rating` is stored for display purposes only, and `seasonal_multiplier` is not currently implemented in the codebase.

---

## Caching Strategy

The service uses a two-tier cache: **L1** (in-process Python dict, sub-millisecond) backed by **L2** (Redis). If Redis is unavailable at startup, caching is disabled and all reads fall through to the database.

| Entity | Cache Key Pattern | TTL (Redis) | L1 TTL | Invalidation Trigger |
|---|---|---|---|---|
| Review list (per user) | `recognition:reviews:{user_id}:{page}:{limit}` | 60 s | 30 s | Any review create or update involving the user |
| Category list | `recognition:categories:{page}:{limit}:{active}` | 3600 s | 300 s | Any category create or update |
| Single category | `recognition:category:{category_id}` | 3600 s | 300 s | Any category create or update |
| Role weight | `recognition:role_weight:{role_code}` | 3600 s | 300 s | TTL expiry only (roles rarely change) |
| Team headcount | `recognition:team_count:{department_id}` | 300 s | 60 s | TTL expiry only (acceptable staleness for quota) |

`GET /v1/recognitions/reviews/{id}` (single review) is **not cached** because it is access-control sensitive — the same review_id returns different 200/403 responses depending on the caller.

---

## Access Control

### Review Categories
- **GET** — any authenticated user
- **POST / PUT** — HR_ADMIN or SUPER_ADMIN only

### Reviews
- **GET (list)** — EMPLOYEE/MANAGER see only their own given/received reviews; HR_ADMIN/SUPER_ADMIN see all
- **GET (single)** — reviewer, receiver, HR_ADMIN, or SUPER_ADMIN
- **POST** — EMPLOYEE, MANAGER, HR_ADMIN, or SUPER_ADMIN (cannot self-review)
- **PUT** — review creator, HR_ADMIN, or SUPER_ADMIN

---

## Business Rules

| Rule | Detail | Error |
|---|---|---|
| No self-review | Reviewer and receiver must differ | 422 |
| Active reviewer | Reviewer account must be ACTIVE | 403 |
| Active receiver | Receiver account must be ACTIVE | 422 |
| One review per pair per month | Cannot re-review the same person in the same calendar month | 422 |
| Monthly quota | Non-privileged users can submit at most N reviews/month, where N = active teammate count | 422 |
| Comment length | 10–2000 characters | 422 |
| Category count | 1–5 unique category UUIDs per review | 422 |
| URL length | Max 500 characters | 422 |

---

## Error Responses

All errors follow a standard envelope:

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Review not found",
    "timestamp": "2026-02-06T10:30:00.000Z",
    "path": "/v1/recognitions/reviews/bad-id"
  }
}
```

| Status | Code | Typical Cause |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Malformed request body |
| 401 | `UNAUTHORIZED` | Missing or expired token |
| 403 | `FORBIDDEN` | Insufficient role permissions or inactive account |
| 404 | `RESOURCE_NOT_FOUND` | Review or category not found |
| 409 | `CONFLICT` | Duplicate `category_code` or `category_name` |
| 422 | `VALIDATION_ERROR` | Business rule violation |
| 429 | `RATE_LIMIT_EXCEEDED` | Too many requests |
| 503 | `SERVICE_UNAVAILABLE` | Auth service unreachable |

---

## File Structure

```
recognition-service/
├── main.py               # FastAPI app, middleware, routers, OTel setup
├── requirements.txt
├── schema.prisma         # Prisma schema
├── .env                  # Environment variables (not in repo)
└── src/
    ├── prisma/
    │   └── client.py         # Prisma client singleton with retry
    ├── recognition/
    │   ├── router.py         # Route definitions + OpenAPI extras
    │   ├── service.py        # Business logic (RecognitionService)
    │   ├── schemas.py        # Pydantic request / response models
    │   ├── points_engine.py  # Stateless points calculation
    │   └── __init__.py
    ├── digest/
    │   ├── router.py         # Digest endpoints
    │   └── worker.py         # Background digest_worker_loop task
    ├── notifications/
    │   ├── service.py        # Notification creation
    │   ├── email_sender.py   # SMTP email delivery
    │   ├── redis_client.py   # Redis connect/disconnect helpers
    │   └── schemas.py        # NotificationType enum
    ├── wallet/
    │   └── service.py        # credit_wallet_from_review, adjust_wallet_for_review_update
    └── common/
        ├── dependencies.py   # Auth dependency + require_roles()
        ├── middleware.py     # Rate limiting, error handlers
        ├── cache.py          # Two-tier cache helpers + TTL constants
        └── route_registry.py # Dynamic route registration with RBAC
```

---

## Production Deployment

- Remove `--reload` from the uvicorn command
- Restrict `FRONTEND_CORS_ORIGINS` to production domains only
- Deploy behind an HTTPS reverse proxy (nginx / Caddy)
- Use a process supervisor (systemd, Gunicorn with uvicorn workers, or a container orchestrator)
- Point `OTEL_EXPORTER_OTLP_ENDPOINT` at your Jaeger/Tempo collector
- Ensure the `REVIEW_ACTIVE` status row exists in `status_master` before first deployment
- Add composite DB indexes on `(reviewer_id, review_at)` and `(receiver_id, review_at)` for list query performance

---

## License

Internal use only — Employee Management & Rewards System

---

**Contract Compliance:** ✅ Fully Compliant with API Contract v0.1.1  