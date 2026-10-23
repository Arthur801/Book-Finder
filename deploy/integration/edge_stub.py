"""Local stand-in for the host nginx: forwards to the web container and adds the header nginx sets in production.

Why: the public health probe goes through the edge. Without X-Forwarded-Proto the app answers 307 to HTTPS, which is
what production nginx prevents, so the stand-in must add it too. Used only by the local integration run.

Response handling: only the upstream status and body are relayed. Health probes need nothing else, and echoing
upstream response headers back to the client is unnecessary and was flagged by CodeQL (py/http-response-splitting).
Content-Type is therefore fixed to application/octet-stream.
Usage: edge_stub.py <listen-port> <upstream-port>
"""

import http.client
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "content-length", "host"}


def make_handler(upstream_port: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            headers = {name: value for name, value in self.headers.items() if name.lower() not in HOP_BY_HOP}
            # nginx sets this for TLS termination; the app trusts it only from the container network.
            headers["X-Forwarded-Proto"] = "https"
            connection = http.client.HTTPConnection("127.0.0.1", upstream_port, timeout=15)
            try:
                connection.request("GET", self.path, headers=headers)
                response = connection.getresponse()
                body = response.read()
            except OSError:
                self.send_error(502)
                return
            finally:
                connection.close()
            self.send_response(response.status)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def main(argv: list[str]) -> None:
    listen, upstream = int(argv[0]), int(argv[1])
    ThreadingHTTPServer(("127.0.0.1", listen), make_handler(upstream)).serve_forever()


if __name__ == "__main__":
    main(sys.argv[1:])
