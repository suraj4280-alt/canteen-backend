"""Task 22: pytest tests for core endpoints.

Run: cd canteen-backend && .\\venv\\Scripts\\python.exe -m pytest tests/ -v
"""
import pytest
import pytest_asyncio
import httpx
import asyncio
from datetime import date, timedelta

import httpx
import asyncio
from datetime import date, timedelta

BASE = "http://localhost:8000"

# Test user credentials — created by register test
TEST_EMAIL = "testuser@tnu.in"
TEST_UID = "TNU2024091100099"
TEST_PASSWORD = "Test@1234"
TEST_HOSTEL = "H4"

# Shared state across tests
_tokens = {}
_booking_id = None


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def client():
    async with httpx.AsyncClient(base_url=BASE, timeout=15.0) as c:
        yield c


# ── 1. Register ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register(client):
    resp = await client.post("/api/auth/register", json={
        "first_name": "Test",
        "last_name": "User",
        "email": TEST_EMAIL,
        "uid": TEST_UID,
        "hostel": TEST_HOSTEL,
        "password": TEST_PASSWORD,
    })
    # 201 on first run, 400 if already registered
    assert resp.status_code in (201, 400), resp.text


@pytest.mark.asyncio
async def test_register_duplicate(client):
    resp = await client.post("/api/auth/register", json={
        "first_name": "Test",
        "last_name": "User",
        "email": TEST_EMAIL,
        "uid": TEST_UID,
        "hostel": TEST_HOSTEL,
        "password": TEST_PASSWORD,
    })
    assert resp.status_code == 400
    assert "already registered" in resp.json()["detail"].lower()


# ── 2. Login ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_with_email(client):
    resp = await client.post("/api/auth/login", json={
        "identifier": TEST_EMAIL,
        "password": TEST_PASSWORD,
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    _tokens["access"] = data["access_token"]
    _tokens["refresh"] = data["refresh_token"]


@pytest.mark.asyncio
async def test_login_with_uid(client):
    resp = await client.post("/api/auth/login", json={
        "identifier": TEST_UID,
        "password": TEST_PASSWORD,
    })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    resp = await client.post("/api/auth/login", json={
        "identifier": TEST_EMAIL,
        "password": "WrongPass@1",
    })
    assert resp.status_code == 401


# ── 3. Token Refresh ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_token(client):
    assert _tokens.get("refresh"), "Login must run first"
    resp = await client.post("/api/auth/refresh", json={
        "refresh_token": _tokens["refresh"],
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    # Update tokens for subsequent tests
    _tokens["access"] = data["access_token"]
    _tokens["refresh"] = data["refresh_token"]


@pytest.mark.asyncio
async def test_refresh_invalid_token(client):
    resp = await client.post("/api/auth/refresh", json={
        "refresh_token": "invalid.token.here",
    })
    assert resp.status_code == 401


# ── 4. Get Menu ─────────────────────────────────────────────────────────────

def _auth_headers():
    return {"Authorization": f"Bearer {_tokens['access']}"}


@pytest.mark.asyncio
async def test_get_slots(client):
    resp = await client.get("/api/meals/slots", headers=_auth_headers())
    assert resp.status_code == 200
    slots = resp.json()
    assert isinstance(slots, list)
    assert len(slots) >= 1
    assert "name" in slots[0]
    assert "id" in slots[0]


@pytest.mark.asyncio
async def test_get_menu(client):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    resp = await client.get(f"/api/meals/menu?date={tomorrow}&slot_id=1", headers=_auth_headers())
    # 200 if menu exists, 404 if no menu configured for that hostel/slot
    assert resp.status_code in (200, 404), resp.text
    if resp.status_code == 200:
        data = resp.json()
        assert "items" in data
        assert isinstance(data["items"], list)


# ── 5. Create Booking ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_booking(client):
    global _booking_id
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    
    # First get menu items to use valid IDs
    menu_resp = await client.get(f"/api/meals/menu?date={tomorrow}&slot_id=1", headers=_auth_headers())
    if menu_resp.status_code != 200:
        pytest.skip("No menu available for booking test")
    
    items = menu_resp.json().get("items", [])
    if not items:
        pytest.skip("No menu items available")
    
    item_ids = [items[0]["id"]]
    
    resp = await client.post("/api/bookings", headers=_auth_headers(), json={
        "date": tomorrow,
        "slot_id": 1,
        "item_ids": item_ids,
    })
    # 201 on success, 400 if already booked or cutoff passed
    assert resp.status_code in (201, 400), resp.text
    if resp.status_code == 201:
        data = resp.json()
        assert "id" in data
        assert "order_id" in data
        _booking_id = data["id"]


@pytest.mark.asyncio
async def test_create_duplicate_booking(client):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    menu_resp = await client.get(f"/api/meals/menu?date={tomorrow}&slot_id=1", headers=_auth_headers())
    if menu_resp.status_code != 200:
        pytest.skip("No menu")
    items = menu_resp.json().get("items", [])
    if not items:
        pytest.skip("No items")
    
    resp = await client.post("/api/bookings", headers=_auth_headers(), json={
        "date": tomorrow,
        "slot_id": 1,
        "item_ids": [items[0]["id"]],
    })
    assert resp.status_code == 400  # Duplicate


# ── 6. Skip Meal ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skip_booking(client):
    if not _booking_id:
        pytest.skip("No booking created")
    
    resp = await client.post(
        f"/api/bookings/{_booking_id}/skip",
        headers=_auth_headers(),
        json={"reason": "Going Home"},
    )
    # 200 on success, 400 if cutoff passed
    assert resp.status_code in (200, 400), resp.text


@pytest.mark.asyncio
async def test_undo_skip(client):
    if not _booking_id:
        pytest.skip("No booking created")
    
    resp = await client.delete(
        f"/api/bookings/{_booking_id}/skip",
        headers=_auth_headers(),
    )
    assert resp.status_code in (200, 400), resp.text


# ── 7. QR Scan ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_qr_not_available_future_date(client):
    """QR should not be available for a future-date booking."""
    if not _booking_id:
        pytest.skip("No booking created")
    
    resp = await client.get(
        f"/api/bookings/{_booking_id}/qr",
        headers=_auth_headers(),
    )
    # Should be 400 "QR not available yet" since booking is for tomorrow
    assert resp.status_code == 400
    assert "not available" in resp.json().get("detail", "").lower()


# ── 8. Stats & History ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_booking_stats(client):
    resp = await client.get("/api/bookings/stats", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "total_bookings" in data
    assert "consumed" in data


@pytest.mark.asyncio
async def test_booking_history(client):
    resp = await client.get("/api/bookings?page=1&size=10", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    # Task 1 verification: JOINed fields must be present
    if data["items"]:
        item = data["items"][0]
        assert "slot_name" in item, "BookingHistoryResp must include slot_name"
        assert "status_name" in item, "BookingHistoryResp must include status_name"


# ── 9. Feedback ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_feedback_tags(client):
    resp = await client.get("/api/feedback/tags", headers=_auth_headers())
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── 10. Profile Update ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_profile(client):
    resp = await client.put("/api/auth/profile", headers=_auth_headers(), json={
        "phone": "9876543210",
        "room_number": "A-101",
    })
    assert resp.status_code == 200


# ── 11. Cleanup: Cancel test booking ────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_booking(client):
    if not _booking_id:
        pytest.skip("No booking to cancel")
    
    resp = await client.delete(
        f"/api/bookings/{_booking_id}",
        headers=_auth_headers(),
    )
    assert resp.status_code in (200, 400), resp.text
