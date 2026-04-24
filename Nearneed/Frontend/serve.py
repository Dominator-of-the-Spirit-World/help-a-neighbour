import http.server
import socketserver
import webbrowser
import threading
import os

PORT = int(os.environ.get("NEARNEED_PORT", "8080"))
HOST = "127.0.0.1"   # Force IPv4 — gives a clean localhost link

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # Cleaner request log
        # Avoid Unicode arrows (Windows cp1252 consoles can crash).
        try:
            print(f"  > {args[0]}  {args[1]}", flush=True)
        except Exception:
            pass

def open_browser():
    webbrowser.open(f"http://localhost:{PORT}")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # serve from script's folder

    # If the default port is taken (common on Windows), try the next few ports.
    # This avoids a hard crash and keeps the dev setup smooth.
    httpd = None
    for p in range(PORT, PORT + 20):
        try:
            httpd = socketserver.TCPServer((HOST, p), Handler)
            PORT = p
            break
        except OSError:
            continue
    if httpd is None:
        raise OSError(f"Could not bind to ports {PORT}-{PORT+19}. Close the app using the port or set NEARNEED_PORT.")

    with httpd:
        url = f"http://localhost:{PORT}"
        # Avoid Unicode box-drawing chars (Windows cp1252 consoles can crash).
        print("", flush=True)
        print("+------------------------------------------+", flush=True)
        print("|        NearNeed  -  Frontend Server      |", flush=True)
        print("+------------------------------------------+", flush=True)
        print((f"|  URL: {url}").ljust(43) + "|", flush=True)
        print("|                                          |", flush=True)
        print("|  Make sure your Flask backend is also    |", flush=True)
        print("|  running:  python app.py  (port 5000)    |", flush=True)
        print("+------------------------------------------+", flush=True)
        print("", flush=True)
        print("Request log:", flush=True)

        # Auto-open browser after a short delay
        threading.Timer(0.8, open_browser).start()

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n  Server stopped.")
