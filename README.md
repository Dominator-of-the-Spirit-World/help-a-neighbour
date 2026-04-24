# NearNeed 🤝

**A hyperlocal community help platform** — connect with neighbors to give and receive help in real time.

NearNeed lets people in the same neighborhood post help requests, respond to emergencies, share community notices, and message each other — all backed by a live Flask + MySQL backend with JWT auth, OTP verification, and real-time Server-Sent Events.

---

## Features

- **Help Requests** — Post requests by category (Medical, Household, Transport, etc.) and urgency level. Nearby users are notified instantly.
- **Emergency Alerts** — Emergency-tagged requests trigger instant email notifications and in-app alerts to all users within 5 km.
- **Community Notices** — Broadcast announcements to your neighborhood (lost & found, events, alerts).
- **OTP Login** — Register and log in via email OTP. No SMS gateway needed in dev mode — OTP is printed to the console.
- **Aadhaar Verification** — Optional Aadhaar-based identity verification (OTP flow, last-4-digits stored).
- **Real-time Messaging** — Direct messages between users with Server-Sent Events (SSE) push for live chat.
- **Notifications** — In-app notification feed with profession-matched alerts (e.g. Doctors get notified of Medical requests nearby).
- **Admin Panel** — Super Admin, Admin, and Moderator roles with full user management, ban/unban, login audit logs, and live stats.
- **Offline / Demo Mode** — Frontend gracefully falls back to demo users if the backend is unreachable, so the UI is always testable.

---

## Tech Stack

| Layer     | Technology                                   |
|-----------|----------------------------------------------|
| Backend   | Python 3 · Flask · Flask-SQLAlchemy · PyMySQL |
| Database  | MySQL 8+                                     |
| Auth      | JWT (PyJWT) · Werkzeug password hashing       |
| Realtime  | Server-Sent Events (SSE) via Flask streaming  |
| Email     | Gmail SMTP (smtplib) · HTML + plain text      |
| Frontend  | Vanilla HTML/CSS/JS · DM Sans font            |
| Dev Server| Python `http.server` (serve.py, port 8080)   |

---

## Project Structure

```
nearneed/
├── Backend/
│   ├── app.py            ← Flask API server (port 5000)
│   ├── nearneed.sql      ← MySQL schema + seed data (run once)
│   ├── requirements.txt  ← Python dependencies
│   └── .env              ← Your local credentials (never commit this)
└── Frontend/
    ├── index.html        ← Landing page
    ├── login.html        ← Password + OTP login, forgot password
    ├── register.html     ← Multi-step registration with OTP + Aadhaar
    ├── dashboard.html    ← Main app (requests, notices, messages, admin)
    ├── app.js            ← Shared auth, API helpers, toast, chat cache
    └── serve.py          ← Static file server (port 8080)
```

---

## Prerequisites

- **Python 3.9+**
- **MySQL 8+** (running locally or remote)
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) *(optional — only needed for real email delivery)*

---

## Setup & Installation

### 1. Clone the repository

```bash
git clone https://github.com/yourname/nearneed.git
cd nearneed
```

### 2. Set up the MySQL database

Run the SQL schema once to create the database, tables, and the Super Admin account:

```bash
mysql -u root -p < Backend/nearneed.sql
```

This creates the `nearneed` database and a default Super Admin:

| Field    | Value                    |
|----------|--------------------------|
| Email    | `nearneed2006@gmail.com` |
| Password | `Admin@1234`             |

### 3. Configure environment variables

Create (or edit) `Backend/.env`:

```env
# MySQL connection
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_DB=nearneed

# JWT signing key — change this to a long random string in production
SECRET_KEY=nearneed-change-me

# Gmail SMTP — leave blank to stay in DEV mode (OTPs print to console)
SMTP_SENDER=nearneed2006@gmail.com
SMTP_PASSWORD=your_16_char_app_password_here

# Super Admin email (auto-elevated on first login)
SUPER_ADMIN_EMAIL=nearneed2006@gmail.com

# Public URL for email links (update for production)
APP_URL=http://localhost:8080
```

> **DEV Mode:** If `SMTP_PASSWORD` is blank or set to `your_16_char_app_password_here`, the server runs in DEV mode — all OTPs are printed to the terminal instead of being emailed. This is the default for local development.

### 4. Install Python dependencies

```bash
cd Backend
pip install -r requirements.txt
```

### 5. Run the backend

```bash
python app.py
```

You should see:

```
=======================================================
  NearNeed v4.1  (MySQL)
  http://127.0.0.1:5000/
  Super Admin: nearneed2006@gmail.com
=======================================================

  DEV MODE - OTPs printed to console, emails skipped
  MySQL connection OK
```

### 6. Run the frontend

Open a **second terminal**:

```bash
cd Frontend
python serve.py
```

Your browser opens automatically at **http://localhost:8080**.

---

## API Reference

All endpoints are prefixed with `/api`. Protected routes require `Authorization: Bearer <jwt_token>`.

### Auth

| Method | Endpoint              | Auth | Description                              |
|--------|-----------------------|------|------------------------------------------|
| POST   | `/send-otp`           | —    | Send OTP to email or phone               |
| POST   | `/verify-otp`         | —    | Verify OTP (returns JWT for login flow)  |
| POST   | `/register`           | —    | Create account                           |
| POST   | `/login`              | —    | Password login, returns JWT              |
| POST   | `/forgot-password`    | —    | Send password reset OTP                  |
| POST   | `/reset-password`     | —    | Reset password with OTP                  |
| POST   | `/check-contact`      | —    | Check if email/phone is already taken    |
| POST   | `/aadhaar/send-otp`   | —    | Send Aadhaar verification OTP            |
| POST   | `/aadhaar/verify-otp` | —    | Confirm Aadhaar OTP                      |

### Help Requests

| Method | Endpoint                        | Auth | Description                      |
|--------|---------------------------------|------|----------------------------------|
| GET    | `/requests`                     | ✓    | List open requests near you      |
| POST   | `/requests`                     | ✓    | Create a help request            |
| DELETE | `/requests/<id>`                | ✓    | Delete a request (owner/staff)   |
| POST   | `/requests/<id>/accept`         | ✓    | Volunteer to help                |
| POST   | `/requests/<id>/complete`       | ✓    | Mark request resolved            |
| GET    | `/my-requests`                  | ✓    | Your posted + helping requests   |
| POST   | `/nearby-requests`              | ✓    | Requests within a custom radius  |

### Notices, Messages, Notifications

| Method | Endpoint                        | Auth | Description                      |
|--------|---------------------------------|------|----------------------------------|
| GET    | `/notices`                      | ✓    | List community notices           |
| POST   | `/notices`                      | ✓    | Post a notice                    |
| DELETE | `/notices/<id>`                 | ✓    | Delete a notice (owner/staff)    |
| GET    | `/messages/<peer_id>`           | ✓    | Fetch message thread             |
| POST   | `/messages/<peer_id>`           | ✓    | Send a message                   |
| DELETE | `/messages/delete/<msg_id>`     | ✓    | Delete a message                 |
| GET    | `/contacts`                     | ✓    | List all message contacts        |
| GET    | `/notifications`                | ✓    | Notification feed (last 50)      |
| POST   | `/notifications/read-all`       | ✓    | Mark all notifications read      |

### Profile & Admin

| Method | Endpoint                         | Auth         | Description              |
|--------|----------------------------------|--------------|--------------------------|
| GET    | `/profile`                       | ✓            | Get own profile          |
| PUT    | `/profile`                       | ✓            | Update profile           |
| GET    | `/admin/stats`                   | Staff        | Platform stats           |
| GET    | `/admin/users`                   | Staff        | All users + login logs   |
| POST   | `/admin/ban/<id>`                | Staff        | Ban / unban a user       |
| DELETE | `/admin/delete-user/<id>`        | Admin        | Soft-delete a user       |
| POST   | `/admin/moderators/<id>`         | Super Admin  | Grant/revoke moderator   |
| GET    | `/events/<room>`                 | ✓ (token QS) | SSE stream for realtime  |

### Health check

```
GET /api/health
```
Returns `{"status": "ok", "db": "connected", "version": "4.1"}`.

---

## Real-time Events (SSE)

Connect to `/api/events/<room>?token=<jwt>` to receive push events.

| Room            | Events emitted                          |
|-----------------|-----------------------------------------|
| `requests`      | `new_request`, `update_request`, `delete_request` |
| `notices`       | `new_notice`                            |
| `chat_<min>_<max>` | `new_message`, `delete_message`      |
| `user_<id>`     | `new_message_notif`, `notification`    |
| `admin`         | `new_user`, `user_banned`, `moderator_changed` |

---

## User Roles

| Role        | Permissions                                                          |
|-------------|----------------------------------------------------------------------|
| Member      | Post/manage own requests & notices, message users, update profile    |
| Moderator   | All of the above + view admin panel, delete any post, ban users      |
| Admin       | All of the above + delete users, manage moderators                   |
| Super Admin | Full access, cannot be banned or deleted, auto-elevated by email match |

The Super Admin is identified by the `SUPER_ADMIN_EMAIL` env variable and is automatically elevated on every login.

---

## Offline / Demo Mode

If the Flask backend is unreachable, the frontend automatically:

- Shows a yellow warning banner on the login page
- Falls back to three built-in demo accounts for password login

| Name          | Email              | Phone      | Password   | Role  |
|---------------|--------------------|------------|------------|-------|
| Rahul Sharma  | rahul@demo.com     | 9876543210 | Test@1234  | Admin |
| Priya Patel   | priya@demo.com     | 9876543211 | Test@1234  | User  |
| Vikram Khanna | vikram@demo.com    | 9876543212 | Test@1234  | User  |

Demo logins use `token: 'demo-token'` and data is stored only in `sessionStorage`. No real data is saved.

---

## OTP Flow (DEV Mode)

When `SMTP_PASSWORD` is not set, OTPs are printed directly to the Flask console:

```
==================================================
  [DEV OTP] user@example.com: 483921  (register)
==================================================
```

The frontend also displays the OTP in a toast notification when the server returns `dev_otp` in the response, so you never need to switch to the terminal during development.

---

## Database Schema

The MySQL database (`nearneed`) contains these tables:

| Table          | Purpose                                         |
|----------------|-------------------------------------------------|
| `users`        | Accounts, roles, location, Aadhaar status       |
| `requests`     | Help requests with category, urgency, GPS       |
| `notices`      | Community notice board posts                    |
| `otp_records`  | OTP log with expiry and used flag               |
| `messages`     | Direct messages between users                   |
| `notifications`| In-app notification feed                        |
| `login_logs`   | Login audit trail (success/failure + IP)        |

---

## Environment Variables Reference

| Variable            | Default                      | Required | Description                          |
|---------------------|------------------------------|----------|--------------------------------------|
| `MYSQL_USER`        | `root`                       | Yes      | MySQL username                       |
| `MYSQL_PASSWORD`    | *(empty)*                    | Yes      | MySQL password                       |
| `MYSQL_HOST`        | `localhost`                  | No       | MySQL host                           |
| `MYSQL_PORT`        | `3306`                       | No       | MySQL port                           |
| `MYSQL_DB`          | `nearneed`                   | No       | Database name                        |
| `SECRET_KEY`        | `nearneed-change-me`         | **Yes**  | JWT signing secret (change in prod!) |
| `SMTP_SENDER`       | `nearneed2006@gmail.com`     | No       | Gmail sender address                 |
| `SMTP_PASSWORD`     | *(empty)*                    | No       | Gmail App Password (enables email)   |
| `SUPER_ADMIN_EMAIL` | `nearneed2006@gmail.com`     | No       | Email auto-elevated to Super Admin   |
| `APP_URL`           | `http://localhost:8080`      | No       | Base URL used in email links         |

---

## Troubleshooting

**Backend won't start — "Cannot connect to MySQL"**
- Make sure MySQL is running: `sudo systemctl start mysql` (Linux) or start MySQL from System Preferences (macOS)
- Verify your `.env` credentials match your MySQL setup
- Confirm the schema was imported: `mysql -u root -p -e "SHOW DATABASES;"`

**OTP not arriving in email**
- Check that `SMTP_PASSWORD` is a Gmail **App Password** (16 chars, no spaces), not your regular Gmail password
- Make sure 2-Step Verification is enabled on your Google account
- In DEV mode (no password set), OTPs print to the Flask terminal — check there first

**"Backend offline" banner on login page**
- Flask is not running. Open a terminal and run `python app.py` from the `Backend/` folder
- Confirm the backend is up by visiting `http://localhost:5000/api/health`

**Requests posted by one user not visible to another**
- Both users must have location set. If GPS is not set (lat=0, lng=0), requests are still shown to all users
- The default visible radius is 50 km

**`ModuleNotFoundError` on startup**
```bash
pip install -r requirements.txt
```

---

## License

MIT License — free to use, modify, and distribute. Attribution appreciated.

---

*Built with Flask, vanilla JS, and a lot of ☕.*
