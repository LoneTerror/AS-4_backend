# 🔐 Auth Service

> **Employee Rewards System — Authentication & Authorization Microservice**
>
> A production-ready auth service built with **FastAPI**, **Prisma ORM**, and **PostgreSQL**. Handles JWT-based login, refresh tokens, role-based access control, and password reset via email.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
- [Database Schema](#database-schema)
- [API Endpoints](#api-endpoints)
- [Authentication Flow](#authentication-flow)
- [Security Design](#security-design)
- [Role-Based Access Control (RBAC)](#role-based-access-control-rbac)
- [Password Reset Flow](#password-reset-flow)
- [Middleware](#middleware)
- [Error Handling](#error-handling)
- [Environment Variables](#environment-variables)
- [Getting Started](#getting-started)
- [Testing the API](#testing-the-api)

---

## Overview

The **Auth Service** is a standalone microservice responsible for:

- Authenticating employees via email/username + password
- Issuing short-lived JWT access tokens (30 min) and long-lived refresh tokens (7 days)
- Enforcing role-based access control on protected routes
- Enabling inter-service token validation for other microservices
- Handling secure password reset via time-limited JWT tokens sent by email

It runs on **port 8001** and exposes a versioned REST API under `/v1/auth`.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI (Python 3.10+) |
| ORM | Prisma (Python client) |
| Database | PostgreSQL |
| Authentication | JWT via `python-jose` (HS256) |
| Password Hashing | bcrypt (rounds=12) |
| Refresh Token Hashing | SHA-256 |
| Email | SMTP (Gmail) via `smtplib` |
| Runtime | Uvicorn (ASGI) |
| Frontend (client) | Next.js 14 (App Router) |

---

## Project Structure

```
src/
├── auth/
│   ├── router.py          # Route definitions + request handlers
│   ├── service.py         # Business logic for all auth operations
│   ├── schemas.py         # Pydantic request/response models
│   └── dependencies.py    # get_current_user, require_roles()
├── core/
│   ├── security.py        # JWT, bcrypt, SHA-256 utilities
│   ├── email_utils.py     # SMTP email sending (reset + confirmation)
│   └── middleware.py      # Rate limiting, request ID, error handlers
├── prisma/
│   └── client.py          # Prisma client singleton
└── main.py                # FastAPI app, CORS, lifespan, OpenAPI config
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        Browser / Next.js :3000               │
└───────────────────────────────┬──────────────────────────────┘
                                │ HTTP Requests
                                ▼
┌──────────────────────────────────────────────────────────────┐
│                    FastAPI Auth Service :8001                 │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │  Middleware  │  │   Router     │  │   Dependencies      │ │
│  │  • Rate Limit│  │  /v1/auth/*  │  │  • get_current_user │ │
│  │  • Request ID│  │              │  │  • require_roles()  │ │
│  │  • Error fmt │  └──────┬───────┘  └─────────────────────┘ │
│  └─────────────┘         │                                  │
│                           ▼                                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                    service.py                          │  │
│  │  authenticate_user │ refresh_access_token │ logout    │  │
│  │  create_employee   │ validate_token                   │  │
│  │  request_password_reset │ reset_password              │  │
│  └───────────────────────────────────────────────────────┘  │
│                           │                                  │
│  ┌────────────┐   ┌────────────────┐   ┌─────────────────┐  │
│  │ security.py│   │  email_utils   │   │   Prisma ORM    │  │
│  │ • JWT      │   │  • SMTP send   │   │  • Type-safe DB │  │
│  │ • bcrypt   │   │  • Reset email │   │    queries      │  │
│  │ • SHA-256  │   │  • Confirm     │   └────────┬────────┘  │
│  └────────────┘   └────────────────┘            │           │
└─────────────────────────────────────────────────┼───────────┘
                                                  │
                                                  ▼
                                    ┌─────────────────────────┐
                                    │       PostgreSQL         │
                                    │  employees               │
                                    │  refresh_tokens          │
                                    │  employee_roles          │
                                    │  roles                   │
                                    │  departments             │
                                    │  designations            │
                                    │  wallets                 │
                                    │  status_master           │
                                    └─────────────────────────┘
```

### Inter-Service Communication

Other microservices (e.g., Recognition Service on `:8005`) validate tokens by calling:

```
POST /v1/auth/validate
Body: { "token": "Bearer JWT" }
```

This returns the user's ID, email, roles, and department — no shared secret needed.

---

## Database Schema

### Key Tables Used by Auth Service

#### `employees`
| Column | Type | Notes |
|---|---|---|
| `employee_id` | UUID (PK) | Auto-generated |
| `username` | String | Unique |
| `email` | String | Unique, used for login |
| `password_hash` | String | bcrypt hash (rounds=12) |
| `designation_id` | UUID (FK) | → designations |
| `department_id` | UUID (FK) | → departments |
| `manager_id` | UUID (FK, nullable) | → employees (self-ref) |
| `status_id` | UUID (FK) | → status_master |
| `date_of_joining` | DateTime | Set on creation |
| `created_by` | String | Employee ID who created |
| `updated_by` | String | Employee ID who last updated |
| `updated_at` | DateTime | Last update timestamp |

#### `refresh_tokens`
| Column | Type | Notes |
|---|---|---|
| `token_id` | UUID (PK) | UUID v4, sent to client |
| `token_hash` | String | SHA-256 hash of token secret |
| `employee_id` | UUID (FK) | → employees |
| `expires_at` | DateTime | 7 days from creation |
| `revoked_at` | DateTime (nullable) | Set on logout or password reset |
| `created_at` | DateTime | |
| `updated_at` | DateTime | |

#### `employee_roles`
| Column | Type | Notes |
|---|---|---|
| `employee_id` | UUID (FK) | → employees |
| `role_id` | UUID (FK) | → roles |
| `is_active` | Boolean | Only active roles are included in JWT |

#### `roles`
| Column | Type | Notes |
|---|---|---|
| `role_id` | UUID (PK) | |
| `role_code` | String | e.g., `SUPER_ADMIN`, `HR_ADMIN`, `EMPLOYEE` |

#### `wallets`
Auto-created for every new employee with 0 points.

| Column | Type | Notes |
|---|---|---|
| `employee_id` | UUID (FK) | → employees |
| `available_points` | Int | Starts at 0 |
| `redeemed_points` | Int | Starts at 0 |
| `total_earned_points` | Int | Starts at 0 |

---

## API Endpoints

Base URL: `http://localhost:8001/v1/auth`

Swagger UI: `http://localhost:8001/v1/docs`

### Summary

| Method | Endpoint | Auth Required | Role Required | Description |
|---|---|---|---|---|
| `POST` | `/login` | ❌ | — | Login with email/username + password |
| `POST` | `/refresh` | ❌ | — | Get new access token using refresh token |
| `POST` | `/logout` | ✅ Bearer | — | Revoke refresh token |
| `POST` | `/signup` | ✅ Bearer | SUPER_ADMIN or HR_ADMIN | Create new employee account |
| `POST` | `/validate` | ❌ | — | Validate JWT (for other microservices) |
| `POST` | `/forgot-password` | ❌ | — | Request password reset email |
| `POST` | `/reset-password` | ❌ | — | Reset password using email token |

---

### `POST /login`

Authenticates an employee by email or username and returns JWT tokens.

**Request Body:**
```json
{
  "username": "user@company.com",
  "password": "SecurePass123"
}
```

> `username` accepts both email address and username string — handled in service layer.

**Success Response `200 OK`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "550e8400-e29b-41d4-a716-446655440000||<64-byte-secret>",
  "token_type": "Bearer",
  "expires_in": 1800,
  "employee": {
    "employee_id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "john.doe",
    "email": "john.doe@company.com",
    "designation_id": "...",
    "department_id": "..."
  }
}
```

**Error Responses:**
- `401` — Invalid credentials (wrong password or user not found)
- `429` — Rate limit exceeded

---

### `POST /refresh`

Issues a new access token using a valid refresh token. The same refresh token is returned (not rotated).

**Request Body:**
```json
{
  "refresh_token": "550e8400-e29b-41d4-a716-446655440000||<64-byte-secret>"
}
```

**Success Response `200 OK`:** Same shape as `/login` response with new `access_token`.

**Error Responses:**
- `401` — Token not found, expired, revoked, or invalid format/signature

---

### `POST /logout`

Revokes the provided refresh token in the database. Requires a valid access token in the `Authorization` header.

**Headers:**
```
Authorization: Bearer <access_token>
```

**Request Body:**
```json
{
  "refresh_token": "550e8400-e29b-41d4-a716-446655440000||<64-byte-secret>"
}
```

**Success Response `200 OK`:**
```json
{
  "message": "Logged out successfully"
}
```

> If the refresh token belongs to a different user, logout silently succeeds — this prevents token ownership enumeration.

---

### `POST /signup`

Creates a new employee account and automatically creates a wallet with 0 points. Restricted to `SUPER_ADMIN` and `HR_ADMIN` roles.

**Headers:**
```
Authorization: Bearer <access_token>
```

**Request Body:**
```json
{
  "username": "jane.doe",
  "email": "jane.doe@company.com",
  "password": "SecurePass123",
  "designation_id": "uuid-here",
  "department_id": "uuid-here",
  "manager_id": "uuid-here"
}
```

> `manager_id` is optional.

**Success Response `200 OK`:**
```json
{
  "employee_id": "uuid-here",
  "username": "jane.doe",
  "email": "jane.doe@company.com",
  "designation_id": "uuid-here",
  "department_id": "uuid-here"
}
```

**Error Responses:**
- `400` — Manager / designation / department not found
- `401` — Missing or invalid token
- `403` — Insufficient role (not SUPER_ADMIN or HR_ADMIN)
- `500` — ACTIVE status not found in `status_master`

---

### `POST /validate`

Validates a JWT access token and returns decoded user information. Designed for inter-service communication — no authentication required to call this endpoint.

**Request Body:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Success Response `200 OK`:**
```json
{
  "valid": true,
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "john.doe@company.com",
  "roles": ["EMPLOYEE", "HR_ADMIN"],
  "department_id": "uuid-here"
}
```

**Invalid Token Response `200 OK`:**
```json
{
  "valid": false,
  "error": "Invalid or expired token"
}
```

> Always returns `200`. The `valid` boolean indicates result. Other services should check `valid: true` before proceeding.

---

### `POST /forgot-password`

Sends a password reset email containing a short-lived JWT token (15 min). Always returns a success message regardless of whether the email exists — this prevents email enumeration attacks.

**Request Body:**
```json
{
  "email": "john.doe@company.com"
}
```

**Success Response `200 OK`:**
```json
{
  "message": "If your email is registered, you will receive a password reset link shortly."
}
```

> The same response is returned whether the email exists or not.

---

### `POST /reset-password`

Resets the employee's password using the JWT reset token from the email. On success, **all existing refresh tokens are revoked** — forcing re-login on all devices.

**Request Body:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "new_password": "NewSecurePass123"
}
```

**Success Response `200 OK`:**
```json
{
  "message": "Password reset successful. Please login with your new password."
}
```

**Error Responses:**
- `400` — Token expired (15 min), invalid signature, wrong purpose, or user not found

---

## Authentication Flow

### Token Architecture

The service uses a **dual-token strategy**:

```
Access Token (JWT)                  Refresh Token (Opaque)
─────────────────────────────────   ────────────────────────────────────
• Algorithm: HS256                  • Format: {uuid4}||{urlsafe_64_bytes}
• Expiry: 30 minutes                • Expiry: 7 days
• Payload: sub, email,              • Stored: SHA-256 hash in DB
           roles, department_id     • Used to: get new access tokens
• Used for: API authorization       • Revoked on: logout, password reset
```

### Refresh Token Design

The refresh token sent to the client has the format:

```
<token_id>||<token_secret>
```

- `token_id` — UUID v4, used as the primary key to look up the token row in the DB
- `token_secret` — 64-byte URL-safe random string, never stored directly
- `||` — separator guaranteed not to appear in either part

In the database, only `SHA-256(token_secret)` is stored. This means even if the DB is compromised, the raw refresh tokens cannot be recovered.

### JWT Access Token Payload

```json
{
  "sub": "employee-uuid",
  "email": "user@company.com",
  "roles": ["HR_ADMIN"],
  "department_id": "dept-uuid",
  "iat": 1708084200,
  "exp": 1708086000,
  "iss": "employee-rewards-system"
}
```

### JWT Reset Token Payload

```json
{
  "sub": "employee-uuid",
  "email": "user@company.com",
  "purpose": "password_reset",
  "iat": 1708084200,
  "exp": 1708085100,
  "iss": "employee-rewards-system"
}
```

> The `purpose` claim is **required** and must equal `"password_reset"`. Using an access token on the reset endpoint will fail even if the signature is valid.

---

## Security Design

### Password Hashing

Passwords are hashed using **bcrypt with cost factor 12**. This is compatible with Node.js `bcryptjs` for cross-service use.

```python
# Hashing
bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12))

# Verification
bcrypt.checkpw(plain_password.encode("utf-8"), stored_hash.encode("utf-8"))
```

### Refresh Token Hashing

Refresh token secrets use **SHA-256** (not bcrypt) because:
- They are already 64 bytes of high entropy (equivalent to 512 bits of randomness)
- bcrypt is unnecessary for high-entropy random secrets
- SHA-256 is orders of magnitude faster for lookup-heavy operations

```python
hashlib.sha256(token_secret.encode("utf-8")).hexdigest()
```

### Security Practices

| Practice | Implementation |
|---|---|
| Email enumeration prevention | `/forgot-password` always returns `200` with identical message |
| Token ownership verification | Logout checks `employee_id` matches before revoking |
| Silent fail on wrong ownership | No 403 on cross-user logout — prevents token existence detection |
| Session revocation on reset | All refresh tokens revoked when password is reset |
| Purpose-bound reset tokens | `purpose` claim blocks access tokens from being used for reset |
| Timing-safe comparison | bcrypt's `checkpw` is timing-safe for password verification |
| No plaintext token storage | Only SHA-256 hash stored in `refresh_tokens` table |

---

## Role-Based Access Control (RBAC)

### Available Roles

| Role Code | Description |
|---|---|
| `SUPER_ADMIN` | Full access — bypasses all role checks |
| `HR_ADMIN` | Can create new employees |
| `EMPLOYEE` | Default role — basic access only |

### How It Works

The `require_roles()` dependency in `dependencies.py` is used as a FastAPI `Depends`:

```python
@router.post("/signup")
async def signup(
    payload: SignUpRequest,
    user = Depends(require_roles("SUPER_ADMIN", "HR_ADMIN"))
):
    ...
```

Internally, it:

1. Extracts the Bearer token from the `Authorization` header
2. Decodes the JWT and reads the `roles` array from the payload
3. If `SUPER_ADMIN` is in roles → **always allowed** (bypass)
4. Otherwise checks if the user has **any** of the allowed roles
5. Raises `403 FORBIDDEN` if no matching role found

### Role Assignment

Roles are stored in the `employee_roles` join table. Only rows with `is_active: true` are included in the JWT at login/refresh time.

```python
# At login — roles are embedded in the JWT
roles = [er.roles.role_code for er in emp_roles if er.roles]

# At refresh — roles are re-fetched fresh from the DB
roles_relation = await db.employee_roles.find_many(
    where={"employee_id": user.employee_id, "is_active": True},
    include={"roles": True}
)
```

> This means role changes take effect on the **next token refresh** — no need to re-login.

---

## Password Reset Flow

```
1. User submits email to POST /forgot-password
        │
        ▼
2. Lookup employee by email in PostgreSQL
        │
    ┌───┴──────────────────────┐
    │ Found                    │ Not Found
    ▼                          ▼
3. create_reset_token()    4. Return same 200 message
   JWT, 15 min,               (enumeration prevention)
   purpose=password_reset
        │
        ▼
5. Send email via Gmail SMTP
   Contains: reset link + raw token (for Swagger testing)
        │
        ▼
6. User copies token from email
        │
        ▼
7. POST /reset-password { token, new_password }
        │
        ▼
8. decode_reset_token():
   • Verify HS256 signature
   • Check expiration (15 min)
   • Validate purpose == "password_reset"
        │
        ▼
9. Verify employee still exists + email matches
        │
        ▼
10. hash_password(new_password) — bcrypt rounds=12
        │
        ▼
11. UPDATE employees SET password_hash = ...
        │
        ▼
12. REVOKE all refresh_tokens for this employee
    (forces re-login on all devices)
        │
        ▼
13. Send confirmation email
        │
        ▼
14. Return 200 { message: "Password reset successful..." }
```

---

## Middleware

Defined in `src/core/middleware.py` and applied globally via `app.middleware("http")`.

### Request ID

Every request is assigned a unique `X-Request-ID`:
- Uses the client-provided `X-Request-ID` header if present
- Otherwise generates a new UUID v4
- Stored on `request.state.request_id` for use in error responses
- Returned in the response headers

### Rate Limiting

In-memory sliding window rate limiter:
- **Limit:** 1,000 requests per IP
- **Window:** 1 hour (3,600 seconds)
- **Algorithm:** Sliding window (timestamps stored per IP)

Response headers on every request:
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 847
X-RateLimit-Reset: 1708087800
```

> This is an in-memory store — it resets on server restart and does not work across multiple instances. For production multi-instance deployments, replace with Redis-backed rate limiting.

---

## Error Handling

All errors follow a consistent contract format:

```json
{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Invalid or expired token",
    "timestamp": "2026-02-17T10:30:00.000000+00:00",
    "path": "/v1/auth/login",
    "request_id": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

### Error Code Mapping

| HTTP Status | Error Code | Typical Cause |
|---|---|---|
| `400` | `INVALID_REQUEST` | Bad token, missing field, invalid FK |
| `401` | `UNAUTHORIZED` | Wrong password, expired token, invalid JWT |
| `403` | `FORBIDDEN` | Insufficient role |
| `404` | `RESOURCE_NOT_FOUND` | Entity not found |
| `409` | `CONFLICT` | Duplicate email/username |
| `422` | `VALIDATION_ERROR` | Pydantic validation failure |
| `429` | `RATE_LIMIT_EXCEEDED` | Too many requests |
| `500` | `INTERNAL_ERROR` | Unexpected server error |
| `503` | `SERVICE_UNAVAILABLE` | Service temporarily unavailable |

### Validation Errors

Pydantic validation failures return structured field-level errors:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": {
      "email": ["value is not a valid email address"],
      "password": ["field required"]
    },
    "timestamp": "...",
    "path": "/v1/auth/login",
    "request_id": "..."
  }
}
```

---

## Environment Variables

Create a `.env` file in the project root:

```bash
# ─── Required ──────────────────────────────────────────────
SECRET_KEY=your-super-secret-key-minimum-32-characters-long

# ─── Database ──────────────────────────────────────────────
DATABASE_URL=postgresql://user:password@localhost:5432/employee_rewards

# ─── Email (Gmail SMTP) ────────────────────────────────────
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-app-gmail@gmail.com
SMTP_PASSWORD=abcd efgh ijkl mnop       # Gmail App Password (not your login password)
SMTP_FROM_EMAIL=noreply@yourcompany.com

# ─── Frontend ──────────────────────────────────────────────
FRONTEND_URL=http://localhost:3000      # Used to construct reset links in emails
```

### Generating a SECRET_KEY

```bash
# Python
python -c "import secrets; print(secrets.token_hex(32))"

# OpenSSL
openssl rand -hex 32
```

### Gmail App Password Setup

Gmail requires an **App Password** (not your regular password) for SMTP access:

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Enable **2-Step Verification**
3. Go to **App passwords**
4. Select **Mail** → **Other (Custom name)** → Name it "Employee Rewards"
5. Copy the 16-character password → paste as `SMTP_PASSWORD`

---

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL 14+
- Node.js (for Prisma CLI)

### Installation

```bash
# 1. Clone and enter the directory
cd auth-service

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
# Edit .env with your values

# 5. Generate Prisma client
prisma generate

# 6. Run database migrations
prisma migrate deploy

# 7. Start the server
uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload
```

### Running in Production

```bash
uvicorn src.main:app \
  --host 0.0.0.0 \
  --port 8001 \
  --workers 4 \
  --no-access-log
```

---

## Testing the API

### Swagger UI

The interactive API docs are available at:

```
http://localhost:8001/v1/docs
```

Use the **BearerAuth** button (🔓) to paste your access token for protected endpoints.

### Quick Test Sequence

```bash
# 1. Login
curl -X POST http://localhost:8001/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin@company.com", "password": "password123"}'

# 2. Copy the access_token from the response

# 3. Create a new employee (requires SUPER_ADMIN or HR_ADMIN role)
curl -X POST http://localhost:8001/v1/auth/signup \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{
    "username": "jane.doe",
    "email": "jane@company.com",
    "password": "SecurePass123",
    "designation_id": "<uuid>",
    "department_id": "<uuid>"
  }'

# 4. Refresh token
curl -X POST http://localhost:8001/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<your_refresh_token>"}'

# 5. Validate token (for inter-service use)
curl -X POST http://localhost:8001/v1/auth/validate \
  -H "Content-Type: application/json" \
  -d '{"token": "<access_token>"}'

# 6. Request password reset
curl -X POST http://localhost:8001/v1/auth/forgot-password \
  -H "Content-Type: application/json" \
  -d '{"email": "jane@company.com"}'

# 7. Reset password (token from email/console)
curl -X POST http://localhost:8001/v1/auth/reset-password \
  -H "Content-Type: application/json" \
  -d '{"token": "<reset_jwt>", "new_password": "NewPass456"}'

# 8. Logout
curl -X POST http://localhost:8001/v1/auth/logout \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{"refresh_token": "<your_refresh_token>"}'
```

### Frontend Integration

The Next.js frontend connects to this service at `http://localhost:8001`. Store the tokens from the login response in `localStorage`:

```typescript
localStorage.setItem('access_token', data.access_token)
localStorage.setItem('refresh_token', data.refresh_token)
localStorage.setItem('user', JSON.stringify(data.employee))
```

For authenticated requests, include the access token in the `Authorization` header:

```typescript
headers: {
  'Authorization': `Bearer ${localStorage.getItem('access_token')}`
}
```

---

## CORS Configuration

The service allows requests from the following origins (configured in `main.py`):

```python
allow_origins=[
  "http://localhost:8005",  # Recognition microservice
  "http://localhost:3000",  # Next.js frontend (dev)
]
```

Add production origins here before deploying.

---

## OpenAPI / Swagger Customization

The default FastAPI Swagger UI uses `OAuth2PasswordBearer` which shows a username/password form. This service overrides the OpenAPI schema to use **BearerAuth** instead — matching the actual JWT flow:

```python
schema["components"]["securitySchemes"] = {
    "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
}
```

The custom schema is available at `http://localhost:8001/v1/openapi.json`.

---

*Auth Service — Employee Rewards System*
