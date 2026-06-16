"""
Oraculo Risk Engine - zero-dependency localhost server.

Routes:
  GET  /                -> static UI
  POST /api/analyze     -> body: raw PDF bytes; returns {state, eligible, locked}
  POST /api/simulate    -> JSON {state, basket}; returns joint-risk simulation

Run:  python server.py   then open http://localhost:8000
"""
import os, json, warnings
warnings.filterwarnings("ignore")
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import engine  # noqa: E402
import scheduler  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
PORT = 8000

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "json" in ctype or "html" in ctype else ""))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n) if n else b""

    def log_message(self, *a):  # quieter console
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            path = "/index.html"
        fp = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if not fp.startswith(STATIC) or not os.path.isfile(fp):
            return self._send(404, {"error": "not found"})
        ctype = ("text/html" if fp.endswith(".html") else
                 "application/javascript" if fp.endswith(".js") else
                 "text/css" if fp.endswith(".css") else "application/octet-stream")
        with open(fp, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_POST(self):
        try:
            if self.path == "/api/analyze":
                pdf = self._body()
                state = engine.parse_transcript(pdf)
                elig = engine.eligible(state)
                return self._send(200, {"state": state, **elig})
            if self.path == "/api/simulate":
                payload = json.loads(self._body() or "{}")
                basket = payload.get("basket", [])
                sim = engine.simulate(payload.get("state", {}), basket)
                sim["schedule"] = scheduler.solve(basket)   # conflict solver
                return self._send(200, sim)
            return self._send(404, {"error": "unknown route"})
        except Exception as e:
            import traceback; traceback.print_exc()
            return self._send(500, {"error": str(e)})

if __name__ == "__main__":
    print(f"Oraculo Risk Engine  ->  http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
