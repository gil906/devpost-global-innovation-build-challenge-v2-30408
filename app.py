"""CommonTable HTTP application; Python 3.11+, no runtime packages or remote APIs."""

import argparse
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from planner import ValidationError, csv_export, plan, validate
from store import Store, StoreFull

ROOT = Path(__file__).resolve().parent
MAX_BODY = 128 * 1024
STATIC = {
    "/": ("web/index.html", "text/html; charset=utf-8"),
    "/app.js": ("web/app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("web/style.css", "text/css; charset=utf-8"),
    "/icon.svg": ("web/icon.svg", "image/svg+xml"),
}


class RequestError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, data_directory):
        self.store = Store(data_directory)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "CommonTable/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)
        self.new_cookie = None

    def log_message(self, fmt, *args):
        # Paths and names are user input; don't put them in server logs.
        logging.info("HTTP response completed")

    def send(self, status, body, content_type="application/json; charset=utf-8", download=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, allow_nan=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' blob:; connect-src 'self'; object-src 'none'; "
                         "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if self.new_cookie:
            self.send_header("Set-Cookie", f"ct_session={self.new_cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age=604800")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(body)

    def owner(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            cookie = SimpleCookie()
        token = cookie["ct_session"].value if "ct_session" in cookie else ""
        if not re.fullmatch(r"[a-f0-9]{64}", token):
            token = secrets.token_hex(32)
            self.new_cookie = token
        return hashlib.sha256(token.encode()).hexdigest()

    def same_origin(self):
        origin = self.headers.get("Origin")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise RequestError(403, "Cross-site requests are not allowed.")
        if origin:
            try:
                parsed = urlsplit(origin)
            except ValueError as error:
                raise RequestError(403, "Invalid request origin.") from error
            if parsed.scheme not in ("http", "https") or parsed.netloc != self.headers.get("Host"):
                raise RequestError(403, "Origin does not match this application.")

    def body(self):
        if self.headers.get("Transfer-Encoding"):
            raise RequestError(400, "Transfer-Encoding is not supported.")
        if self.headers.get_content_type() != "application/json":
            raise RequestError(415, "Send application/json.")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isdigit():
            raise RequestError(411, "One valid Content-Length is required.")
        length = int(lengths[0])
        if length > MAX_BODY:
            raise RequestError(413, "Scenario exceeds the 128 KiB request limit.")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise RequestError(400, "Incomplete request body.")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError) as error:
            raise RequestError(400, "Request body must be valid JSON.") from error

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def dispatch(self, method):
        try:
            self.route(method)
        except RequestError as error:
            self.send(error.status, {"error": error.message})
        except ValidationError as error:
            self.send(422, {"error": str(error)})
        except StoreFull as error:
            self.send(409, {"error": str(error)})
        except (TimeoutError, ConnectionError):
            logging.warning("Client connection interrupted or timed out")
            self.close_connection = True
        except (sqlite3.Error, OSError):
            logging.exception("Storage or filesystem operation failed")
            self.send(503, {"error": "Local storage is unavailable. Try again or export an unsaved scenario."})

    def route(self, method):
        try:
            path = urlsplit(self.path).path
        except ValueError as error:
            raise RequestError(400, "Invalid request path.") from error
        if method == "GET" and path == "/health":
            return self.send(200, {"status": "ok", "app": "CommonTable", "version": "1.0"})
        if method == "GET" and path in STATIC:
            filename, content_type = STATIC[path]
            return self.send(200, (ROOT / filename).read_bytes(), content_type)
        if method == "GET" and path == "/api/demo":
            return self.send(200, json.loads((ROOT / "data/demo.json").read_text()))
        if path.startswith("/api/"):
            self.same_origin()
        if method == "GET" and path == "/api/scenarios":
            return self.send(200, {"items": self.server.store.list(self.owner())})
        if method == "POST" and path in ("/api/plan", "/api/export/csv", "/api/scenarios"):
            scenario = validate(self.body())
            if path == "/api/scenarios":
                return self.send(201, self.server.store.save(self.owner(), scenario))
            result = plan(scenario)
            if path == "/api/export/csv":
                return self.send(200, csv_export(scenario, result), "text/csv; charset=utf-8",
                                 "commontable-transfers.csv")
            return self.send(200, result)
        match = re.fullmatch(r"/api/scenarios/([a-f0-9]{32})", path)
        if match and method in ("GET", "DELETE"):
            owner = self.owner()
            if method == "DELETE":
                if not self.server.store.delete(owner, match[1]):
                    raise RequestError(404, "Snapshot not found in this browser session.")
                return self.send(200, {"deleted": True})
            scenario = self.server.store.get(owner, match[1])
            if scenario is None:
                raise RequestError(404, "Snapshot not found in this browser session.")
            return self.send(200, scenario)
        raise RequestError(404, "Not found.")


def main():
    parser = argparse.ArgumentParser(description="Run the CommonTable prototype")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8764")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    server = Server((args.host, args.port), os.environ.get("APP_DATA_DIR", ".runtime"))
    logging.info("CommonTable listening on %s:%s", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
