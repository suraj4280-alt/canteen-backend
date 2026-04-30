CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DROP TABLE IF EXISTS leave_periods, feedback_tag_links, otp_requested, sessions,
    error_logs, auth_logs, hostel_settings, notifications, scans, feedback,
    feedback_tags, booking_items, bookings, booking_status, meal_menu_items,
    meal_menus, menu_items, meal_slots, staff, students, users, hostels, roles CASCADE;


-- ─── trigger functions ────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Handles updated_at + version bump + status audit for bookings in one pass.
CREATE OR REPLACE FUNCTION bookings_before_update()
RETURNS TRIGGER AS $$
DECLARE
    v_cancelled_id INTEGER;
    v_used_id      INTEGER;
    v_booked_id    INTEGER;
    v_pending_id   INTEGER;
BEGIN
    NEW.updated_at := CURRENT_TIMESTAMP;
    NEW.version    := OLD.version + 1;

    IF OLD.status_id IS DISTINCT FROM NEW.status_id THEN
        NEW.previous_status_id := OLD.status_id;
        SELECT id INTO v_cancelled_id FROM booking_status WHERE status_name = 'cancelled';
        SELECT id INTO v_used_id      FROM booking_status WHERE status_name = 'used';
        SELECT id INTO v_booked_id    FROM booking_status WHERE status_name = 'booked';
        SELECT id INTO v_pending_id   FROM booking_status WHERE status_name = 'pending';

        IF    NEW.status_id = v_cancelled_id THEN NEW.cancelled_at  := CURRENT_TIMESTAMP;
        ELSIF NEW.status_id = v_used_id      THEN NEW.used_at       := CURRENT_TIMESTAMP;
        ELSIF NEW.status_id = v_booked_id AND OLD.status_id = v_pending_id
                                             THEN NEW.confirmed_at  := CURRENT_TIMESTAMP;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Handles updated_at + version bump + blocks is_recurring flip for meal_menus.
CREATE OR REPLACE FUNCTION meal_menus_before_update()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.is_recurring IS DISTINCT FROM NEW.is_recurring THEN
        RAISE EXCEPTION 'Cannot toggle is_recurring on meal_menus(id=%). Delete and recreate.', OLD.id;
    END IF;
    NEW.updated_at := CURRENT_TIMESTAMP;
    NEW.version    := OLD.version + 1;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Sets qr_expires_at from slot end time; rotates qr_token if date/slot changes.
CREATE OR REPLACE FUNCTION set_booking_qr_expiry()
RETURNS TRIGGER AS $$
DECLARE
    slot_end TIME;
BEGIN
    SELECT end_time INTO slot_end FROM meal_slots WHERE id = NEW.meal_slot_id;
    NEW.qr_expires_at := (NEW.date + slot_end)::TIMESTAMP;

    IF TG_OP = 'UPDATE' AND (
        OLD.date         IS DISTINCT FROM NEW.date OR
        OLD.meal_slot_id IS DISTINCT FROM NEW.meal_slot_id
    ) THEN
        NEW.qr_token := uuid_generate_v4();
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Keeps meal_menus.bookings_count in sync; floors at 0 to guard anomalies.
CREATE OR REPLACE FUNCTION update_meal_menu_bookings_count()
RETURNS TRIGGER AS $$
DECLARE
    v_booked_id INTEGER;
BEGIN
    SELECT id INTO v_booked_id FROM booking_status WHERE status_name = 'booked';

    IF TG_OP = 'INSERT' AND NEW.status_id = v_booked_id THEN
        UPDATE meal_menus SET bookings_count = bookings_count + 1 WHERE id = NEW.meal_menu_id;

    ELSIF TG_OP = 'UPDATE' AND OLD.status_id IS DISTINCT FROM NEW.status_id THEN
        IF NEW.status_id = v_booked_id THEN
            UPDATE meal_menus SET bookings_count = bookings_count + 1 WHERE id = NEW.meal_menu_id;
        ELSIF OLD.status_id = v_booked_id THEN
            UPDATE meal_menus SET bookings_count = GREATEST(0, bookings_count - 1) WHERE id = NEW.meal_menu_id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Validates auto_book_days array elements are 0-6; also bumps updated_at.
CREATE OR REPLACE FUNCTION validate_auto_book_days()
RETURNS TRIGGER AS $$
DECLARE d INTEGER;
BEGIN
    IF NEW.auto_book_days IS NOT NULL THEN
        FOREACH d IN ARRAY NEW.auto_book_days LOOP
            IF d < 0 OR d > 6 THEN
                RAISE EXCEPTION 'auto_book_days has invalid value %: must be 0-6', d;
            END IF;
        END LOOP;
    END IF;
    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ─── tables ───────────────────────────────────────────────────────────────────

CREATE TABLE roles (
    id         SERIAL PRIMARY KEY,
    role_name  VARCHAR(50) UNIQUE NOT NULL,
    is_active  BOOLEAN   DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_role_name_lowercase CHECK (role_name = LOWER(role_name))
);

CREATE TABLE hostels (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(50) UNIQUE NOT NULL,
    capacity     INTEGER   DEFAULT 0 CHECK (capacity >= 0),
    address      TEXT,
    warden_name  VARCHAR(100),
    warden_email VARCHAR(100),
    warden_phone VARCHAR(15),
    is_active    BOOLEAN   DEFAULT TRUE,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_warden_email CHECK (
        warden_email IS NULL OR
        warden_email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
    )
);
CREATE TRIGGER trg_hostels_updated_at BEFORE UPDATE ON hostels
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE users (
    id                  SERIAL PRIMARY KEY,
    role_id             INTEGER NOT NULL REFERENCES roles(id),
    email               VARCHAR(100) UNIQUE NOT NULL,
    email_verified      BOOLEAN   DEFAULT FALSE,
    password_hash       VARCHAR(255) NOT NULL,
    password_changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active           BOOLEAN   DEFAULT TRUE,
    login_attempts      INTEGER   DEFAULT 0,
    locked_until        TIMESTAMP,
    last_login_at       TIMESTAMP,
    last_login_ip       VARCHAR(50),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_email_format CHECK (
        email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
    ),
    -- bcrypt hashes start with $2; update this constraint if you switch algorithms
    CONSTRAINT chk_password_hash CHECK (password_hash LIKE '$2%'),
    CONSTRAINT chk_login_attempts CHECK (login_attempts BETWEEN 0 AND 5)
);
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE students (
    id                 SERIAL PRIMARY KEY,
    user_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    first_name         VARCHAR(50) NOT NULL,
    middle_name        VARCHAR(50),
    last_name          VARCHAR(50) NOT NULL,
    phone              VARCHAR(15),
    email              VARCHAR(100),
    uid                VARCHAR(20) UNIQUE NOT NULL,
    hostel_id          INTEGER REFERENCES hostels(id),
    room_number        VARCHAR(10),
    profile_image_url  TEXT,
    dietary_preference VARCHAR(20) DEFAULT 'veg'
                           CHECK (dietary_preference IN ('veg', 'non-veg', 'vegan', 'jain')),
    fcm_token          TEXT,
    platform           VARCHAR(10) CHECK (platform IN ('ios', 'android')),
    app_version        VARCHAR(20),
    is_active          BOOLEAN   DEFAULT TRUE,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- pattern: TNU2024069100014 — update if your UID format differs
    CONSTRAINT chk_uid_format  CHECK (uid ~ '^[A-Z]{3}[0-9]{10,14}$'),
    CONSTRAINT chk_room_format CHECK (room_number IS NULL OR room_number ~ '^[0-9]{1,4}[A-Z]?$'),
    CONSTRAINT chk_student_email CHECK (
        email IS NULL OR email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
    )
);
CREATE TRIGGER trg_students_updated_at BEFORE UPDATE ON students
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE staff (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    first_name       VARCHAR(50) NOT NULL,
    last_name        VARCHAR(50) NOT NULL,
    phone            VARCHAR(15),
    email            VARCHAR(100),
    designation      VARCHAR(50) CHECK (designation IN (
                         'canteen_manager','head_cook','cook',
                         'qr_scanner','cashier','supervisor','admin')),
    hostel_id        INTEGER REFERENCES hostels(id),
    can_scan_qr      BOOLEAN DEFAULT FALSE,
    can_edit_menu    BOOLEAN DEFAULT FALSE,
    can_view_reports BOOLEAN DEFAULT FALSE,
    can_manage_staff BOOLEAN DEFAULT FALSE,
    shift_start      TIME,
    shift_end        TIME,
    is_active        BOOLEAN   DEFAULT TRUE,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_shift CHECK (
        (shift_start IS NULL AND shift_end IS NULL) OR
        (shift_start IS NOT NULL AND shift_end IS NOT NULL AND shift_end > shift_start)
    ),
    CONSTRAINT chk_staff_email CHECK (
        email IS NULL OR email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
    )
);
CREATE TRIGGER trg_staff_updated_at BEFORE UPDATE ON staff
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE meal_slots (
    id                       SERIAL PRIMARY KEY,
    name                     VARCHAR(50) NOT NULL,
    display_order            INTEGER   NOT NULL DEFAULT 0,
    start_time               TIME NOT NULL,
    end_time                 TIME NOT NULL,
    booking_cutoff_time      TIME NOT NULL,
    -- NULL means no cancellation cutoff (always cancellable up to booking cutoff)
    cancel_cutoff_time       TIME DEFAULT NULL,
    color_code               VARCHAR(7) DEFAULT '#4CAF50'
                                 CHECK (color_code ~ '^#[0-9A-Fa-f]{6}$'),
    icon_name                VARCHAR(50) DEFAULT 'restaurant',
    max_bookings_per_student INTEGER DEFAULT 1,
    is_active                BOOLEAN DEFAULT TRUE,
    CONSTRAINT chk_times        CHECK (end_time > start_time),
    CONSTRAINT chk_cutoff       CHECK (booking_cutoff_time < start_time),
    CONSTRAINT chk_cancel_cutoff CHECK (
        cancel_cutoff_time IS NULL OR cancel_cutoff_time <= booking_cutoff_time
    ),
    UNIQUE (name, is_active)
);

CREATE TABLE menu_items (
    id                SERIAL PRIMARY KEY,
    name              VARCHAR(100) NOT NULL UNIQUE,
    type              VARCHAR(20) CHECK (type IN ('veg','non-veg','beverage','dessert','snack')),
    description       TEXT,
    short_description VARCHAR(100),
    image_url         TEXT,
    thumbnail_url     TEXT,
    allergens         VARCHAR(200),
    spice_level       INTEGER CHECK (spice_level BETWEEN 0 AND 3),
    default_quantity  VARCHAR(30) DEFAULT '1 plate',
    unit              VARCHAR(20) DEFAULT 'plate',
    base_price        DECIMAL(10,2) DEFAULT 0.00,
    is_premium        BOOLEAN   DEFAULT FALSE,
    is_active         BOOLEAN   DEFAULT TRUE,
    created_by        INTEGER REFERENCES users(id),
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_image_url CHECK (
        image_url IS NULL OR
        image_url ~* '^https?://.*\.(jpg|jpeg|png|webp)(\?.*)?$'
    )
);
CREATE TRIGGER trg_menu_items_updated_at BEFORE UPDATE ON menu_items
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE meal_menus (
    id             SERIAL PRIMARY KEY,
    hostel_id      INTEGER NOT NULL REFERENCES hostels(id),
    meal_slot_id   INTEGER NOT NULL REFERENCES meal_slots(id),
    date           DATE,
    day_of_week    INTEGER CHECK (day_of_week BETWEEN 0 AND 6),
    is_recurring   BOOLEAN DEFAULT FALSE,
    is_published   BOOLEAN DEFAULT FALSE,
    is_active      BOOLEAN DEFAULT TRUE,
    max_bookings   INTEGER DEFAULT 999,
    bookings_count INTEGER DEFAULT 0 CHECK (bookings_count >= 0),
    special_notes  TEXT,
    created_by     INTEGER REFERENCES users(id),
    updated_by     INTEGER REFERENCES users(id),
    version        INTEGER   DEFAULT 1,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_date_or_dow CHECK (
        (date IS NOT NULL AND day_of_week IS NULL AND is_recurring = FALSE) OR
        (date IS NULL     AND day_of_week IS NOT NULL AND is_recurring = TRUE)
    )
);
-- Partial unique indexes (WHERE clause not allowed inside CREATE TABLE)
CREATE UNIQUE INDEX uidx_meal_menus_date
    ON meal_menus (hostel_id, meal_slot_id, date) WHERE date IS NOT NULL;
CREATE UNIQUE INDEX uidx_meal_menus_recurring
    ON meal_menus (hostel_id, meal_slot_id, day_of_week) WHERE is_recurring = TRUE;

CREATE TRIGGER trg_meal_menus_before_update BEFORE UPDATE ON meal_menus
    FOR EACH ROW EXECUTE FUNCTION meal_menus_before_update();

CREATE TABLE meal_menu_items (
    id             SERIAL PRIMARY KEY,
    meal_menu_id   INTEGER NOT NULL REFERENCES meal_menus(id) ON DELETE CASCADE,
    menu_item_id   INTEGER NOT NULL REFERENCES menu_items(id),
    quantity       VARCHAR(30)   DEFAULT '1 plate',
    quantity_value DECIMAL(10,2) DEFAULT 1,
    unit           VARCHAR(20)   DEFAULT 'plate',
    is_default     BOOLEAN DEFAULT FALSE,
    is_optional    BOOLEAN DEFAULT TRUE,
    max_selectable INTEGER DEFAULT 1,
    price_override DECIMAL(10,2),
    sort_order     INTEGER DEFAULT 0,
    UNIQUE (meal_menu_id, menu_item_id)
);

CREATE TABLE booking_status (
    id            SERIAL PRIMARY KEY,
    status_name   VARCHAR(20) UNIQUE NOT NULL,
    is_terminal   BOOLEAN DEFAULT FALSE,
    display_label VARCHAR(30) NOT NULL,
    color_code    VARCHAR(7) DEFAULT '#000000'
                      CHECK (color_code ~ '^#[0-9A-Fa-f]{6}$'),
    icon_name     VARCHAR(50),
    counts_as_meal BOOLEAN DEFAULT TRUE,
    counts_as_skip BOOLEAN DEFAULT FALSE,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    is_active     BOOLEAN DEFAULT TRUE
);

CREATE TABLE leave_periods (
    id              SERIAL PRIMARY KEY,
    student_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    reason          TEXT NOT NULL,
    reason_category VARCHAR(20) DEFAULT 'home_visit'
                        CHECK (reason_category IN ('home_visit','festival','medical','internship','sports','other')),
    is_approved     BOOLEAN DEFAULT FALSE,
    approved_by     INTEGER REFERENCES staff(id),
    approved_at     TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_leave_dates CHECK (end_date >= start_date)
);
CREATE TRIGGER trg_leave_periods_updated_at BEFORE UPDATE ON leave_periods
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE bookings (
    id                   SERIAL PRIMARY KEY,
    student_id           INTEGER NOT NULL REFERENCES students(id),
    meal_slot_id         INTEGER NOT NULL REFERENCES meal_slots(id),
    meal_menu_id         INTEGER NOT NULL REFERENCES meal_menus(id),
    date                 DATE NOT NULL,
    status_id            INTEGER NOT NULL REFERENCES booking_status(id),
    previous_status_id   INTEGER REFERENCES booking_status(id),
    qr_token             UUID DEFAULT uuid_generate_v4() UNIQUE,
    qr_expires_at        TIMESTAMP,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    confirmed_at         TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    cancelled_at         TIMESTAMP,
    used_at              TIMESTAMP,
    skip_reason          TEXT,
    skip_reason_category VARCHAR(20)
                             CHECK (skip_reason_category IN ('planned','unplanned','medical','emergency','other')),
    cancellation_reason  TEXT,
    cancelled_by         INTEGER REFERENCES users(id),
    notified_at          TIMESTAMP,
    total_items_count    INTEGER DEFAULT 0,
    special_requests     TEXT,
    version              INTEGER DEFAULT 1,
    UNIQUE (student_id, meal_slot_id, date),
    CONSTRAINT chk_confirmed_before_used CHECK (used_at IS NULL OR confirmed_at IS NOT NULL),
    CONSTRAINT chk_cancelled_before_used CHECK (used_at IS NULL OR cancelled_at IS NULL),
    CONSTRAINT chk_qr_expiry            CHECK (qr_expires_at IS NULL OR qr_expires_at > created_at)
);
CREATE TRIGGER trg_bookings_before_update BEFORE UPDATE ON bookings
    FOR EACH ROW EXECUTE FUNCTION bookings_before_update();
CREATE TRIGGER trg_set_qr_expiry BEFORE INSERT OR UPDATE OF meal_slot_id, date ON bookings
    FOR EACH ROW EXECUTE FUNCTION set_booking_qr_expiry();
CREATE TRIGGER trg_update_bookings_count AFTER INSERT OR UPDATE OF status_id ON bookings
    FOR EACH ROW EXECUTE FUNCTION update_meal_menu_bookings_count();
CREATE TABLE booking_items (
    id                   SERIAL PRIMARY KEY,
    booking_id           INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    menu_item_id         INTEGER NOT NULL REFERENCES menu_items(id),
    quantity             INTEGER DEFAULT 1 CHECK (quantity > 0),
    price_at_booking     DECIMAL(10,2),
    special_instructions TEXT,
    UNIQUE (booking_id, menu_item_id)
);

CREATE TABLE scans (
    id             SERIAL PRIMARY KEY,
    booking_id     INTEGER NOT NULL REFERENCES bookings(id),
    student_id     INTEGER NOT NULL REFERENCES students(id),
    meal_slot_id   INTEGER NOT NULL REFERENCES meal_slots(id),
    scan_date      DATE NOT NULL,
    scanned_by     INTEGER NOT NULL REFERENCES staff(id),
    qr_token       UUID NOT NULL,
    scanned_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    counter_id     INTEGER,
    location       VARCHAR(50),
    status         VARCHAR(20) CHECK (status IN ('success','failed','duplicate','expired')),
    failure_reason TEXT,
    device_info    TEXT,
    -- concurrent success protection: advisory lock on booking_id in app layer
    CONSTRAINT chk_failure_reason CHECK (status != 'failed' OR failure_reason IS NOT NULL)
);
CREATE UNIQUE INDEX uidx_scans_one_success
    ON scans (booking_id) WHERE status = 'success';

CREATE TABLE feedback_tags (
    id            SERIAL PRIMARY KEY,
    tag_name      VARCHAR(50) UNIQUE NOT NULL,
    display_label VARCHAR(50) NOT NULL,
    color_code    VARCHAR(7) DEFAULT '#607D8B',
    icon_name     VARCHAR(50),
    sort_order    INTEGER DEFAULT 0,
    is_active     BOOLEAN DEFAULT TRUE
);

CREATE TABLE feedback (
    id                  SERIAL PRIMARY KEY,
    student_id          INTEGER NOT NULL REFERENCES students(id),
    booking_id          INTEGER REFERENCES bookings(id),
    rating              INTEGER CHECK (rating BETWEEN 1 AND 5),
    message             TEXT,
    images              TEXT[],
    is_anonymous        BOOLEAN DEFAULT FALSE,
    is_locked           BOOLEAN DEFAULT TRUE,
    unlocked_at         TIMESTAMP,
    unlocked_by_scan_id INTEGER REFERENCES scans(id),
    is_resolved         BOOLEAN DEFAULT FALSE,
    resolved_by         INTEGER REFERENCES staff(id),
    resolved_at         TIMESTAMP,
    resolution_notes    TEXT,
    is_visible          BOOLEAN DEFAULT TRUE,
    sentiment_score     DECIMAL(3,2),
    sentiment_label     VARCHAR(10),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- when unlocked, unlocked_at must be recorded for audit trail
    CONSTRAINT chk_unlock_audit CHECK (is_locked = TRUE OR unlocked_at IS NOT NULL)
);
CREATE TRIGGER trg_feedback_updated_at BEFORE UPDATE ON feedback
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE feedback_tag_links (
    id          SERIAL PRIMARY KEY,
    feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
    tag_id      INTEGER NOT NULL REFERENCES feedback_tags(id),
    UNIQUE (feedback_id, tag_id)
);

CREATE TABLE notifications (
    id             SERIAL PRIMARY KEY,
    -- at least one of these must be set; all NULL means no one gets notified
    user_id        INTEGER REFERENCES users(id),
    hostel_id      INTEGER REFERENCES hostels(id),
    role_id        INTEGER REFERENCES roles(id),
    title          VARCHAR(100) NOT NULL,
    message        TEXT NOT NULL,
    image_url      TEXT,
    type           VARCHAR(50) CHECK (type IN ('booking','menu','alert','system','reminder','promo')),
    priority       VARCHAR(10) DEFAULT 'normal'
                       CHECK (priority IN ('low','normal','high','urgent')),
    action_label   VARCHAR(50) DEFAULT 'View',
    action_route   VARCHAR(100),
    action_params  JSONB,
    reference_type VARCHAR(50),
    reference_id   INTEGER,
    sent_via_push  BOOLEAN DEFAULT FALSE,
    sent_via_sms   BOOLEAN DEFAULT FALSE,
    sent_via_email BOOLEAN DEFAULT FALSE,
    sent_at        TIMESTAMP,
    delivered_at   TIMESTAMP,
    failed_at      TIMESTAMP,
    failure_reason TEXT,
    scheduled_at   TIMESTAMP,
    is_scheduled   BOOLEAN DEFAULT FALSE,
    expiry_at      TIMESTAMP,
    is_read        BOOLEAN DEFAULT FALSE,
    read_at        TIMESTAMP,
    created_by     INTEGER REFERENCES users(id),
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_has_target CHECK (
        user_id IS NOT NULL OR hostel_id IS NOT NULL OR role_id IS NOT NULL
    )
);

CREATE TABLE hostel_settings (
    id                    SERIAL PRIMARY KEY,
    hostel_id             INTEGER UNIQUE NOT NULL REFERENCES hostels(id),
    booking_window_days   INTEGER DEFAULT 7  CHECK (booking_window_days BETWEEN 1 AND 30),
    advance_booking_hour  INTEGER DEFAULT 18 CHECK (advance_booking_hour BETWEEN 0 AND 23),
    cancel_window_hours   INTEGER DEFAULT 1  CHECK (cancel_window_hours >= 0),
    max_skips_per_month   INTEGER DEFAULT 5,
    penalty_after_skips   INTEGER DEFAULT 3,
    penalty_type          VARCHAR(20) DEFAULT 'warning'
                              CHECK (penalty_type IN ('warning','fine','block_booking')),
    penalty_amount        DECIMAL(10,2) DEFAULT 0.00,
    auto_book_enabled     BOOLEAN DEFAULT FALSE,
    -- valid values: 0=Sun .. 6=Sat; enforced by trigger below
    auto_book_days        INTEGER[] DEFAULT '{1,2,3,4,5}',
    menu_publish_time     TIME DEFAULT '20:00',
    meal_cost             DECIMAL(10,2) DEFAULT 0.00,
    currency              VARCHAR(3) DEFAULT 'INR',
    default_notify_before INTEGER DEFAULT 30,
    updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER trg_hostel_settings_validate BEFORE INSERT OR UPDATE ON hostel_settings
    FOR EACH ROW EXECUTE FUNCTION validate_auto_book_days();

-- sessions before auth_logs so the FK is valid
CREATE TABLE sessions (
    id                 SERIAL PRIMARY KEY,
    user_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    access_token_hash  VARCHAR(64) NOT NULL UNIQUE,
    refresh_token_hash VARCHAR(64) UNIQUE,
    device_info        TEXT,
    device_id          VARCHAR(100),
    ip_address         VARCHAR(50),
    platform           VARCHAR(10) CHECK (platform IN ('ios','android','web')),
    is_mobile          BOOLEAN   DEFAULT TRUE,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at         TIMESTAMP NOT NULL,
    refresh_expires_at TIMESTAMP,
    last_used_at       TIMESTAMP,
    revoked_at         TIMESTAMP,
    logout_at          TIMESTAMP,
    revoked            BOOLEAN   DEFAULT FALSE,
    revoked_reason     VARCHAR(50)
);
CREATE UNIQUE INDEX uidx_sessions_user_device
    ON sessions (user_id, device_id) WHERE device_id IS NOT NULL;

CREATE TABLE auth_logs (
    id                SERIAL PRIMARY KEY,
    user_id           INTEGER REFERENCES users(id),
    action            VARCHAR(50) NOT NULL CHECK (action IN (
                          'login','logout','failed_login','password_reset_request',
                          'password_reset_complete','token_refresh','account_locked')),
    success           BOOLEAN NOT NULL,
    ip_address        VARCHAR(50),
    device_info       TEXT,
    user_agent        TEXT,
    platform          VARCHAR(10),
    failure_reason    VARCHAR(100),
    is_suspicious     BOOLEAN DEFAULT FALSE,
    suspicion_reason  TEXT,
    -- ON DELETE SET NULL: keep audit row even after session is deleted
    session_id        INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    token_fingerprint VARCHAR(64),
    country_code      VARCHAR(2),
    city              VARCHAR(100),
    timestamp         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE error_logs (
    id             SERIAL PRIMARY KEY,
    severity       VARCHAR(10) DEFAULT 'error'
                       CHECK (severity IN ('debug','info','warning','error','critical')),
    error_code     VARCHAR(50),
    request_id     VARCHAR(64) NOT NULL,
    correlation_id VARCHAR(64),
    endpoint       VARCHAR(200),
    http_method    VARCHAR(10),
    status_code    INTEGER,
    request_body   JSONB,
    response_body  JSONB,
    message        TEXT NOT NULL,
    stack_trace    TEXT,
    exception_type VARCHAR(100),
    environment    VARCHAR(10) DEFAULT 'production'
                       CHECK (environment IN ('development','staging','production')),
    app_version    VARCHAR(20),
    user_id        INTEGER REFERENCES users(id),
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- SHA-256 hex digest of the OTP; never store raw OTP value
CREATE TABLE otp_requested (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    otp_sha256     VARCHAR(64) NOT NULL,
    purpose        VARCHAR(30) DEFAULT 'login'
                       CHECK (purpose IN ('login','reset_password','verify_email',
                                          'verify_phone','change_email','change_phone','delete_account')),
    sent_via       VARCHAR(10) DEFAULT 'sms' CHECK (sent_via IN ('sms','email','push')),
    delivered_at   TIMESTAMP,
    is_used        BOOLEAN DEFAULT FALSE,
    verified_at    TIMESTAMP,
    attempts_count INTEGER DEFAULT 0,
    max_attempts   INTEGER DEFAULT 3,
    ip_address     VARCHAR(50),
    device_info    TEXT,
    expires_at     TIMESTAMP NOT NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_attempts CHECK (attempts_count <= max_attempts)
);


-- indexes

CREATE INDEX idx_users_email        ON users(email);
CREATE INDEX idx_users_active_email ON users(email) WHERE is_active = TRUE;

CREATE INDEX idx_students_uid        ON students(uid);
CREATE INDEX idx_students_hostel     ON students(hostel_id);
CREATE INDEX idx_students_phone      ON students(phone)     WHERE phone     IS NOT NULL;
CREATE INDEX idx_students_fcm        ON students(fcm_token) WHERE fcm_token IS NOT NULL;
CREATE INDEX idx_students_uid_lookup ON students(uid, is_active) INCLUDE (user_id, hostel_id);

CREATE INDEX idx_staff_user         ON staff(user_id);
CREATE INDEX idx_staff_hostel       ON staff(hostel_id)  WHERE hostel_id IS NOT NULL;
CREATE INDEX idx_staff_active_desig ON staff(is_active, designation);

CREATE INDEX idx_bookings_student   ON bookings(student_id);
CREATE INDEX idx_bookings_date      ON bookings(date);
CREATE INDEX idx_bookings_slot_date ON bookings(meal_slot_id, date);
CREATE INDEX idx_bookings_qr_token  ON bookings(qr_token);
CREATE INDEX idx_bookings_status    ON bookings(status_id, date);
CREATE INDEX idx_bookings_qr_lookup ON bookings(qr_token, qr_expires_at, status_id);

CREATE INDEX idx_meal_menus_date      ON meal_menus(date)        WHERE date IS NOT NULL;
CREATE INDEX idx_meal_menus_recurring ON meal_menus(day_of_week) WHERE is_recurring = TRUE;

CREATE INDEX idx_notifications_user_unread ON notifications(user_id, is_read, priority, created_at DESC);
CREATE INDEX idx_notifications_scheduled   ON notifications(is_scheduled, scheduled_at) WHERE is_scheduled = TRUE;
CREATE INDEX idx_notifications_expiry      ON notifications(expiry_at) WHERE expiry_at IS NOT NULL;
CREATE INDEX idx_notifications_reference   ON notifications(reference_type, reference_id);

CREATE INDEX idx_sessions_token ON sessions(access_token_hash);
CREATE INDEX idx_sessions_user  ON sessions(user_id) WHERE revoked = FALSE;

CREATE INDEX idx_scans_booking   ON scans(booking_id, scanned_at);
CREATE INDEX idx_scans_student   ON scans(student_id, scan_date);
CREATE INDEX idx_scans_slot_date ON scans(meal_slot_id, scan_date);
CREATE INDEX idx_scans_qr        ON scans(qr_token);

CREATE INDEX idx_feedback_student  ON feedback(student_id, created_at DESC);
CREATE INDEX idx_feedback_booking  ON feedback(booking_id) WHERE booking_id IS NOT NULL;
CREATE INDEX idx_feedback_resolved ON feedback(is_resolved, created_at) WHERE is_resolved = FALSE;
CREATE INDEX idx_feedback_rating   ON feedback(rating, created_at) WHERE rating <= 2;

CREATE INDEX idx_leave_student ON leave_periods(student_id, start_date, end_date);
CREATE INDEX idx_leave_active  ON leave_periods(student_id, start_date, end_date) WHERE is_approved = TRUE;

CREATE INDEX idx_error_logs_request_id ON error_logs(request_id);


-- seed data

INSERT INTO roles (role_name) VALUES ('student'), ('canteen_staff'), ('admin'), ('warden');

INSERT INTO hostels (name, capacity, warden_name, warden_email, warden_phone) VALUES
    ('H3', 200, 'Dr. Sharma',  'warden.h3@university.edu', '9876543210'),
    ('H4', 200, 'Prof. Gupta', 'warden.h4@university.edu', '9876543211'),
    ('H5', 250, 'Dr. Patel',   'warden.h5@university.edu', '9876543212'),
    ('H7', 300, 'Prof. Kumar', 'warden.h7@university.edu', '9876543213');

INSERT INTO booking_status (status_name, is_terminal, display_label, color_code, icon_name, counts_as_meal, counts_as_skip, sort_order) VALUES
    ('pending',   FALSE, 'Pending',   '#FF9800', 'pending',      FALSE, FALSE, 1),
    ('booked',    FALSE, 'Booked',    '#4CAF50', 'check_circle', TRUE,  FALSE, 2),
    ('cancelled', TRUE,  'Cancelled', '#F44336', 'cancel',       FALSE, FALSE, 3),
    ('used',      TRUE,  'Completed', '#2196F3', 'verified',     TRUE,  FALSE, 4),
    ('absent',    TRUE,  'No Show',   '#9E9E9E', 'person_off',   FALSE, TRUE,  5),
    ('expired',   TRUE,  'Expired',   '#795548', 'timer_off',    FALSE, FALSE, 6);

INSERT INTO meal_slots (name, display_order, start_time, end_time, booking_cutoff_time, cancel_cutoff_time, color_code, icon_name, max_bookings_per_student) VALUES
    ('Breakfast', 1, '07:00', '09:00', '06:30', '06:00', '#FF9800', 'free_breakfast', 1),
    ('Lunch',     2, '12:00', '14:00', '11:30', '11:00', '#4CAF50', 'lunch_dining',   1),
    ('Snacks',    3, '17:00', '18:00', '16:30', '16:00', '#FF5722', 'bakery_dining',  2),
    ('Dinner',    4, '20:00', '22:00', '19:30', '19:00', '#9C27B0', 'dinner_dining',  1);

INSERT INTO feedback_tags (tag_name, display_label, color_code, icon_name, sort_order) VALUES
    ('food_quality',  'Food Quality',  '#E91E63', 'restaurant',        1),
    ('hygiene',       'Hygiene',       '#00BCD4', 'cleaning_services', 2),
    ('service_speed', 'Service Speed', '#FF9800', 'timer',             3),
    ('quantity',      'Quantity',      '#8BC34A', 'scale',             4),
    ('taste',         'Taste',         '#FF5722', 'local_dining',      5),
    ('variety',       'Variety',       '#9C27B0', 'menu_book',         6);

INSERT INTO menu_items (name, type, description, short_description, allergens, spice_level, default_quantity, unit, base_price, created_by) VALUES
    ('Idli Sambar',   'veg',      'Soft idlis with sambar and chutney',   'Idli & Sambar',  'none',         1, '2 pieces', 'piece', 0.00, NULL),
    ('Poha',          'veg',      'Flattened rice with vegetables',        'Poha',           'none',         1, '1 plate',  'plate', 0.00, NULL),
    ('Bread Butter',  'veg',      'Toasted bread with butter and jam',     'Bread & Butter', 'gluten,dairy', 0, '2 slices', 'slice', 0.00, NULL),
    ('Tea',           'beverage', 'Hot masala tea',                        'Tea',            'none',         0, '1 cup',    'cup',   0.00, NULL),
    ('Rice Dal',      'veg',      'Steamed rice with dal',                 'Rice & Dal',     'none',         1, '1 plate',  'plate', 0.00, NULL),
    ('Roti Sabzi',    'veg',      'Wheat roti with mixed vegetable curry', 'Roti & Sabzi',   'gluten',       1, '2 roti',   'piece', 0.00, NULL),
    ('Chicken Curry', 'non-veg',  'Spicy chicken curry with rice',         'Chicken Curry',  'none',         2, '1 plate',  'plate', 0.00, NULL),
    ('Egg Curry',     'non-veg',  'Egg curry with roti',                   'Egg Curry',      'egg',          1, '1 plate',  'plate', 0.00, NULL),
    ('Samosa',        'snack',    'Crispy samosa with chutney',            'Samosa',         'gluten',       1, '2 pieces', 'piece', 0.00, NULL),
    ('Biscuits',      'snack',    'Assorted biscuits',                     'Biscuits',       'gluten',       0, '1 pack',   'pack',  0.00, NULL),
    ('Coffee',        'beverage', 'Hot filter coffee',                     'Coffee',         'none',         0, '1 cup',    'cup',   0.00, NULL),
    ('Biryani',       'non-veg',  'Chicken biryani with raita',            'Biryani',        'none',         2, '1 plate',  'plate', 0.00, NULL),
    ('Curd Rice',     'veg',      'Curd rice with pickle',                 'Curd Rice',      'dairy',        0, '1 plate',  'plate', 0.00, NULL),
    ('Khichdi',       'veg',      'Rice and lentil khichdi',               'Khichdi',        'none',         1, '1 plate',  'plate', 0.00, NULL),
    ('Gulab Jamun',   'dessert',  'Sweet gulab jamun',                     'Gulab Jamun',    'dairy',        0, '2 pieces', 'piece', 0.00, NULL);

INSERT INTO hostel_settings (hostel_id, booking_window_days, cancel_window_hours, max_skips_per_month, penalty_after_skips, meal_cost, currency)
SELECT id, 7, 1, 5, 3, 0.00, 'INR' FROM hostels;

-- Admin seed — replace password via env var before deploy
DO $$
DECLARE
    v_role_id INTEGER;
    v_user_id INTEGER;
    v_password TEXT := 'CHANGE_ME_BEFORE_DEPLOY';
BEGIN
    SELECT id INTO v_role_id FROM roles WHERE role_name = 'admin';
    INSERT INTO users (role_id, email, password_hash, email_verified)
    VALUES (v_role_id, 'admin@university.edu', crypt(v_password, gen_salt('bf')), TRUE)
    RETURNING id INTO v_user_id;
    INSERT INTO staff (user_id, first_name, last_name, phone, designation, can_scan_qr, can_edit_menu, can_view_reports, can_manage_staff)
    VALUES (v_user_id, 'System', 'Admin', '9999999999', 'admin', TRUE, TRUE, TRUE, TRUE);
END $$;

-- Post-seed: partial index with status IDs resolved by name, not hardcoded
DO $$
DECLARE
    v_pending INTEGER;
    v_booked  INTEGER;
BEGIN
    SELECT id INTO v_pending FROM booking_status WHERE status_name = 'pending';
    SELECT id INTO v_booked  FROM booking_status WHERE status_name = 'booked';
    EXECUTE format(
        'CREATE INDEX idx_bookings_active ON bookings(student_id, date, status_id) WHERE status_id IN (%s, %s)',
        v_pending, v_booked
    );
END $$;


-- views

CREATE OR REPLACE VIEW view_todays_bookings AS
SELECT
    b.id AS booking_id,
    b.qr_token,
    s.uid AS student_uid,
    s.first_name || ' ' || COALESCE(s.middle_name || ' ', '') || s.last_name AS student_name,
    h.name AS hostel,
    s.room_number,
    ms.name AS meal_slot,
    bs.display_label AS status,
    b.status_id,
    b.created_at,
    b.confirmed_at,
    b.used_at
FROM bookings b
JOIN students s        ON b.student_id   = s.id
LEFT JOIN hostels h    ON s.hostel_id    = h.id
JOIN meal_slots ms     ON b.meal_slot_id = ms.id
JOIN booking_status bs ON b.status_id    = bs.id
WHERE b.date = CURRENT_DATE;

CREATE OR REPLACE VIEW view_meal_count_today AS
SELECT
    ms.name AS meal_slot,
    h.name  AS hostel,
    bs.display_label AS status,
    COUNT(b.id) AS total_count,
    SUM(CASE WHEN bs.status_name = 'booked' THEN 1 ELSE 0 END) AS confirmed_count,
    SUM(CASE WHEN bs.status_name = 'used'   THEN 1 ELSE 0 END) AS served_count
FROM bookings b
JOIN meal_slots ms     ON b.meal_slot_id = ms.id
JOIN students s        ON b.student_id   = s.id
LEFT JOIN hostels h    ON s.hostel_id    = h.id
JOIN booking_status bs ON b.status_id    = bs.id
WHERE b.date = CURRENT_DATE
GROUP BY ms.name, h.name, bs.display_label, ms.display_order
ORDER BY ms.display_order, h.name;

CREATE OR REPLACE VIEW view_student_booking_history AS
SELECT
    s.uid AS student_uid,
    s.first_name || ' ' || COALESCE(s.middle_name || ' ', '') || s.last_name AS student_name,
    h.name AS hostel,
    b.date,
    ms.name AS meal_slot,
    bs.display_label AS status,
    bs.color_code    AS status_color,
    b.confirmed_at,
    b.used_at,
    b.cancelled_at,
    b.skip_reason,
    b.skip_reason_category,
    b.qr_token,
    (SELECT COUNT(*) FROM booking_items bi WHERE bi.booking_id = b.id) AS item_count
FROM bookings b
JOIN students s        ON b.student_id   = s.id
LEFT JOIN hostels h    ON s.hostel_id    = h.id
JOIN meal_slots ms     ON b.meal_slot_id = ms.id
JOIN booking_status bs ON b.status_id    = bs.id
ORDER BY b.date DESC, ms.display_order;

CREATE OR REPLACE VIEW view_active_tokens AS
SELECT
    b.id AS booking_id,
    b.student_id,
    s.uid AS student_uid,
    s.first_name || ' ' || s.last_name AS student_name,
    b.qr_token,
    b.qr_expires_at,
    b.meal_slot_id,
    ms.name AS meal_slot,
    b.date,
    b.meal_menu_id,
    mm.special_notes,
    CASE
        WHEN b.qr_expires_at < CURRENT_TIMESTAMP THEN 'expired'
        WHEN bs.status_name  = 'booked'          THEN 'active'
        ELSE 'inactive'
    END AS token_state
FROM bookings b
JOIN students s        ON b.student_id   = s.id
JOIN meal_slots ms     ON b.meal_slot_id = ms.id
JOIN meal_menus mm     ON b.meal_menu_id = mm.id
JOIN booking_status bs ON b.status_id    = bs.id
WHERE bs.status_name = 'booked'
  AND b.date = CURRENT_DATE;

CREATE OR REPLACE VIEW view_student_leave_periods AS
SELECT
    lp.id,
    s.uid AS student_uid,
    s.first_name || ' ' || s.last_name AS student_name,
    h.name AS hostel,
    s.room_number,
    lp.start_date,
    lp.end_date,
    lp.reason,
    lp.reason_category,
    lp.is_approved,
    st.first_name || ' ' || st.last_name AS approved_by_name,
    lp.approved_at,
    (lp.end_date - lp.start_date + 1) AS total_days,
    CASE
        WHEN lp.end_date < CURRENT_DATE                                    THEN 'completed'
        WHEN lp.start_date <= CURRENT_DATE AND lp.end_date >= CURRENT_DATE THEN 'active'
        ELSE 'upcoming'
    END AS leave_state
FROM leave_periods lp
JOIN students s     ON lp.student_id  = s.id
LEFT JOIN hostels h ON s.hostel_id    = h.id
LEFT JOIN staff st  ON lp.approved_by = st.id
ORDER BY lp.start_date DESC;
