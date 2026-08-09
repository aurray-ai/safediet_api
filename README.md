# SafeDaet API

Production-shaped FastAPI backend for Safediet authentication, onboarding, meals, groceries, billing, and notifications.

## Auth and Email Coverage

- customer registration with JWT session creation
- welcome email delivery after registration
- password reset request and confirmation
- Resend email delivery support with logging fallback when email is not configured
- MongoDB-backed password reset token storage

## Tech Stack

- FastAPI
- PyMongo
- Passlib with PBKDF2-SHA256 and bcrypt compatibility
- Python-JOSE for JWT
- Resend for transactional email

## Environment Setup

1. Copy `.env.example` to `.env`.
2. Set `JWT_SECRET_KEY` to a strong production secret.
3. Set `MONGODB_URL` and `MONGODB_DATABASE`.
4. Set Stripe keys if billing is enabled.
5. Set the email variables below when enabling transactional email.

Required email-related variables:

- `RESEND_API_KEY`
- `EMAIL_FROM_ADDRESS`
- `EMAIL_FROM_NAME`
- `WEB_APP_BASE_URL`

Recommended public URL variables:

- `API_PUBLIC_BASE_URL`
  Use your externally reachable backend URL here, for example your ngrok HTTPS URL, so uploaded image URLs do not get saved as `localhost`.

Optional email-related variables:

- `EMAIL_REPLY_TO`
- `RESEND_API_BASE_URL`
- `RESEND_TIMEOUT_SECONDS`
- `PASSWORD_RESET_TOKEN_TTL_MINUTES`

If `RESEND_API_KEY` or `EMAIL_FROM_ADDRESS` is missing, the backend falls back to a logging sender instead of calling Resend.

## Run With Docker

```bash
cd safedaet_api
docker compose up --build
```

API base URL:

```text
http://localhost:8000
```

Swagger docs:

```text
http://localhost:8000/docs
```

## Auth Endpoints

### Register

`POST /api/v1/auth/register`

```json
{
  "name": "Ada Lovelace",
  "email": "ada@example.com",
  "password": "StrongPass123",
  "user_types": ["customer"],
  "user_configuration": {
    "mode": "solo",
    "goal": "maintain",
    "weekly_budget": 85,
    "culture_preferences": ["East African", "Italian"],
    "diet_rules": [],
    "household_size": 1,
    "selected_plan_types": ["Breakfast", "Lunch", "Dinner"],
    "allergies": [],
    "gender": "Prefer not to say",
    "age": 24
  }
}
```

Returns an auth response with:

- `access_token`
- `token_type`
- `user`

### Login

`POST /api/v1/auth/login`

```json
{
  "email": "ada@example.com",
  "password": "StrongPass123"
}
```

### Request Password Reset

`POST /api/v1/auth/password-reset/request`

```json
{
  "email": "ada@example.com"
}
```

Returns:

```json
{
  "message": "If that email exists, a password reset link has been sent."
}
```

### Confirm Password Reset

`POST /api/v1/auth/password-reset/confirm`

```json
{
  "token": "reset-token-from-email",
  "password": "NewStrongPass123"
}
```

Returns:

```json
{
  "message": "Password updated successfully."
}
```

### Current User

`GET /api/v1/auth/me`

### Update User Configuration

`PATCH /api/v1/auth/me/configuration`

### Health

`GET /health`
# safediet_api
