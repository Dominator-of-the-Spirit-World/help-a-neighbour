SET sql_mode = '';

DROP DATABASE IF EXISTS nearneed;
CREATE DATABASE nearneed
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE nearneed;


CREATE TABLE users (
    id               INT            NOT NULL AUTO_INCREMENT,
    name             VARCHAR(100)   NOT NULL,
    email            VARCHAR(120)   NULL,
    phone            VARCHAR(15)    NULL,
    password_hash    VARCHAR(256)   NOT NULL,
    city             VARCHAR(80)    NOT NULL DEFAULT '',
    state            VARCHAR(80)    NOT NULL DEFAULT '',
    pincode          VARCHAR(10)    NOT NULL DEFAULT '',
    street           VARCHAR(200)   NOT NULL DEFAULT '',
    bio              TEXT           NOT NULL DEFAULT '',
    gender           VARCHAR(20)    NOT NULL DEFAULT '',
    age_group        VARCHAR(20)    NOT NULL DEFAULT '',
    profession       VARCHAR(80)    NOT NULL DEFAULT '',
    lat              DOUBLE         NOT NULL DEFAULT 0.0,
    lng              DOUBLE         NOT NULL DEFAULT 0.0,
    is_super_admin   TINYINT(1)     NOT NULL DEFAULT 0,
    is_admin         TINYINT(1)     NOT NULL DEFAULT 0,
    is_moderator     TINYINT(1)     NOT NULL DEFAULT 0,
    is_banned        TINYINT(1)     NOT NULL DEFAULT 0,
    is_verified      TINYINT(1)     NOT NULL DEFAULT 0,
    aadhaar_verified TINYINT(1)     NOT NULL DEFAULT 0,
    aadhaar_last4    VARCHAR(4)     NOT NULL DEFAULT '',
    rating           DOUBLE         NOT NULL DEFAULT 5.0,
    helped_count     INT            NOT NULL DEFAULT 0,
    req_count        INT            NOT NULL DEFAULT 0,
    created_at       DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),

    
    UNIQUE INDEX ix_users_email (email),
    UNIQUE INDEX ix_users_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;



CREATE TABLE requests (
    id          INT           NOT NULL AUTO_INCREMENT,
    user_id     INT           NOT NULL,
    title       VARCHAR(200)  NOT NULL,
    description TEXT          NOT NULL,
    category    VARCHAR(60)   NOT NULL DEFAULT 'General',
    urgency     VARCHAR(20)   NOT NULL DEFAULT 'Low',
    location    VARCHAR(200)  NOT NULL DEFAULT '',
    lat         DOUBLE        NOT NULL DEFAULT 0.0,
    lng         DOUBLE        NOT NULL DEFAULT 0.0,
    status      VARCHAR(20)   NOT NULL DEFAULT 'open',
    helper_id   INT           NULL,
    photo_url   VARCHAR(300)  NOT NULL DEFAULT '',
    is_deleted  TINYINT(1)    NOT NULL DEFAULT 0,
    deleted_by  INT           NULL,
    created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                              ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),

    -- Status + deleted filter (used on every feed query)
    INDEX ix_requests_status_deleted (status, is_deleted),

    -- Fast lookup of all requests by a specific user
    INDEX ix_requests_user_id (user_id),

    CONSTRAINT fk_requests_user
        FOREIGN KEY (user_id)   REFERENCES users(id) ON DELETE CASCADE,

    CONSTRAINT fk_requests_helper
        FOREIGN KEY (helper_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ───────────────────────────────────────────────────────────────
--  TABLE: notices
--  Community notice-board posts (water cuts, events, safety
--  alerts, etc.). Soft-deleted via is_deleted flag.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE notices (
    id         INT           NOT NULL AUTO_INCREMENT,
    user_id    INT           NOT NULL,
    title      VARCHAR(200)  NOT NULL,
    body       TEXT          NOT NULL,
    category   VARCHAR(40)   NOT NULL DEFAULT 'General',
    lat        DOUBLE        NOT NULL DEFAULT 0.0,
    lng        DOUBLE        NOT NULL DEFAULT 0.0,
    is_deleted TINYINT(1)    NOT NULL DEFAULT 0,
    created_at DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    INDEX ix_notices_user_id (user_id),

    CONSTRAINT fk_notices_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ───────────────────────────────────────────────────────────────
--  TABLE: otp_records
--  One row per OTP issued. purpose distinguishes between
--  registration, login, password reset, and Aadhaar flows.
--  Rows are marked used=1 after verification, never deleted,
--  so there is a full audit trail of all OTP activity.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE otp_records (
    id         INT          NOT NULL AUTO_INCREMENT,
    contact    VARCHAR(120) NOT NULL,
    otp        VARCHAR(6)   NOT NULL,
    purpose    VARCHAR(30)  NOT NULL DEFAULT 'register',
    used       TINYINT(1)   NOT NULL DEFAULT 0,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),

    -- Active OTP lookup (contact + purpose + used=0 + recent timestamp)
    INDEX ix_otp_contact_purpose (contact, purpose, used)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ───────────────────────────────────────────────────────────────
--  TABLE: messages
--  Direct messages between users. Soft-deleted so admins can
--  review flagged content after the user deletes it.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE messages (
    id           INT       NOT NULL AUTO_INCREMENT,
    sender_id    INT       NOT NULL,
    recipient_id INT       NOT NULL,
    text         TEXT      NOT NULL,
    is_read      TINYINT(1) NOT NULL DEFAULT 0,
    is_deleted   TINYINT(1) NOT NULL DEFAULT 0,
    deleted_by   INT       NULL,
    created_at   DATETIME  NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),

    -- Thread queries: all messages between two users
    INDEX ix_messages_thread (sender_id, recipient_id),
    INDEX ix_messages_recipient (recipient_id),

    CONSTRAINT fk_messages_sender
        FOREIGN KEY (sender_id)    REFERENCES users(id) ON DELETE CASCADE,

    CONSTRAINT fk_messages_recipient
        FOREIGN KEY (recipient_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ───────────────────────────────────────────────────────────────
--  TABLE: notifications
--  In-app inbox notifications. Types: info, success, emergency.
--  is_read=0 drives the unread badge count in the frontend.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE notifications (
    id         INT          NOT NULL AUTO_INCREMENT,
    user_id    INT          NOT NULL,
    title      VARCHAR(200) NOT NULL,
    message    TEXT         NOT NULL DEFAULT '',
    type       VARCHAR(20)  NOT NULL DEFAULT 'info',
    is_read    TINYINT(1)   NOT NULL DEFAULT 0,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),

    -- Unread-count query: user_id + is_read
    INDEX ix_notifications_user_read (user_id, is_read),

    CONSTRAINT fk_notifications_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ───────────────────────────────────────────────────────────────
--  TABLE: login_logs
--  Audit log of every login attempt (success or failure).
--  user_id is NULL for failed attempts where no account exists.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE login_logs (
    id         INT          NOT NULL AUTO_INCREMENT,
    user_id    INT          NULL,
    contact    VARCHAR(120) NOT NULL DEFAULT '',
    success    TINYINT(1)   NOT NULL DEFAULT 1,
    ip_address VARCHAR(45)  NOT NULL DEFAULT '',
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    INDEX ix_login_logs_user_id (user_id),
    INDEX ix_login_logs_created (created_at),

    CONSTRAINT fk_login_logs_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ═══════════════════════════════════════════════════════════════
--  SEED: Super Admin account
--  Password hash below is bcrypt of "Admin@1234".
--  Change the password immediately after first login.
--
--  To generate a new hash in Python:
--    from werkzeug.security import generate_password_hash
--    print(generate_password_hash("YourNewPassword"))
--  Then replace the hash value below.
-- ═══════════════════════════════════════════════════════════════
INSERT INTO users (
    name, email, password_hash,
    city, lat, lng,
    is_super_admin, is_admin, is_verified, aadhaar_verified
) VALUES (
    'NearNeed Admin',
    'nearneed2006@gmail.com',
    'scrypt:32768:8:1$U8uBAGxnoR0Mb0Qr$01be9c984016da171cb53f70ed34ad5aa1713284c64b2b772d70431937e4fc08f137321a2608e267386ba1856ae0ce9c71be25c73afdb5687f088b863c362859',
    'Mumbai', 19.0760, 72.8777,
    1, 1, 1, 1
);

SELECT 'NearNeed database created successfully.' AS status;
