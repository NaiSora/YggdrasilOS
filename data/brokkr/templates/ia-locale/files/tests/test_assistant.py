import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from {{snake}}.assistant import Assistant
from {{snake}}.ollama import Ollama


class FauxOllama(BaseHTTPRequestHandler):
    recus: list = []

    def do_GET(self):
        self._json({"models": [{"name": "essai:1b"}]})

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FauxOllama.recus.append(corps)
        self.send_response(200)
        self.end_headers()
        for mot in ("Bon", "jour", " !"):
            self.wfile.write(json.dumps({"message": {"content": mot}, "done": False}).encode() + b"\n")
        self.wfile.write(json.dumps({"done": True}).encode() + b"\n")

    def _json(self, donnees):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(donnees).encode())

    def log_message(self, *args):
        pass


def test_conversation():
    serveur = HTTPServer(("127.0.0.1", 0), FauxOllama)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    client = Ollama(f"http://127.0.0.1:{serveur.server_port}")
    assert client.modeles() == ["essai:1b"]
    assistant = Assistant(client, "essai:1b", memoire=2)
    assert "".join(assistant.demander("Salut")) == "Bonjour !"
    "".join(assistant.demander("Encore"))
    dernier = FauxOllama.recus[-1]
    assert dernier["model"] == "essai:1b" and dernier["stream"] is True
    assert [m["role"] for m in dernier["messages"]] == ["system", "assistant", "user"]
    serveur.shutdown()
