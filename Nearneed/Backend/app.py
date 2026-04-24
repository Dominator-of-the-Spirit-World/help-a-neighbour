import os, sys, math, random, smtplib, string, datetime, json, threading, queue, decimal
from functools import wraps
import hashlib

# Safe JSON encoder — handles decimal.Decimal returned by MySQL DOUBLE columns
class _DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal): return float(o)
        return super().default(o)

def _safe_dumps(obj):
    return json.dumps(obj, cls=_DecimalEncoder)
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from dotenv import load_dotenv
    load_dotenv()

    print("MYSQL_USER:", os.environ.get("MYSQL_USER"))
    print("MYSQL_PASSWORD:", os.environ.get("MYSQL_PASSWORD"))

except ImportError:
    print("dotenv not installed")

from flask import Flask, request, jsonify, g, Response, stream_with_context, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from sqlalchemy.dialects.mysql import DOUBLE

_DEBUG_LOG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "debug-b2e4a7.log"))
def _dbg(hypothesisId, location, message, data=None, runId=None):
    # Never log secrets (tokens/passwords/PII). Keep payload small.
    try:
        payload = {
            "sessionId": "b2e4a7",
            "runId": runId or "pre-fix",
            "hypothesisId": hypothesisId,
            "location": location,
            "message": message,
            "data": data or {},        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass

try:
    _dbg("BOOT", "Backend/app.py:startup", "Backend module loaded", {"pid": os.getpid()})
except Exception:
    pass


def _mysql_uri():
    from urllib.parse import quote_plus
    user = os.environ.get("MYSQL_USER") or "root"
    pw   = os.environ.get("MYSQL_PASSWORD", "")
    host = os.environ.get("MYSQL_HOST") or "localhost"
    port = os.environ.get("MYSQL_PORT") or "3306"
    db   = os.environ.get("MYSQL_DB") or "nearneed"
    return f"mysql+pymysql://{user}:{quote_plus(pw)}@{host}:{port}/{db}?charset=utf8mb4"


_backend_dir  = os.path.dirname(os.path.abspath(__file__))
_frontend_dir = os.path.abspath(os.path.join(_backend_dir,'..','frontend'))
if not os.path.isdir(_frontend_dir):
    _frontend_dir = _backend_dir

app = Flask(__name__, static_folder=_frontend_dir, static_url_path='/static')
CORS(app, origins=["*"], allow_headers=["Content-Type","Authorization"], expose_headers=["Authorization"], supports_credentials=False)

# FIX: Teach Flask's jsonify to handle decimal.Decimal (MySQL DOUBLE columns)
import flask.json.provider as _fjp
class _SafeJSONProvider(_fjp.DefaultJSONProvider):
    @staticmethod
    def default(obj):
        if isinstance(obj, decimal.Decimal): return float(obj)
        return _fjp.DefaultJSONProvider.default(obj)
app.json_provider_class = _SafeJSONProvider
app.json = _SafeJSONProvider(app)

@app.before_request
def _dbg_before_request():
    try:
        if request.path.startswith("/api"):
            _dbg(
                "H10",
                "Backend/app.py:before_request",
                "Incoming API request",
                {
                    "method": request.method,
                    "path": request.path,
                    "ct": request.headers.get("Content-Type", ""),
                    "accept": request.headers.get("Accept", ""),
                    "origin": request.headers.get("Origin", ""),
                    "has_auth": request.headers.get("Authorization", "").startswith("Bearer "),
                },
            )
    except Exception:
        pass

@app.errorhandler(Exception)
def handle_error(e):
    code = 500
    if hasattr(e, 'code'): code = e.code
    return jsonify({"error": str(e), "success": False}), code

@app.after_request
def _cors_headers(response):
    # Ensure CORS headers are present even on errors handled by errorhandler
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
    return response

@app.route('/api', methods=['GET','OPTIONS'])
def api_root():
    if request.method == 'OPTIONS':
        resp = app.make_default_options_response()
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
        return resp
    return jsonify({'status':'NearNeed API v4.1','version':'4.1'})

# Teach Flask's jsonify to also handle Decimal (login/register response bodies)
app.json.default = lambda o: float(o) if isinstance(o, decimal.Decimal) else o
app.config.update(
    SECRET_KEY                     = os.environ.get("SECRET_KEY","nearneed-change-me"),
    SQLALCHEMY_DATABASE_URI        = _mysql_uri(),
    SQLALCHEMY_TRACK_MODIFICATIONS = False,
    SQLALCHEMY_ENGINE_OPTIONS      = {"pool_recycle":1800,"pool_pre_ping":True},
    JWT_EXPIRY_HOURS               = 24,
    OTP_EXPIRY_MINUTES             = 10,
    RADIUS_KM                      = 50.0,  # wide radius so all posts are visible
)

SMTP_SENDER       = os.environ.get("SMTP_SENDER","nearneed2006@gmail.com")
SMTP_PASSWORD     = os.environ.get("SMTP_PASSWORD","")
DEV_MODE          = SMTP_PASSWORD in ("your_16_char_app_password_here","")
SUPER_ADMIN_EMAIL = os.environ.get("SUPER_ADMIN_EMAIL","nearneed2006@gmail.com").lower()

db        = SQLAlchemy(app)
_sse_subs = {}
_sse_lock = threading.Lock()

@app.route('/')
def serve_index():
    return send_from_directory(_frontend_dir, 'index.html')

@app.route('/<path:filename>')
def serve_frontend_file(filename):
    """Serve any frontend static file (html, js, css, images).
    IMPORTANT: Flask matches explicit /api/... routes FIRST.
    """
    if filename.startswith('api/'):
        return jsonify({"error": "API route not found", "success": False}), 404
    return send_from_directory(_frontend_dir, filename)

@app.route('/api/health', methods=['GET'])
def health_check():
    try:
        with db.engine.connect() as conn: conn.execute(db.text('SELECT 1'))
        return jsonify({'status':'ok','db':'connected','version':'4.1'})
    except Exception as e:
        return jsonify({'status':'error','db':str(e)}),500


# ── MODELS ────────────────────────────────────────────────────
class User(db.Model):
    __tablename__ = "users"
    id               = db.Column(db.Integer,    primary_key=True)
    name             = db.Column(db.String(100), nullable=False)
    email            = db.Column(db.String(120), unique=True, nullable=True)
    phone            = db.Column(db.String(15),  unique=True, nullable=True)
    password_hash    = db.Column(db.String(256), nullable=False)
    city             = db.Column(db.String(80),  default="")
    state            = db.Column(db.String(80),  default="")
    pincode          = db.Column(db.String(10),  default="")
    street           = db.Column(db.String(200), default="")
    bio              = db.Column(db.Text,         default="")
    gender           = db.Column(db.String(20),  default="")
    age_group        = db.Column(db.String(20),  default="")
    profession       = db.Column(db.String(80),  default="")
    lat              = db.Column(DOUBLE,          default=0.0)
    lng              = db.Column(DOUBLE,          default=0.0)
    is_super_admin   = db.Column(db.Boolean,      default=False)
    is_admin         = db.Column(db.Boolean,      default=False)
    is_moderator     = db.Column(db.Boolean,      default=False)
    is_banned        = db.Column(db.Boolean,      default=False)
    is_verified      = db.Column(db.Boolean,      default=False)
    aadhaar_verified = db.Column(db.Boolean,      default=False)
    aadhaar_last4    = db.Column(db.String(4),    default="")
    rating           = db.Column(DOUBLE,          default=5.0)
    helped_count     = db.Column(db.Integer,      default=0)
    req_count        = db.Column(db.Integer,      default=0)
    created_at       = db.Column(db.DateTime,     default=datetime.datetime.utcnow)

    def is_staff(self):   return self.is_super_admin or self.is_admin or self.is_moderator
    def role_label(self):
        if self.is_super_admin: return "super_admin"
        if self.is_admin:       return "admin"
        if self.is_moderator:   return "moderator"
        return "member"
    def to_dict(self,include_private=False):
        d={"id":self.id,"name":self.name,"city":self.city,
           "is_admin":self.is_admin,"is_super_admin":self.is_super_admin,
           "is_moderator":self.is_moderator,"is_verified":self.is_verified,
           "aadhaar_verified":self.aadhaar_verified,"is_banned":self.is_banned,
           "role":self.role_label(),"rating":round(float(self.rating or 0),1),
           "helped":self.helped_count,"requested":self.req_count,
           "initials":"".join(w[0] for w in self.name.split() if w)[:2].upper(),
           "joined":self.created_at.strftime("%b %Y") if self.created_at else ""}
        if include_private:
            d.update({"email":self.email,"phone":self.phone,
                      "lat":float(self.lat or 0),"lng":float(self.lng or 0),
                      "pincode":self.pincode,"state":self.state,"bio":self.bio,
                      "gender":self.gender,"aadhaar_last4":self.aadhaar_last4,
                      "profession":self.profession})
        return d

class HelpRequest(db.Model):
    __tablename__ = "requests"
    id          = db.Column(db.Integer,     primary_key=True)
    user_id     = db.Column(db.Integer,     db.ForeignKey("users.id"),nullable=False)
    title       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text,        nullable=False)
    category    = db.Column(db.String(60),  default="General")
    urgency     = db.Column(db.String(20),  default="Low")
    location    = db.Column(db.String(200), default="")
    lat         = db.Column(DOUBLE,          default=0.0)
    lng         = db.Column(DOUBLE,          default=0.0)
    status      = db.Column(db.String(20),  default="open")
    helper_id   = db.Column(db.Integer,     db.ForeignKey("users.id"),nullable=True)
    photo_url   = db.Column(db.String(300), default="")
    is_deleted  = db.Column(db.Boolean,     default=False)
    deleted_by  = db.Column(db.Integer,     nullable=True)
    created_at  = db.Column(db.DateTime,    default=datetime.datetime.utcnow)
    updated_at  = db.Column(db.DateTime,    default=datetime.datetime.utcnow,
                                            onupdate=datetime.datetime.utcnow)
    user   = db.relationship("User",foreign_keys=[user_id])
    helper = db.relationship("User",foreign_keys=[helper_id])
    def to_dict(self,viewer_lat=None,viewer_lng=None):
        d={"id":self.id,"title":self.title,"description":self.description,
           "category":self.category,"urgency":self.urgency,"status":self.status,
           "location":self.location,"created_at":self.created_at.isoformat(),
           "user":self.user.to_dict() if self.user else {}}
        d["lat"] = float(self.lat or 0)
        d["lng"] = float(self.lng or 0)
        if viewer_lat is not None and viewer_lng is not None:
            d["distance_km"]=round(haversine(viewer_lat,viewer_lng,self.lat,self.lng),2)
        if self.helper: d["helper"]=self.helper.to_dict()
        return d

class Notice(db.Model):
    __tablename__ = "notices"
    id         = db.Column(db.Integer,     primary_key=True)
    user_id    = db.Column(db.Integer,     db.ForeignKey("users.id"),nullable=False)
    title      = db.Column(db.String(200), nullable=False)
    body       = db.Column(db.Text,        nullable=False)
    category   = db.Column(db.String(40),  default="General")
    lat        = db.Column(DOUBLE,          default=0.0)
    lng        = db.Column(DOUBLE,          default=0.0)
    is_deleted = db.Column(db.Boolean,     default=False)
    created_at = db.Column(db.DateTime,    default=datetime.datetime.utcnow)
    user       = db.relationship("User")
    def to_dict(self):
        return {"id":self.id,"title":self.title,"body":self.body,
                "category":self.category,"created_at":self.created_at.isoformat(),
                "user":self.user.to_dict() if self.user else {}}

class OTPRecord(db.Model):
    __tablename__ = "otp_records"
    id         = db.Column(db.Integer,     primary_key=True)
    contact    = db.Column(db.String(120), nullable=False)
    otp        = db.Column(db.String(6),   nullable=False)
    purpose    = db.Column(db.String(30),  default="register")
    used       = db.Column(db.Boolean,     default=False)
    created_at = db.Column(db.DateTime,    default=datetime.datetime.utcnow)

class Message(db.Model):
    __tablename__ = "messages"
    id           = db.Column(db.Integer,  primary_key=True)
    sender_id    = db.Column(db.Integer,  db.ForeignKey("users.id"),nullable=False)
    recipient_id = db.Column(db.Integer,  db.ForeignKey("users.id"),nullable=False)
    text         = db.Column(db.Text,     nullable=False)
    is_read      = db.Column(db.Boolean,  default=False)
    is_deleted   = db.Column(db.Boolean,  default=False)
    deleted_by   = db.Column(db.Integer,  nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    sender    = db.relationship("User",foreign_keys=[sender_id])
    recipient = db.relationship("User",foreign_keys=[recipient_id])
    def to_dict(self):
        return {"id":self.id,"text":"[Message deleted]" if self.is_deleted else self.text,
                "is_read":self.is_read,"is_deleted":self.is_deleted,
                "created_at":self.created_at.isoformat(),"sender_id":self.sender_id,
                "recipient_id":self.recipient_id,
                "sender_name":self.sender.name if self.sender else ""}

class Notification(db.Model):
    __tablename__ = "notifications"
    id         = db.Column(db.Integer,     primary_key=True)
    user_id    = db.Column(db.Integer,     db.ForeignKey("users.id"),nullable=False)
    title      = db.Column(db.String(200), nullable=False)
    message    = db.Column(db.Text,        default="")
    type       = db.Column(db.String(20),  default="info")
    is_read    = db.Column(db.Boolean,     default=False)
    created_at = db.Column(db.DateTime,    default=datetime.datetime.utcnow)
    def to_dict(self):
        s=int((datetime.datetime.now(datetime.timezone.utc)-(self.created_at.replace(tzinfo=datetime.timezone.utc) if self.created_at.tzinfo is None else self.created_at)).total_seconds())
        ago=("Just now" if s<60 else f"{s//60} min ago" if s<3600 else
             f"{s//3600} hr ago" if s<86400 else f"{s//86400}d ago")
        return {"id":self.id,"title":self.title,"message":self.message,
                "type":self.type,"is_read":self.is_read,"time":ago}

class LoginLog(db.Model):
    __tablename__ = "login_logs"
    id         = db.Column(db.Integer,     primary_key=True)
    user_id    = db.Column(db.Integer,     db.ForeignKey("users.id"),nullable=True)
    contact    = db.Column(db.String(120), default="")
    success    = db.Column(db.Boolean,     default=True)
    ip_address = db.Column(db.String(45),  default="")
    created_at = db.Column(db.DateTime,    default=datetime.datetime.utcnow)


# ── HELPERS ───────────────────────────────────────────────────
def haversine(lat1,lon1,lat2,lon2):
    R=6371; dlat=math.radians(lat2-lat1); dlon=math.radians(lon2-lon1)
    a=math.sin(dlat/2)**2+math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R*2*math.asin(math.sqrt(a))

def _rel(dt):
    if not dt: return ""
    s=int((datetime.datetime.now(datetime.timezone.utc)-dt.replace(tzinfo=datetime.timezone.utc) if dt.tzinfo is None else dt).total_seconds())
    if s<60:    return "Just now"
    if s<3600:  return f"{s//60} min ago"
    if s<86400: return f"{s//3600} hr ago"
    return f"{s//86400} days ago"

def gen_token(user):
    p={"sub":str(user.id),"is_admin":bool(user.is_admin),"is_super_admin":bool(user.is_super_admin),
       "is_moderator":bool(user.is_moderator),
       "exp":datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=app.config["JWT_EXPIRY_HOURS"])}
    return jwt.encode(p,app.config["SECRET_KEY"],algorithm="HS256")

def decode_token(tok):
    try:    return jwt.decode(tok,app.config["SECRET_KEY"],algorithms=["HS256"])
    except jwt.ExpiredSignatureError: print("[JWT] Token expired"); return None
    except jwt.InvalidTokenError as e: print(f"[JWT] Invalid token: {e}"); return None
    except Exception as e: print(f"[JWT] Decode error: {e}"); return None

def get_current_user():
    auth=request.headers.get("Authorization","")
    if not auth.startswith("Bearer "): return None
    p=decode_token(auth.split(" ",1)[1])
    if not p: return None
    u=db.session.get(User,int(p["sub"]))  # sub is stored as str; cast back to int
    if not u: return None
    if u.email and u.email.lower()==SUPER_ADMIN_EMAIL and not u.is_super_admin:
        u.is_super_admin=True; u.is_admin=True; db.session.commit()
    return u

def require_auth(f):
    @wraps(f)
    def d(*a,**k):
        u=get_current_user()
        if not u:       return jsonify({"error":"Authentication required"}),401
        if u.is_banned: return jsonify({"error":"Account suspended."}),403
        g.current_user=u; return f(*a,**k)
    return d

def require_admin(f):
    @wraps(f)
    def d(*a,**k):
        u=get_current_user()
        if not u or not(u.is_admin or u.is_super_admin): return jsonify({"error":"Admin required"}),403
        g.current_user=u; return f(*a,**k)
    return d

def require_staff(f):
    @wraps(f)
    def d(*a,**k):
        u=get_current_user()
        if not u or not u.is_staff(): return jsonify({"error":"Staff required"}),403
        g.current_user=u; return f(*a,**k)
    return d


# ── EMAIL ─────────────────────────────────────────────────────
def _send_email(to_list,subject,html,plain=""):
    if not to_list: return
    if DEV_MODE:
        print(f"\n[DEV EMAIL] To:{to_list}\n  Subject:{subject}\n  {plain[:200]}\n"); return
    try:
        for addr in to_list:
            msg=MIMEMultipart("alternative"); msg["From"]=SMTP_SENDER; msg["To"]=addr; msg["Subject"]=subject
            msg.attach(MIMEText(plain,"plain")); msg.attach(MIMEText(html,"html"))
            s=smtplib.SMTP("smtp.gmail.com",587); s.starttls(); s.login(SMTP_SENDER,SMTP_PASSWORD)
            s.send_message(msg); s.quit()
    except Exception as e: print(f"[EMAIL ERR] {e}")

def _email_new_user(user_id):
    with app.app_context():
        user=db.session.get(User,user_id)
        if not user: return
        staff=User.query.filter((User.is_admin==True)|(User.is_moderator==True)).filter(User.email!=None).all()
        emails=[u.email for u in staff if u.email]
        if not emails: return
        html=f"""<div style="font-family:Arial;padding:20px;border:1px solid #c8e0ef;border-radius:10px">
<h2 style="color:#1d6698">New User</h2>
<p><b>Name:</b> {user.name}<br><b>Email:</b> {user.email or "-"}<br>
<b>Phone:</b> {user.phone or "-"}<br><b>City:</b> {user.city or "-"}</p></div>"""
        _send_email(emails,"NearNeed — New User",html,f"New user: {user.name} ({user.email or user.phone})")

def _email_emergency(req):
    all_u=User.query.filter(User.is_banned==False,User.email!=None).all()
    emails=[u.email for u in all_u if u.id!=req.user_id
            and haversine(req.lat or 0,req.lng or 0,u.lat or 0,u.lng or 0)<=5.0]
    if not emails: return
    poster=db.session.get(User,req.user_id); name=poster.name if poster else "A neighbor"
    html=f"""<div style="font-family:Arial;padding:20px;border:2px solid #d63131;border-radius:10px">
<h2 style="color:#d63131">Emergency Nearby!</h2>
<p><b>{req.title}</b><br>{req.description[:200]}</p>
<p>By {name} | {req.category} | {req.location or "Nearby"}</p>
<a href="{os.environ.get('APP_URL','http://localhost:8080')}/dashboard.html" style="background:#d63131;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none">Open NearNeed</a>
</div>"""
    _send_email(emails,"NearNeed — EMERGENCY Near You!",html,f"EMERGENCY: {req.title} by {name}")

PROFESSION_CATEGORY_MAP={
    "Medical":["Doctor","Nurse","Caregiver"],
    "Household":["Electrician","Plumber","Carpenter","Engineer"],
    "Transport":["Driver"],
    "Kids":["Teacher","Caregiver"],
    "Elderly Care":["Nurse","Caregiver","Doctor"],
}

def _notify_profession_match(req):
    professions=PROFESSION_CATEGORY_MAP.get(req.category or "Other",[])
    if not professions: return
    poster=db.session.get(User,req.user_id); pname=poster.name if poster else "A neighbor"
    nearby=[u for u in User.query.filter(User.is_banned==False,User.id!=req.user_id,
            User.profession.in_(professions)).all()
            if haversine(req.lat or 0,req.lng or 0,u.lat or 0,u.lng or 0)<=5.0]
    if not nearby: return
    for u in nearby:
        db.session.add(Notification(user_id=u.id,
            title="Task matching your skills nearby",
            message=f"{pname} needs {req.category} help: \"{req.title}\". Your profession ({u.profession}) is a great match!",
            type="info"))
    db.session.commit()
    for u in (x for x in nearby if x.email):
        html=f"""<div style="font-family:Arial;padding:20px;border:1.5px solid #c8e0ef;border-radius:10px">
<h2 style="color:#2772A0">Task Matching Your Skills</h2>
<p>Hi {u.name}, a neighbor needs {req.category} help and your profession ({u.profession}) is a great match.</p>
<p><b>{req.title}</b><br>{req.description[:200]}</p>
<p>Posted by {pname} | Urgency: {req.urgency}</p>
<a href="{os.environ.get('APP_URL','http://localhost:8080')}/dashboard.html" style="background:#2772A0;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none">View on NearNeed</a>
</div>"""
        _send_email([u.email],f"NearNeed — {req.category} task matching your skills",html,
                    f"Hi {u.name}, {req.category} task: {req.title}")

def send_otp_email(contact,otp,purpose):
    is_phone="@" not in contact
    if is_phone:
        print(f"[MOCK SMS] OTP {otp} -> {contact}"); return True,otp if DEV_MODE else None
    if DEV_MODE:
        print(f"\n{'='*50}\n  [DEV OTP] {contact}: {otp}  ({purpose})\n{'='*50}\n"); return True,otp
    html=f"<div style='padding:20px'><h2>NearNeed OTP</h2><div style='font-size:36px;font-weight:800;letter-spacing:10px;padding:16px;background:#eef7fc;border-radius:10px;text-align:center'>{otp}</div><p>Valid 10 minutes.</p></div>"
    _send_email([contact],f"NearNeed — {purpose} OTP",html,f"OTP: {otp}"); return True,None


# ── SSE ───────────────────────────────────────────────────────
def sse_push(room,event,data):
    msg=f"event: {event}\ndata: {_safe_dumps(data)}\n\n"
    with _sse_lock:
        for q in list(_sse_subs.get(room,[])):
            try: q.put_nowait(msg)
            except: pass

@app.route("/api/events/<room>")
def sse_stream(room):
    tok=request.args.get("token","")
    if not decode_token(tok): return jsonify({"error":"Unauthorized"}),401
    q=queue.Queue(maxsize=100)
    with _sse_lock: _sse_subs.setdefault(room,[]).append(q)
    def gen():
        try:
            yield f"event: connected\ndata: {_safe_dumps({'room':room})}\n\n"
            while True:
                try:    yield q.get(timeout=20)
                except queue.Empty: yield "event: ping\ndata: {}\n\n"
        finally:
            with _sse_lock:
                lst=_sse_subs.get(room,[])
                if q in lst: lst.remove(q)
    return Response(stream_with_context(gen()),mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


# ── AUTH ROUTES ───────────────────────────────────────────────
@app.route("/api/send-otp",methods=["POST"])
def send_otp():
    data=request.get_json() or {}; contact=(data.get("contact") or "").strip().lower(); purpose=data.get("purpose","register")
    if not contact: return jsonify({"error":"Contact required"}),400
    # Safe contact fingerprint for debugging (no PII)
    fp = hashlib.sha256(contact.encode("utf-8")).hexdigest()[:10]
    cutoff=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)-datetime.timedelta(minutes=app.config["OTP_EXPIRY_MINUTES"])
    recent_cnt = OTPRecord.query.filter_by(contact=contact,used=False).filter(OTPRecord.created_at>=cutoff).count()
    _dbg("H11","Backend/app.py:send_otp","OTP requested",{"purpose":purpose,"contact_fp":fp,"recent_unexpired_unused":int(recent_cnt)})
    if recent_cnt>=3:
        _dbg("H12","Backend/app.py:send_otp","OTP rate-limited",{"purpose":purpose,"contact_fp":fp,"recent_unexpired_unused":int(recent_cnt)})
        return jsonify({"error":"Too many requests. Wait 10 minutes."}),429
    otp="".join(random.choices(string.digits,k=6))
    db.session.add(OTPRecord(contact=contact,otp=otp,purpose=purpose)); db.session.commit()
    ok,dev=send_otp_email(contact,otp,purpose)
    _dbg("H13","Backend/app.py:send_otp","OTP send attempted",{"purpose":purpose,"contact_fp":fp,"ok":bool(ok),"dev_returned":bool(dev)})
    r={"message":f"OTP sent to {contact}","success":True}
    if dev: r["dev_otp"]=dev
    return jsonify(r)

@app.route("/api/verify-otp",methods=["POST"])
def verify_otp_route():
    data=request.get_json() or {}; contact=(data.get("contact") or "").strip().lower()
    otp=(data.get("otp") or "").strip(); purpose=data.get("purpose","register")
    cutoff=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)-datetime.timedelta(minutes=app.config["OTP_EXPIRY_MINUTES"])
    rec=OTPRecord.query.filter_by(contact=contact,otp=otp,purpose=purpose,used=False).filter(OTPRecord.created_at>=cutoff).order_by(OTPRecord.created_at.desc()).first()
    if not rec: return jsonify({"error":"Invalid or expired OTP","success":False}),400
    rec.used=True; db.session.commit()
    if purpose=="login":
        u=User.query.filter((User.email==contact)|(User.phone==contact)).first()
        if u: return jsonify({"success":True,"token":gen_token(u),"user":{**u.to_dict(include_private=True),"token":gen_token(u)}})
    return jsonify({"success":True,"message":"OTP verified"})

@app.route("/api/aadhaar/send-otp",methods=["POST"])
def aadhaar_send_otp():
    data=request.get_json() or {}; contact=(data.get("contact") or "").strip().lower()
    aadhaar=(data.get("aadhaar") or "").strip().replace(" ","").replace("-","")
    if not contact: return jsonify({"error":"Contact required"}),400
    if not aadhaar or not aadhaar.isdigit() or len(aadhaar)!=12: return jsonify({"error":"Valid 12-digit Aadhaar required"}),400
    otp="".join(random.choices(string.digits,k=6))
    db.session.add(OTPRecord(contact=contact,otp=otp,purpose="aadhaar")); db.session.commit()
    _,dev=send_otp_email(contact,otp,"Aadhaar Verification")
    r={"message":f"Aadhaar OTP sent to {contact}","success":True}
    if dev: r["dev_otp"]=dev
    return jsonify(r)

@app.route("/api/aadhaar/verify-otp",methods=["POST"])
def aadhaar_verify_otp():
    data=request.get_json() or {}; contact=(data.get("contact") or "").strip().lower(); otp=(data.get("otp") or "").strip()
    cutoff=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)-datetime.timedelta(minutes=10)
    rec=OTPRecord.query.filter_by(contact=contact,otp=otp,purpose="aadhaar",used=False).filter(OTPRecord.created_at>=cutoff).order_by(OTPRecord.created_at.desc()).first()
    if not rec: return jsonify({"error":"Invalid or expired OTP","success":False}),400
    rec.used=True; db.session.commit()
    return jsonify({"success":True,"message":"Aadhaar verified"})

@app.route("/api/register",methods=["POST"])
def register():
    data=request.get_json() or {}; name=(data.get("name") or "").strip()
    contact=(data.get("contact") or "").strip().lower(); password=data.get("password","")
    c_type=data.get("contactType","email"); aadhaar=(data.get("aadhaar") or "").strip().replace(" ","").replace("-","")
    _dbg("H6","Backend/app.py:register","Register attempt",{"has_name":bool(name),"contactType":c_type})
    if not name or not contact: return jsonify({"error":"Name and contact required"}),400
    if len(password)<8: return jsonify({"error":"Password must be at least 8 characters"}),400
    if aadhaar and(not aadhaar.isdigit() or len(aadhaar)!=12): return jsonify({"error":"Aadhaar must be 12 digits"}),400
    if c_type=="email" and User.query.filter_by(email=contact).first(): return jsonify({"error":"Email already registered"}),409
    if c_type=="phone" and User.query.filter_by(phone=contact).first(): return jsonify({"error":"Phone already registered"}),409
    is_sa=(c_type=="email" and contact==SUPER_ADMIN_EMAIL)
    u=User(name=name,email=contact if c_type=="email" else(data.get("email") or "").lower() or None,
           phone=contact if c_type=="phone" else data.get("phone") or None,
           password_hash=generate_password_hash(password),
           city=data.get("city",""),state=data.get("state",""),pincode=data.get("pincode",""),
           street=data.get("street",""),bio=data.get("bio",""),gender=data.get("gender",""),
           age_group=data.get("age_group",""),profession=data.get("profession",""),
           lat=float(data.get("lat") or 0),lng=float(data.get("lng") or 0),
           is_verified=True,is_super_admin=is_sa,is_admin=is_sa,
           aadhaar_verified=bool(aadhaar and data.get("aadhaar_otp_verified")),
           aadhaar_last4=aadhaar[-4:] if aadhaar else "")
    db.session.add(u); db.session.commit()
    threading.Thread(target=_email_new_user,args=(u.id,),daemon=True).start()
    db.session.add(Notification(user_id=u.id,title=f"Welcome to NearNeed, {u.name}!",
                                message="Your account is ready. Explore your neighborhood.",type="success"))
    db.session.commit(); sse_push("admin","new_user",u.to_dict(include_private=True))
    token=gen_token(u)
    return jsonify({"message":"Registration successful","token":token,"user":{**u.to_dict(include_private=True),"token":token}}),201

@app.route("/api/login",methods=["POST"])
def login():
    data=request.get_json() or {}; contact=(data.get("contact") or "").strip().lower()
    password=data.get("password",""); ip=request.remote_addr
    _dbg("H5","Backend/app.py:login","Login attempt",{"has_contact":bool(contact),"ip":ip})
    u=User.query.filter((User.email==contact)|(User.phone==contact)).first()
    if not u or not check_password_hash(u.password_hash,password):
        db.session.add(LoginLog(contact=contact,success=False,ip_address=ip)); db.session.commit()
        return jsonify({"error":"Invalid credentials"}),401
    if u.is_banned: return jsonify({"error":"Account suspended."}),403
    if u.email and u.email.lower()==SUPER_ADMIN_EMAIL and not u.is_super_admin:
        u.is_super_admin=True; u.is_admin=True
    db.session.add(LoginLog(user_id=u.id,contact=contact,success=True,ip_address=ip)); db.session.commit()
    token=gen_token(u)
    return jsonify({"message":"Login successful","token":token,"user":{**u.to_dict(include_private=True),"token":token}})

@app.route("/api/forgot-password",methods=["POST"])
def forgot_password():
    data=request.get_json() or {}; contact=(data.get("contact") or "").strip().lower()
    if not contact: return jsonify({"error":"Contact required"}),400
    u=User.query.filter((User.email==contact)|(User.phone==contact)).first()
    if not u: return jsonify({"message":"If that account exists, an OTP has been sent","success":True})
    otp="".join(random.choices(string.digits,k=6))
    db.session.add(OTPRecord(contact=contact,otp=otp,purpose="reset")); db.session.commit()
    _,dev=send_otp_email(contact,otp,"reset")
    r={"message":"Reset OTP sent","success":True}
    if dev: r["dev_otp"]=dev
    return jsonify(r)

@app.route("/api/reset-password",methods=["POST"])
def reset_password():
    data=request.get_json() or {}; contact=(data.get("contact") or "").strip().lower()
    otp=(data.get("otp") or "").strip(); new_password=(data.get("new_password") or "")
    if not contact or not otp or not new_password: return jsonify({"error":"contact, otp and new_password required"}),400
    if len(new_password)<8: return jsonify({"error":"Password must be at least 8 characters"}),400
    cutoff=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)-datetime.timedelta(minutes=app.config["OTP_EXPIRY_MINUTES"])
    rec=OTPRecord.query.filter_by(contact=contact,otp=otp,purpose="reset",used=False).filter(OTPRecord.created_at>=cutoff).order_by(OTPRecord.created_at.desc()).first()
    if not rec: return jsonify({"error":"Invalid or expired OTP. Please request a new one."}),400
    u=User.query.filter((User.email==contact)|(User.phone==contact)).first()
    if not u: return jsonify({"error":"Account not found"}),404
    u.password_hash=generate_password_hash(new_password); rec.used=True; db.session.commit()
    return jsonify({"success":True,"message":"Password reset successfully"})

@app.route("/api/check-contact",methods=["POST"])
def check_contact():
    data=request.get_json() or {}; contact=(data.get("contact") or "").strip().lower()
    contact_type=data.get("contactType","email")
    if not contact: return jsonify({"error":"Contact required"}),400
    exists=(User.query.filter_by(email=contact).first() if contact_type=="email"
            else User.query.filter_by(phone=contact).first()) is not None
    return jsonify({"available":not exists,
                    "error":(f"{'Email' if contact_type=='email' else 'Phone'} already registered" if exists else None)})


# ── REQUESTS ──────────────────────────────────────────────────
@app.route("/api/requests",methods=["GET"])
def list_requests():
    # Optionally use the authenticated user's location if a token is provided;
    # but authentication is NOT required — the feed is public so all users
    # (including those with expired tokens) always see requests.
    u = get_current_user()  # returns None if no/invalid token — that's OK

    _dbg("H7","Backend/app.py:list_requests","List requests",{"user_id": u.id if u else None})

    def safe_float(val, default):
        try:
            return float(val) if val and str(val).lower() != "undefined" else default
        except (ValueError, TypeError):
            return default

    default_lat = (u.lat if u and u.lat else None) or 19.076
    default_lng = (u.lng if u and u.lng else None) or 72.877
    lat=safe_float(request.args.get("lat"), default_lat)
    lng=safe_float(request.args.get("lng"), default_lng)
    cat=request.args.get("category")
    radius=safe_float(request.args.get("radius"), app.config["RADIUS_KM"])
    reqs=HelpRequest.query.filter_by(status="open",is_deleted=False).order_by(HelpRequest.created_at.desc()).all()
    # Include requests at 0,0 (no GPS set) so they always show up
    result=[]
    for r in reqs:
        rlat=float(r.lat or 0); rlng=float(r.lng or 0)
        if (rlat==0.0 and rlng==0.0) or haversine(lat,lng,rlat,rlng)<=radius:
            result.append(r.to_dict(viewer_lat=lat,viewer_lng=lng))
    if cat: result=[r for r in result if r["category"]==cat]
    result.sort(key=lambda x:(x.get("urgency")!="Emergency",x.get("distance_km",999)))
    return jsonify({"requests":result,"count":len(result)})

@app.route("/api/requests",methods=["POST"])
@require_auth
def create_request():
    data=request.get_json() or {}; u=g.current_user
    title=(data.get("title") or "").strip(); desc=(data.get("description") or "").strip()
    if not title or not desc: return jsonify({"error":"Title and description required"}),400
    _dbg("H8","Backend/app.py:create_request","Create request payload",{"user_id":u.id,"has_title":bool(title),"category":data.get("category","General"),"urgency":data.get("urgency","Low")})
    req=HelpRequest(user_id=u.id,title=title,description=desc,
                    category=data.get("category","General"),urgency=data.get("urgency","Low"),
                    location=data.get("location",""),
                    lat=float(data.get("lat") or u.lat or 0),lng=float(data.get("lng") or u.lng or 0))
    db.session.add(req); u.req_count=(u.req_count or 0)+1; db.session.commit()
    # Refresh so all relationships (user, helper) are loaded before to_dict()
    db.session.refresh(req)
    _dbg("H9","Backend/app.py:create_request","Request committed",{"user_id":u.id,"request_id":req.id})
    rd=req.to_dict(); sse_push("requests","new_request",rd)
    if req.urgency=="Emergency":
        threading.Thread(target=_t_emergency,args=(req.id,),daemon=True).start()
    threading.Thread(target=_t_profession,args=(req.id,),daemon=True).start()
    return jsonify({"message":"Request created","request":rd}),201

def _t_emergency(req_id):
    with app.app_context():
        req=db.session.get(HelpRequest,req_id); poster=db.session.get(User,req.user_id)
        pname=poster.name if poster else "A neighbor"; _email_emergency(req)
        for u in User.query.filter_by(is_banned=False).all():
            if u.id==req.user_id: continue
            if haversine(req.lat or 0,req.lng or 0,u.lat or 0,u.lng or 0)<=5.0:
                n=Notification(user_id=u.id,title="Emergency Nearby!",message=f"{pname}: {req.title[:80]}",type="emergency")
                db.session.add(n); sse_push(f"user_{u.id}","notification",{"title":n.title,"message":n.message,"type":"emergency"})
        db.session.commit()

def _t_profession(req_id):
    with app.app_context():
        req=db.session.get(HelpRequest,req_id)
        if req: _notify_profession_match(req)

@app.route("/api/requests/<int:req_id>/accept",methods=["POST"])
@require_auth
def accept_request(req_id):
    u=g.current_user; req=db.get_or_404(HelpRequest,req_id)
    if req.user_id==u.id: return jsonify({"error":"Cannot help your own request"}),400
    if req.status!="open": return jsonify({"error":"Request already taken"}),400
    req.helper_id=u.id; req.status="in_progress"; u.helped_count=(u.helped_count or 0)+1; db.session.commit()
    rd=req.to_dict(); sse_push("requests","update_request",rd)
    db.session.add(Notification(user_id=req.user_id,title="Someone offered to help!",
                                message=f"{u.name} accepted your request: {req.title[:60]}",type="info"))
    db.session.commit(); return jsonify({"message":"Accepted","request":rd})

@app.route("/api/requests/<int:req_id>/complete",methods=["POST"])
@require_auth
def complete_request(req_id):
    u=g.current_user; req=db.get_or_404(HelpRequest,req_id)
    if req.user_id!=u.id and req.helper_id!=u.id: return jsonify({"error":"Not authorized"}),403
    req.status="resolved"; req.updated_at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None); db.session.commit()
    sse_push("requests","update_request",req.to_dict()); return jsonify({"message":"Marked complete"})

@app.route("/api/requests/<int:req_id>",methods=["DELETE"])
@require_auth
def delete_request(req_id):
    u=g.current_user; req=db.get_or_404(HelpRequest,req_id)
    if req.user_id!=u.id and not u.is_staff(): return jsonify({"error":"Not authorized"}),403
    req.is_deleted=True; req.deleted_by=u.id; db.session.commit()
    sse_push("requests","delete_request",{"id":req_id}); return jsonify({"message":"Deleted"})

@app.route("/api/my-requests",methods=["GET"])
@require_auth
def my_requests():
    u=g.current_user
    return jsonify({"posted":[r.to_dict() for r in HelpRequest.query.filter_by(user_id=u.id,is_deleted=False).all()],
                    "helping":[r.to_dict() for r in HelpRequest.query.filter_by(helper_id=u.id,is_deleted=False).all()]})

@app.route("/api/nearby-requests",methods=["POST"])
@require_auth
def nearby_requests():
    data=request.get_json() or {}; u=g.current_user
    lat=float(data.get("lat") or u.lat or 19.076)
    lng=float(data.get("lng") or u.lng or 72.877)
    radius=float(data.get("radius_km") or app.config["RADIUS_KM"])
    reqs=HelpRequest.query.filter_by(status="open",is_deleted=False).order_by(HelpRequest.created_at.desc()).all()
    result=[]
    for r in reqs:
        rlat=float(r.lat or 0); rlng=float(r.lng or 0)
        if (rlat==0.0 and rlng==0.0) or haversine(lat,lng,rlat,rlng)<=radius:
            result.append(r.to_dict(viewer_lat=lat,viewer_lng=lng))
    result.sort(key=lambda x:(x.get("urgency")!="Emergency",x.get("distance_km",999)))
    return jsonify({"requests":result,"count":len(result)})


# ── NOTICES ───────────────────────────────────────────────────
@app.route("/api/notices",methods=["GET"])
def list_notices():
    # Public endpoint — no auth required to read community notices
    cat=request.args.get("category")
    notices=Notice.query.filter_by(is_deleted=False).order_by(Notice.created_at.desc()).all()
    result=[n.to_dict() for n in notices]
    if cat: result=[n for n in result if n["category"]==cat]
    return jsonify({"notices":result,"count":len(result)})

@app.route("/api/notices",methods=["POST"])
@require_auth
def create_notice():
    data=request.get_json() or {}; u=g.current_user
    title=(data.get("title") or "").strip(); body=(data.get("body") or "").strip()
    if not title or not body: return jsonify({"error":"Title and body required"}),400
    n=Notice(user_id=u.id,title=title,body=body,category=data.get("category","General"),
             lat=float(data.get("lat") or u.lat or 0),lng=float(data.get("lng") or u.lng or 0))
    db.session.add(n); db.session.commit()
    nd=n.to_dict()
    sse_push("notices","new_notice",nd)   # broadcast to all connected dashboards
    return jsonify({"message":"Notice created","notice":nd}),201

@app.route("/api/notices/<int:nid>",methods=["DELETE"])
@require_auth
def delete_notice(nid):
    u=g.current_user; n=db.get_or_404(Notice,nid)
    if n.user_id!=u.id and not u.is_staff(): return jsonify({"error":"Not authorized"}),403
    n.is_deleted=True; db.session.commit(); return jsonify({"message":"Deleted"})


# ── MESSAGES ──────────────────────────────────────────────────
@app.route("/api/messages/<int:peer_id>",methods=["GET"])
@require_auth
def get_messages(peer_id):
    me=g.current_user
    msgs=Message.query.filter(
        ((Message.sender_id==me.id)&(Message.recipient_id==peer_id))|
        ((Message.sender_id==peer_id)&(Message.recipient_id==me.id))
    ).order_by(Message.created_at.asc()).limit(200).all()
    return jsonify({"messages":[m.to_dict() for m in msgs]})

@app.route("/api/messages/<int:peer_id>",methods=["POST"])
@require_auth
def send_message(peer_id):
    me=g.current_user; data=request.get_json() or {}; text=(data.get("text") or "").strip()
    if not text: return jsonify({"error":"Empty message"}),400
    if not db.session.get(User,peer_id): return jsonify({"error":"Recipient not found"}),404
    msg=Message(sender_id=me.id,recipient_id=peer_id,text=text)
    db.session.add(msg); db.session.commit()
    md=msg.to_dict(); room=f"chat_{min(me.id,peer_id)}_{max(me.id,peer_id)}"
    sse_push(room,"new_message",md)
    sse_push(f"user_{peer_id}","new_message_notif",{"from":me.name,"preview":text[:60],"sender_id":me.id})
    return jsonify({"message":md}),201

@app.route("/api/messages/delete/<int:msg_id>",methods=["DELETE"])
@require_auth
def delete_message(msg_id):
    u=g.current_user; msg=db.get_or_404(Message,msg_id)
    if msg.sender_id!=u.id and not u.is_staff(): return jsonify({"error":"Not authorized"}),403
    msg.is_deleted=True; msg.deleted_by=u.id; db.session.commit()
    room=f"chat_{min(msg.sender_id,msg.recipient_id)}_{max(msg.sender_id,msg.recipient_id)}"
    sse_push(room,"delete_message",{"id":msg_id}); return jsonify({"message":"Deleted"})

@app.route("/api/contacts",methods=["GET"])
@require_auth
def get_contacts():
    me=g.current_user
    sent={m.recipient_id for m in Message.query.filter_by(sender_id=me.id).all()}
    recv={m.sender_id for m in Message.query.filter_by(recipient_id=me.id).all()}
    ids=(sent|recv)-{me.id}
    contacts=[db.session.get(User,uid).to_dict() for uid in ids
              if db.session.get(User,uid) and not db.session.get(User,uid).is_banned]
    return jsonify({"contacts":contacts})


# ── NOTIFICATIONS ─────────────────────────────────────────────
@app.route("/api/notifications",methods=["GET"])
@require_auth
def get_notifications():
    u=g.current_user
    notifs=Notification.query.filter_by(user_id=u.id).order_by(Notification.created_at.desc()).limit(50).all()
    unread=sum(1 for n in notifs if not n.is_read)
    return jsonify({"notifications":[n.to_dict() for n in notifs],"unread":unread})

@app.route("/api/notifications/read-all",methods=["POST"])
@require_auth
def mark_all_read():
    Notification.query.filter_by(user_id=g.current_user.id,is_read=False).update({"is_read":True})
    db.session.commit(); return jsonify({"message":"All read"})


# ── PROFILE ───────────────────────────────────────────────────
@app.route("/api/profile",methods=["GET"])
@require_auth
def get_profile():
    return jsonify({"user":g.current_user.to_dict(include_private=True)})

@app.route("/api/profile",methods=["PUT"])
@require_auth
def update_profile():
    u=g.current_user; data=request.get_json() or {}
    for f in("name","bio","city","state","pincode","profession"):
        v=data.get(f)
        if v is not None: setattr(u,f,str(v).strip())
    db.session.commit(); return jsonify({"message":"Updated","user":u.to_dict(include_private=True)})


# ── ADMIN ─────────────────────────────────────────────────────
@app.route("/api/admin/stats",methods=["GET"])
@require_staff
def admin_stats():
    return jsonify({"users":User.query.count(),"requests":HelpRequest.query.filter_by(is_deleted=False).count(),
                    "open_reqs":HelpRequest.query.filter_by(status="open",is_deleted=False).count(),
                    "notices":Notice.query.filter_by(is_deleted=False).count(),
                    "banned":User.query.filter_by(is_banned=True).count(),
                    "moderators":User.query.filter_by(is_moderator=True).count(),
                    "aadhaar_verified":User.query.filter_by(aadhaar_verified=True).count(),
                    "messages":Message.query.filter_by(is_deleted=False).count()})

@app.route("/api/admin/users",methods=["GET"])
@require_staff
def admin_list_users():
    users=User.query.order_by(User.created_at.desc()).all()
    logs=LoginLog.query.order_by(LoginLog.created_at.desc()).limit(60).all()
    log_data=[{"dot":"ok" if l.success else "fail","text":f"{'Login' if l.success else 'Failed'} - {l.contact}",
               "time":_rel(l.created_at),"ip":l.ip_address} for l in logs]
    counts={"total":len(users),"admins":sum(1 for u in users if u.is_admin and not u.is_super_admin),
            "moderators":sum(1 for u in users if u.is_moderator),"banned":sum(1 for u in users if u.is_banned),
            "aadhaar":sum(1 for u in users if u.aadhaar_verified)}
    return jsonify({"users":[u.to_dict(include_private=True) for u in users],"login_logs":log_data,"counts":counts})

@app.route("/api/admin/ban/<int:tid>",methods=["POST"])
@require_staff
def ban_user(tid):
    actor=g.current_user; target=db.get_or_404(User,tid)
    if target.is_super_admin: return jsonify({"error":"Cannot ban the Super Admin"}),403
    if target.is_admin and not actor.is_super_admin: return jsonify({"error":"Only Super Admin can ban admins"}),403
    data=request.get_json() or {}; target.is_banned=data.get("banned",True); db.session.commit()
    action="banned" if target.is_banned else "unbanned"
    sse_push("admin","user_banned",{"id":target.id,"banned":target.is_banned,"name":target.name})
    return jsonify({"message":f"User {action}","user":target.to_dict()})

@app.route("/api/admin/delete-user/<int:tid>",methods=["DELETE"])
@require_admin
def delete_user(tid):
    actor=g.current_user; target=db.get_or_404(User,tid)
    if target.is_super_admin: return jsonify({"error":"Cannot delete Super Admin"}),403
    if target.is_admin and not actor.is_super_admin: return jsonify({"error":"Only Super Admin can delete admins"}),403
    target.is_banned=True; target.name=f"[Deleted #{target.id}]"
    target.email=f"deleted_{target.id}@removed"; target.phone=None
    db.session.commit(); return jsonify({"message":"User deleted"})

@app.route("/api/admin/moderators",methods=["GET"])
@require_admin
def list_moderators():
    return jsonify({"moderators":[u.to_dict(include_private=True) for u in User.query.filter_by(is_moderator=True).all()]})

@app.route("/api/admin/moderators/<int:tid>",methods=["POST"])
def set_moderator(tid):
    actor=get_current_user()
    if not actor or not actor.is_super_admin: return jsonify({"error":"Only Super Admin can manage moderators"}),403
    target=db.get_or_404(User,tid)
    if target.is_super_admin: return jsonify({"error":"Cannot change Super Admin role"}),403
    data=request.get_json() or {}; target.is_moderator=bool(data.get("is_moderator",True)); db.session.commit()
    verb="promoted to moderator" if target.is_moderator else "removed as moderator"
    sse_push("admin","moderator_changed",{"id":target.id,"is_moderator":target.is_moderator})
    return jsonify({"message":f"{target.name} {verb}","user":target.to_dict()})

@app.route("/api/admin/messages",methods=["GET"])
@require_staff
def admin_list_messages():
    msgs=Message.query.filter_by(is_deleted=False).order_by(Message.created_at.desc()).limit(200).all()
    return jsonify({"messages":[m.to_dict() for m in msgs]})

@app.route("/api/admin/requests",methods=["GET"])
@require_staff
def admin_list_requests():
    reqs=HelpRequest.query.filter_by(is_deleted=False).order_by(HelpRequest.created_at.desc()).limit(100).all()
    return jsonify({"requests":[r.to_dict() for r in reqs]})


# ── STARTUP ───────────────────────────────────────────────────
def _check_db():
    try:
        with db.engine.connect() as conn: conn.execute(db.text("SELECT 1"))
        print("  MySQL connection OK")
    except Exception as e:
        print("\n"+"="*58)
        print("  Cannot connect to MySQL!")
        print(f"  {e}")
        print()
        print("  Checklist:")
        print("    1. Is MySQL running?")
        print("    2. Are credentials correct in .env?")
        print("    3. Did you run:  mysql -u root -p < nearneed.sql")
        print("="*58+"\n")
        sys.exit(1)

if __name__=="__main__":
    with app.app_context(): _check_db()
    if DEV_MODE: print("\n  DEV MODE - OTPs printed to console, emails skipped")
    print("\n"+"="*55+"\n  NearNeed v4.1  (MySQL)"+"\n  http://127.0.0.1:5000/"+
          f"\n  Super Admin: {SUPER_ADMIN_EMAIL}"+"\n"+"="*55+"\n")
    app.run(debug=False,host='0.0.0.0',port=5000,threaded=True)
