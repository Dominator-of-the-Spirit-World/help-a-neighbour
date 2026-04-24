
function _resolveApiHost() {
  // Allow overriding API host without rebuilding:
  // - window.NEARNEED_API_HOST = "http://127.0.0.1:5000"
  // - localStorage.NEARNEED_API_HOST = "http://127.0.0.1:5000"
  // - <meta name="nearneed-api-host" content="http://127.0.0.1:5000">
  try {
    if (window.NEARNEED_API_HOST) return String(window.NEARNEED_API_HOST).replace(/\/+$/, '');
  } catch {}

  try {
    const ls = localStorage.getItem('NEARNEED_API_HOST');
    if (ls) return String(ls).replace(/\/+$/, '');
  } catch {}

  try {
    const meta = document.querySelector('meta[name="nearneed-api-host"]');
    const v = meta && meta.getAttribute('content');
    if (v) return String(v).replace(/\/+$/, '');
  } catch {}

  const proto = window.location.protocol;
  // If opened directly as a file, window.location.hostname is empty and fetch targets break.
  // Force a sensible localhost default.
  if (proto !== 'http:' && proto !== 'https:') return 'http://127.0.0.1:5000';

  // If the frontend is being served from the Flask app itself (same origin),
  // avoid hardcoding port 5000.
  if (String(window.location.port) === '5000') return window.location.origin;

  const host = window.location.hostname || '127.0.0.1';
  return `${proto}//${host}:5000`;
}

const _apiHost = _resolveApiHost();
const API = _apiHost + '/api';
const API_BASE = API;

// ─── Auth ──────────────────────────────────────────────
const Auth = {
  save(user) {
    sessionStorage.setItem('nn_user', JSON.stringify(user));
  },

  get() {
    try { return JSON.parse(sessionStorage.getItem('nn_user') || 'null'); }
    catch { return null; }
  },

  getUser()  { return this.get(); },
  
  getToken() { 
    const u = this.get(); 
    if (!u) return null;
    // Handle both {token: '...'} and {user: {token: '...'}}
    return u.token || (u.user && u.user.token) || null; 
  },

  clear() { sessionStorage.removeItem('nn_user'); },

  required() {
    if (!this.get()) { window.location.href = 'login.html'; return false; }
    return true;
  },

  redirect() { if (this.get()) window.location.href = 'dashboard.html'; },

  isLoggedIn() { return !!this.get(); },

  isAdmin() {
    const u = this.get();
    return u && (u.is_admin === true || u.is_super_admin === true);
  },

  isStaff() {
    const u = this.get();
    return u && (u.is_admin || u.is_super_admin || u.is_moderator);
  }
};

// ─── Core API call ──
async function apiCall(endpoint, data, method = 'POST') {
  try {
    // Ensure endpoint starts with /api/ if it doesn't already
    const path = endpoint.startsWith('/api') ? endpoint : '/api' + endpoint;
    
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    const token = Auth.getToken();
    if (token) opts.headers['Authorization'] = 'Bearer ' + token;
    
    if (data && method !== 'GET') opts.body = JSON.stringify(data);

    const res = await fetch(_apiHost + path, opts);

    const contentType = res.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
      // This usually means the request hit the wrong server (e.g. the static frontend server),
      // or a proxy is returning an HTML error page. Don't treat as "offline" demo mode.
      let snippet = '';
      try { snippet = (await res.text()).slice(0, 200); } catch {}
      console.warn('[NearNeed] Expected JSON but got:', contentType, 'for', path, 'snippet:', snippet);
      return {
        error: 'API returned HTML/non-JSON. Backend URL/proxy is misconfigured or backend is not running.',
        offline: false,
        nonJson: true,
        status: res.status,
        apiHost: _apiHost
      };
    }

    const json = await res.json();
    if (!res.ok) return { error: json.error || 'Request failed', status: res.status };
    return json;
  } catch (e) {
    console.warn('[NearNeed] Backend unavailable:', e.message);
    return { error: 'offline', offline: true };
  }
}

async function apiGet(endpoint) {
  return apiCall(endpoint, null, 'GET');
}

// ─── Demo Users (for offline fallback) ────────────────
const DEMO_USERS = [
  { id:1, name:'Rahul Sharma',  email:'rahul@demo.com',  phone:'9876543210',
    password:'Test@1234', city:'Mumbai', pincode:'400001',
    lat:19.0760, lng:72.8777, is_admin:true,  rating:4.8, helped:12, requested:5 },
];

function showToast(msg, type = 'info') {
  const map = { s:'success', e:'error', i:'info', success:'success', error:'error', info:'info', warn:'warn' };
  type = map[type] || 'info';

  let container = document.getElementById('toastRoot')
               || document.getElementById('nnToastRoot')
               || document.getElementById('toasts');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastRoot';
    container.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none;';
    document.body.appendChild(container);
  }

  const colors = { success:'#1a9e5c', error:'#d63131', info:'#2772A0', warn:'#d97706' };
  const icons  = {
    success:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="17" height="17"><polyline points="20 6 9 17 4 12"/></svg>`,
    error:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"   width="17" height="17"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
    info:   `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"   width="17" height="17"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
    warn:   `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"   width="17" height="17"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
  };

  if (!document.querySelector('#tsStyle')) {
    const s = document.createElement('style'); s.id = 'tsStyle';
    s.textContent = '@keyframes tsIn{from{opacity:0;transform:translateX(14px)}to{opacity:1;transform:translateX(0)}}';
    document.head.appendChild(s);
  }

  const el = document.createElement('div');
  el.style.cssText = `display:flex;align-items:center;gap:10px;padding:12px 16px;background:white;
    border:1.5px solid #c8e0ef;border-left:3px solid ${colors[type]};border-radius:10px;
    font-family:'DM Sans',sans-serif;font-size:13px;color:#1b2e3c;
    box-shadow:0 6px 24px rgba(0,0,0,0.12);min-width:220px;max-width:340px;
    animation:tsIn .28s ease;pointer-events:auto;`;
  el.innerHTML = `<span style="color:${colors[type]};flex-shrink:0">${icons[type]}</span><span>${msg}</span>`;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity='0'; el.style.transform='translateX(14px)'; el.style.transition='all .3s'; }, 3500);
  setTimeout(() => el.remove(), 3800);
}

async function loginUser(contact, password) {
  const res = await apiCall('/login', { contact, password });
  if (res && !res.error && res.user) {
    // Ensure token is saved correctly
    const userData = res.user;
    if (!userData.token && res.token) userData.token = res.token;
    Auth.save(userData);
    showToast('Welcome back, ' + userData.name + '! 🎉', 'success');
    setTimeout(() => window.location.href = 'dashboard.html', 800);
    return;
  }
  if (!res.offline) {
    showToast(res.error || 'Invalid email or password', 'error');
    return;
  }
  showToast('Backend is offline. Please start Flask.', 'error');
}

async function registerUser(formDataObj) {
  const res = await apiCall('/register', formDataObj);
  if (res.error) { showToast(res.error, 'error'); return; }
  showToast('Registration successful', 'success');
  setTimeout(() => window.location.href = 'login.html', 1000);
}

function logout() {
  Auth.clear();
  window.location.href = 'login.html';
}
