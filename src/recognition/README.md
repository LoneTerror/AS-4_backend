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
- ✅ **Points Engine** — Stateless calculation: `rating × sum(category_multipliers) × reviewer_weight × seasonal_multiplier`
- ✅ **Wallet Integration** — Auto-credits receiver on review creation; adjusts delta on update
- ✅ **Audit Trail** — Full `created_by` / `updated_by` / `created_at` / `updated_at` on all writes
- ✅ **Pagination** — Consistent pagination metadata across all list endpoints
- ✅ **Standardised Error Handling** — Uniform error shape with HTTP status codes

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.115.0 |
| Database | PostgreSQL via Prisma ORM (prisma-client-py) |
| Auth | OAuth 2.0 Bearer Token (validated against Auth Service) |
| Python | 3.11+ |

---

## API Endpoints

All endpoints are prefixed with `/v1`.

### Review Categories

| Method | Endpoint | Description | Roles |
|--------|----------|-------------|-------|
| GET | `/v1/review-categories` | List categories (paginated) | EMPLOYEE, MANAGER, HR_ADMIN, SUPER_ADMIN |
| POST | `/v1/review-categories` | Create a new category | HR_ADMIN, SUPER_ADMIN |
| PUT | `/v1/review-categories/{id}` | Update an existing category | HR_ADMIN, SUPER_ADMIN |

### Reviews

| Method | Endpoint | Description | Roles |
|--------|----------|-------------|-------|
| GET | `/v1/reviews` | List reviews (paginated) | EMPLOYEE, MANAGER, HR_ADMIN, SUPER_ADMIN |
| GET | `/v1/reviews/{id}` | Get a specific review | All authenticated users |
| POST | `/v1/reviews` | Create a new review | EMPLOYEE, MANAGER |
| PUT | `/v1/reviews/{id}` | Update an existing review | Review owner, HR_ADMIN, SUPER_ADMIN |

---

## Installation

### Prerequisites

- Python 3.11+
- PostgreSQL database
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

---

## API Documentation

With the service running, visit:

- **Swagger UI** → http://localhost:8005/v1/docs
- **ReDoc** → http://localhost:8005/v1/redoc
- **OpenAPI JSON** → http://localhost:8005/v1/openapi.json

---

## Request & Response Examples

### Review Categories

#### List Categories — `GET /v1/review-categories`

```bash
curl http://localhost:8005/v1/review-categories \
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

#### Create Category — `POST /v1/review-categories`

> `is_active` is not accepted on creation — all new categories are active by default. Use `PUT` to deactivate.

```bash
curl -X POST http://localhost:8005/v1/review-categories \
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

#### Update Category — `PUT /v1/review-categories/{id}`

At least one field required. `is_active` is the only way to deactivate a category after creation.

> ⚠️ Changing `multiplier` only affects **future** reviews. Historical reviews are unaffected — each review freezes multiplier values as snapshots at write time.

```bash
curl -X PUT http://localhost:8005/v1/review-categories/770e8400-e29b-41d4-a716-446655440001 \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "multiplier": 1.5,
    "is_active": false
  }'
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

#### List Reviews — `GET /v1/reviews`

```bash
curl "http://localhost:8005/v1/reviews?page=1&page_size=20" \
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
      "rating": 4,
      "comment": "Excellent work on the Q1 project.",
      "category_tags": [
        { "category_id": "770e8400-e29b-41d4-a716-446655440001", "category_code": "INNOVATION", "multiplier_snapshot": 1.4 },
        { "category_id": "770e8400-e29b-41d4-a716-446655440002", "category_code": "TEAMWORK",   "multiplier_snapshot": 1.2 }
      ],
      "category_ids":   ["770e8400-e29b-41d4-a716-446655440001", "770e8400-e29b-41d4-a716-446655440002"],
      "category_codes": ["INNOVATION", "TEAMWORK"],
      "raw_points": 15.68,
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

#### Create Review — `POST /v1/reviews`

Steps: call `GET /v1/review-categories` first to obtain valid `category_id` UUIDs, then submit the review.

```bash
curl -X POST http://localhost:8005/v1/reviews \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver_id":  "550e8400-e29b-41d4-a716-446655440000",
    "rating":       4,
    "category_ids": [
      "770e8400-e29b-41d4-a716-446655440001",
      "770e8400-e29b-41d4-a716-446655440002"
    ],
    "comment": "Excellent work on the Q1 project. Great collaboration and technical skills."
  }'
```

**Response (201 Created)** — same shape as the list item above.

#### Update Review — `PUT /v1/reviews/{id}`

At least one field required. Supplying `category_ids` replaces all existing tags and triggers points recalculation; the receiver's wallet is adjusted by the delta.

```bash
curl -X PUT http://localhost:8005/v1/reviews/990e8400-e29b-41d4-a716-446655440004 \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "rating": 5,
    "comment": "Updated: outstanding performance throughout the quarter."
  }'
```

---

## Points Calculation

```
raw_points = rating × sum(category_multipliers) × reviewer_weight × seasonal_multiplier
```

| Input | Source |
|---|---|
| `rating` | Submitted by reviewer (1–5) |
| `category_multipliers` | Summed from selected `review_categories.multiplier` values |
| `reviewer_weight` | Resolved from `roles.reviewer_weight` for the reviewer's highest-priority role |
| `seasonal_multiplier` | Resolved from `seasonal_multipliers` for the current quarter |

Multipliers are frozen as snapshots in `review_category_tags` at write time, so historical point totals remain reproducible even if an admin later edits a category.

---

## Access Control

### Review Categories
- **GET** — any authenticated user
- **POST / PUT** — HR_ADMIN or SUPER_ADMIN only

### Reviews
- **GET (list)** — EMPLOYEE/MANAGER see only their own given/received reviews; HR_ADMIN/SUPER_ADMIN see all
- **GET (single)** — reviewer, receiver, HR_ADMIN, or SUPER_ADMIN
- **POST** — EMPLOYEE or MANAGER (cannot self-review)
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
| Rating range | 1–5 inclusive | 422 |
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
    "path": "/v1/reviews/bad-id"
  }
}
```

| Status | Code | Typical Cause |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Malformed request body |
| 401 | `UNAUTHORIZED` | Missing or expired token |
| 403 | `FORBIDDEN` | Insufficient role permissions |
| 404 | `RESOURCE_NOT_FOUND` | Review or category not found |
| 409 | `CONFLICT` | Duplicate `category_code` or `category_name` |
| 422 | `VALIDATION_ERROR` | Business rule violation |
| 503 | `SERVICE_UNAVAILABLE` | Auth service unreachable |

---

## File Structure

```
recognition-service/
├── main.py               # FastAPI app, middleware, routers
├── requirements.txt
├── schema.prisma         # Prisma schema
├── .env                  # Environment variables (not in repo)
└── src/
    ├── prisma/
    │   └── client.py     # Prisma client singleton
    └── recognition/
        ├── router.py         # Route definitions + OpenAPI extras
        ├── service.py        # Business logic (RecognitionService)
        ├── schemas.py        # Pydantic request / response models
        ├── dependencies.py   # Auth dependency + require_roles()
        └── points_engine.py  # Stateless points calculation
```

---

## Production Deployment

- Remove `--reload` from the uvicorn command
- Restrict `allow_origins` in CORS to production domains
- Deploy behind an HTTPS reverse proxy (nginx / Caddy)
- Use a process supervisor (systemd, Gunicorn, or a container orchestrator)
- Point the health check at `/v1/docs` or add a dedicated `/health` route

---

## License

Internal use only — Employee Management & Rewards System

---

**Contract Compliance:** ✅ Fully Compliant with API Contract v0.1.1