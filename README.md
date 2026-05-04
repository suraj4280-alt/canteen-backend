# Canteen Management System Backend

This is the FastAPI backend for the University Canteen Management System. It serves both the Flutter mobile application for students and the web administrative portal.

## Tech Stack
- **Framework:** FastAPI
- **Database:** PostgreSQL (with `asyncpg` driver)
- **Authentication:** JWT (JSON Web Tokens)
- **Validation:** Pydantic

## Features
- Secure student and staff authentication with JWT.
- Dynamic, database-driven weekly menu loading.
- Advanced time-based slot booking system.
- Secure, server-side one-time QR token generation (`gen_random_uuid()`).
- High-performance asynchronous database operations.

## Setup Instructions

1. **Clone & Virtual Environment:**
   ```bash
   python -m venv venv
   source venv/Scripts/activate # Windows
   ```

2. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment:**
   Make sure you have a `.env` file in the root directory.
   ```ini
   DB_HOST=localhost
   DB_PORT=5432
   DB_NAME=canteen_db
   DB_USER=postgres
   DB_PASSWORD=postgres
   SECRET_KEY=your_secure_secret_key_here
   CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
   ```

4. **Run the Server:**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

## Core API Endpoints

### Authentication
- `POST /api/auth/register` - Register a new user
- `POST /api/auth/login` - Login and receive JWT
- `GET /api/auth/me` - Get current user profile

### Meals & Menu
- `GET /api/meals/slots` - Get active meal slots (Breakfast, Lunch, etc.)
- `GET /api/meals/menu?date=YYYY-MM-DD&slot_id=X` - Get dynamic menu items

### Bookings
- `POST /api/bookings` - Create a meal booking
- `GET /api/bookings/{id}/qr` - Get a time-bound, secure QR token for the mess counter
- `DELETE /api/bookings/{id}` - Cancel a booking

## How the QR System Works
The QR system utilizes zero-trust architecture. Students cannot generate QR codes themselves.
1. The student app requests a QR code for their `bookingId`.
2. The backend checks the current server time against the meal slot's `start_time` and `end_time`.
3. If valid, the backend generates a `uuid` token in the database.
4. The token is sent to the app and rendered.
5. The token can only be scanned once (tracked in the `scans` table) and expires after the slot ends.
