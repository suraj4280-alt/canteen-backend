# Canteen Backend Project Status & Documentation

This document provides a comprehensive overview of the current state of the Canteen & Hostel Management System backend. It outlines the features that have been built, explains the architecture and where everything is located, and lists the pending tasks.

---

## 1. What We Have Done (Features Implemented)

We have successfully built a robust, async-first FastAPI backend with role-based access control and a PostgreSQL database.

*   **Authentication System:** 
    *   User Registration mapping to specific roles (e.g., student) and hostels.
    *   Login system supporting dual identifiers (Email or Student UID).
    *   Secure password hashing using `bcrypt`.
    *   JWT (JSON Web Token) based stateless authentication (Access & Refresh tokens).
*   **Meal Management System:**
    *   Dynamic fetching of meal slots ordered by time.
    *   Menu fetching mapped to specific dates, meal slots, and the student's assigned hostel.
    *   "Today" timeline endpoint that dynamically calculates the current meal phase and the next upcoming meal based on the real-time clock.
*   **Booking Engine:**
    *   Full CRUD operations for meal bookings (Create, View, Update, Cancel).
    *   **Skip Feature:** Students can mark meals as skipped and provide a reason, with the ability to undo the skip.
    *   **Validation Rules:** Built-in safeguards against duplicate bookings and strict enforcement of booking cutoff times (students cannot book/cancel after the deadline).
    *   Database transaction safety for multi-item bookings.
*   **QR Token System:**
    *   Generation of secure, encrypted QR token payloads for active and upcoming bookings.
    *   Staff scanning endpoint to securely validate QR payloads and mark meals as "consumed".
    *   Ownership validation ensuring users can only access their own QR tokens.

---

## 2. Where Things Are & How They Work (Architecture)

The project follows a standard modular FastAPI structure to keep the code clean and maintainable.

### Core Configuration & Setup
*   **`app/main.py`**: The main entry point. Sets up the FastAPI app, manages the database connection lifecycle (startup/shutdown), configures CORS, and registers all route modules.
*   **`app/config.py`**: Handles environment variables (like Database URL, Secret Keys for JWT).
*   **`app/database.py`**: Manages the high-performance PostgreSQL connection pool using `asyncpg`.
*   **`schema.sql`**: The master file containing all database table definitions and relationships.

### Security & Dependency Injection
*   **`app/dependencies.py`**: Contains reusable dependencies injected into routes. It handles:
    *   Database connection provisioning per request.
    *   JWT decoding and user verification (`get_current_user`).
    *   Role-based access control checkers (`require_role`, `get_current_student`, `require_staff`).

### API Routes (The "Where")
All endpoints are neatly separated into domains inside the `app/routes/` folder:
*   **`auth.py`**: Handles `/api/auth/register` and `/api/auth/login`.
*   **`meals.py`**: Handles `/api/meals/slots`, `/api/meals/menu`, and `/api/meals/today`.
*   **`bookings.py`**: Handles all `/api/bookings` logic (create, update, cancel, skip).
*   **`tokens.py`**: Handles `/api/tokens/active`, `upcoming`, `qr-data`, and the staff `/api/tokens/scan`.

### Business Logic (Services)
Complex logic is abstracted away from routes into the `app/services/` folder:
*   **`auth_service.py`**: Password hashing/verification and JWT generation logic.
*   **`booking_service.py`**: Core logic for validating cutoff times, checking for duplicate bookings, and resolving meal menus.
*   **`qr_service.py`**: Logic for generating the QR payload and safely processing a scan from staff.

### Data Validation (Schemas)
*   **`app/schemas/`**: Contains Pydantic models for every route (`auth.py`, `bookings.py`, `meals.py`, `tokens.py`). These ensure that incoming requests and outgoing responses exactly match the expected data structure.

---

## 3. What is Left to Do (Pending Tasks)

To make the system 100% production-ready and feature-complete, the following items still need to be addressed:

1.  **Session Management (Phase 3):** 
    *   *Where:* `app/routes/auth.py`
    *   *Task:* Currently, refresh tokens are generated statelessly. We need to store active sessions in the database so we can forcefully log users out or invalidate compromised tokens.
2.  **Countdown Timer Logic:**
    *   *Where:* `app/routes/meals.py` -> `get_today` endpoint.
    *   *Task:* Implement the actual mathematical logic to calculate `countdown_hours` and `countdown_minutes` until the next meal cutoff. (Currently hardcoded to 0).
3.  **Admin / Dashboard APIs:**
    *   *Task:* Build endpoints for administrators to create/edit meal slots, manage menus, view system-wide booking statistics, and manage user/staff accounts. 
4.  **Notifications Integration:**
    *   *Task:* Add a service to send emails or push notifications when a user registers, resets their password, or when system-wide announcements are made.
5.  **Data Seeding & DB Migrations:**
    *   *Task:* Set up a proper migration tool (like Alembic, though we are using raw `asyncpg`) or a script to seed initial admin users and hostel data into the live database seamlessly.
6.  **Automated Testing:**
    *   *Task:* Expand upon `test_db.py` by writing comprehensive unit and integration tests using `pytest` for all endpoints to prevent future regressions.
