# Recognition Service API

**Version:** 1.0.0  
**API Version:** v1  
**Contract Version:** 0.1.1

## Overview

This is the Recognition/Review microservice for the Employee Management & Rewards System. It provides a fully contract-compliant REST API for managing performance reviews and employee recognition.

## Features

- ✅ **Contract-Compliant**: Fully implements the API contract specifications (v0.1.1)
- ✅ **Role-Based Access Control**: Granular permissions for EMPLOYEE, MANAGER, HR_ADMIN, SUPER_ADMIN
- ✅ **Comprehensive Validation**: Input validation matching contract requirements
- ✅ **Audit Trail**: Full audit logging with created_by/updated_by fields
- ✅ **Pagination**: Contract-compliant pagination with metadata
- ✅ **Error Handling**: Standardized error responses with proper HTTP status codes

## API Endpoints

All endpoints are prefixed with `/v1`

### Reviews

| Method | Endpoint | Description | Auth Required | Roles |
|--------|----------|-------------|---------------|-------|
| GET | `/v1/reviews` | List reviews (paginated) | ✓ | EMPLOYEE, MANAGER, HR_ADMIN, SUPER_ADMIN |
| GET | `/v1/reviews/{id}` | Get specific review | ✓ | All authenticated users |
| POST | `/v1/reviews` | Create new review | ✓ | EMPLOYEE, MANAGER |
| PUT | `/v1/reviews/{id}` | Update existing review | ✓ | Review owner, HR_ADMIN, SUPER_ADMIN |

## Tech Stack

- **Framework**: FastAPI 0.115.0
- **Database**: PostgreSQL (via Prisma ORM)
- **Authentication**: OAuth 2.0 Bearer Token
- **Python**: 3.11+

## Installation

### Prerequisites

- Python 3.11 or higher
- PostgreSQL database
- Authentication service (for token validation)

### Setup Steps

1. **Clone and navigate to the project**
   ```bash
   cd recognition-service
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   
   Create a `.env` file:
   ```env
   DATABASE_URL="postgresql://user:password@host:port/database?sslmode=require"
   AUTH_SERVICE_URL="http://localhost:8001/v1/auth/validate"
   SECRET_KEY="your-secret-key-here"
   ALGORITHM="HS256"
   ACCESS_TOKEN_EXPIRE_MINUTES=30
   ```

5. **Generate Prisma Client**
   ```bash
   prisma generate
   ```

6. **Run database migrations** (if needed)
   ```bash
   prisma migrate deploy
   ```

7. **Start the service**
   ```bash
   python main.py
   ```
   
   Or using uvicorn directly:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8005 --reload
   ```

## API Documentation

Once running, visit:
- **Swagger UI**: http://localhost:8005/v1/docs
- **ReDoc**: http://localhost:8005/v1/redoc
- **OpenAPI JSON**: http://localhost:8005/v1/openapi.json

## Request/Response Examples

### Create Review (POST /v1/reviews)

**Request:**
```json
{
  "receiver_id": "550e8400-e29b-41d4-a716-446655440000",
  "rating": 4,
  "comment": "Excellent work on the Q1 project. Great collaboration and technical skills.",
  "image_url": "https://cdn.company.com/reviews/image123.jpg",
  "video_url": "https://cdn.company.com/reviews/video123.mp4"
}
```

**Response (201 Created):**
```json
{
  "review_id": "990e8400-e29b-41d4-a716-446655440004",
  "reviewer_id": "880e8400-e29b-41d4-a716-446655440000",
  "receiver_id": "550e8400-e29b-41d4-a716-446655440000",
  "rating": 4,
  "comment": "Excellent work on the Q1 project. Great collaboration and technical skills.",
  "image_url": "https://cdn.company.com/reviews/image123.jpg",
  "video_url": "https://cdn.company.com/reviews/video123.mp4",
  "status_id": "aa0e8400-e29b-41d4-a716-446655440005",
  "review_at": "2026-02-06T10:30:00.000Z",
  "created_at": "2026-02-06T10:30:00.000Z",
  "created_by": "880e8400-e29b-41d4-a716-446655440000",
  "updated_at": "2026-02-06T10:30:00.000Z",
  "updated_by": "880e8400-e29b-41d4-a716-446655440000"
}
```

### List Reviews (GET /v1/reviews?page=1&page_size=20)

**Response (200 OK):**
```json
{
  "data": [
    {
      "review_id": "990e8400-e29b-41d4-a716-446655440004",
      "reviewer_id": "880e8400-e29b-41d4-a716-446655440000",
      "receiver_id": "550e8400-e29b-41d4-a716-446655440000",
      "rating": 4,
      "comment": "Great work!",
      "image_url": null,
      "video_url": null,
      "status_id": "aa0e8400-e29b-41d4-a716-446655440005",
      "review_at": "2026-02-06T10:30:00.000Z",
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

## Authentication

All endpoints require authentication via Bearer token:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     http://localhost:8005/v1/reviews
```

## Access Control

### List Reviews
- **EMPLOYEE/MANAGER**: See only reviews they gave or received
- **HR_ADMIN/SUPER_ADMIN**: See all reviews

### Get Review
- **EMPLOYEE/MANAGER**: See only reviews they gave or received
- **HR_ADMIN/SUPER_ADMIN**: See any review

### Create Review
- **EMPLOYEE/MANAGER**: Can create reviews
- Cannot review themselves

### Update Review
- **Review Creator**: Can update their own reviews
- **HR_ADMIN/SUPER_ADMIN**: Can update any review

## Business Rules

1. **Self-Review Prevention**: Users cannot review themselves (422 error)
2. **Active Receiver Only**: Can only review active employees (422 error)
3. **Rating Range**: Must be 1-5 (validation error)
4. **Comment Length**: 10-2000 characters (validation error)
5. **URL Length**: Maximum 500 characters (validation error)

## Error Handling

The API returns standardized error responses:

### 400 Bad Request
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": {
      "rating": ["Rating must be between 1 and 5"]
    },
    "timestamp": "2026-02-06T10:30:00.000Z",
    "path": "/v1/reviews"
  }
}
```

### 401 Unauthorized
```json
{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Invalid or expired authentication token",
    "timestamp": "2026-02-06T10:30:00.000Z"
  }
}
```

### 403 Forbidden
```json
{
  "error": {
    "code": "FORBIDDEN",
    "message": "Insufficient permissions for this operation",
    "timestamp": "2026-02-06T10:30:00.000Z"
  }
}
```

### 404 Not Found
```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Review not found",
    "timestamp": "2026-02-06T10:30:00.000Z"
  }
}
```

### 422 Unprocessable Entity
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Self review not allowed",
    "timestamp": "2026-02-06T10:30:00.000Z"
  }
}
```

## File Structure

```
recognition-service/
├── main.py                 # FastAPI application entry point
├── requirements.txt        # Python dependencies
├── .env                   # Environment variables (not in repo)
├── schema.prisma          # Prisma database schema
└── src/
    └── recognition/
        ├── router.py      # API route definitions
        ├── service.py     # Business logic layer
        ├── schemas.py     # Pydantic models
        └── dependencies.py # Auth & dependency injection
```

## Key Changes from Original Implementation

### 1. Added `require_roles()` Function (dependencies.py)
- New dependency factory for role-based access control
- Supports multiple allowed roles
- Returns proper 403 error with contract-compliant message

### 2. Enhanced Error Messages (service.py)
- All error messages match API contract exactly
- Proper HTTP status codes (404, 422, 403, 500)
- Contract-compliant error details

### 3. Improved Schema Validation (schemas.py)
- URL length validation (500 char max)
- Enhanced field descriptions
- JSON schema examples for documentation
- Proper field validators

### 4. Updated Router Documentation (router.py)
- Comprehensive endpoint descriptions
- Access control documentation
- Example responses
- Status code 201 for POST /reviews

### 5. Enhanced Main Application (main.py)
- Added health check endpoint
- Improved CORS configuration
- Contract-compliant error response examples
- Better documentation

## Testing

### Manual Testing with cURL

**Create Review:**
```bash
curl -X POST http://localhost:8005/v1/reviews \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver_id": "550e8400-e29b-41d4-a716-446655440000",
    "rating": 4,
    "comment": "Excellent work on the project!"
  }'
```

**List Reviews:**
```bash
curl http://localhost:8005/v1/reviews?page=1&page_size=20 \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Get Specific Review:**
```bash
curl http://localhost:8005/v1/reviews/990e8400-e29b-41d4-a716-446655440004 \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Update Review:**
```bash
curl -X PUT http://localhost:8005/v1/reviews/990e8400-e29b-41d4-a716-446655440004 \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "rating": 5,
    "comment": "Updated: Outstanding performance!"
  }'
```

## Health Check

```bash
curl http://localhost:8005/health
```

Response:
```json
{
  "status": "healthy",
  "database": "connected",
  "service": "recognition-service"
}
```

## Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| DATABASE_URL | PostgreSQL connection string | ✓ | - |
| AUTH_SERVICE_URL | Authentication validation endpoint | ✓ | - |
| SECRET_KEY | JWT secret key | ✓ | - |
| ALGORITHM | JWT algorithm | ✗ | HS256 |
| ACCESS_TOKEN_EXPIRE_MINUTES | Token expiration time | ✗ | 30 |

## Database Schema Requirements

The service requires the following database tables:
- `reviews` - Main reviews table
- `employees` - Employee records
- `status_master` - Status codes (requires REVIEW_ACTIVE status)

See `schema.prisma` for complete schema definition.

## Production Deployment

### Recommended Settings

1. **Disable debug mode**: Remove `--reload` flag
2. **Use process manager**: Deploy with Gunicorn or systemd
3. **Enable HTTPS**: Use reverse proxy (nginx) with SSL
4. **Configure logging**: Set up structured logging
5. **Monitor health**: Use `/health` endpoint
6. **Set rate limits**: Configure API gateway limits
7. **Update CORS**: Restrict to production domains

### Example with Gunicorn

```bash
gunicorn main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8005 \
  --access-logfile - \
  --error-logfile -
```

## Support

For issues or questions:
1. Check the API documentation at `/v1/docs`
2. Review the API contract document
3. Contact the development team

## License

Internal use only - Employee Management & Rewards System

---

**Contract Compliance:** ✅ Fully Compliant with API Contract v0.1.1