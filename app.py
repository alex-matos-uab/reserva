import os, sys, json, time, socket, sqlite3
import threading, webbrowser, logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, Response
from werkzeug.serving import make_server

APP_NAME = "ReservaLabUAB"
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    RESOURCE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RESOURCE_DIR = BASE_DIR

DATA_DIR = BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "reservas.db")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LOG_PATH = os.path.join(DATA_DIR, "reserva.log")

logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

PORTA = 5757
NOME_LAB = "Laboratório UAB"

DEFAULT_CONFIG = {
    "turnos": [
        {"id": "matutino",   "nome": "Matutino",   "inicio": "08:00", "fim": "12:00"},
        {"id": "vespertino", "nome": "Vespertino", "inicio": "13:00", "fim": "17:00"},
        {"id": "noturno",    "nome": "Noturno",    "inicio": "18:00", "fim": "22:00"},
    ],
    "admin_senha": "admin123",
}

def carregar_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            c = json.load(f)
            if "turnos" not in c:
                c["turnos"] = DEFAULT_CONFIG["turnos"]
            return c
    except Exception:
        return dict(DEFAULT_CONFIG)

def salvar_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

app = Flask(__name__, template_folder=os.path.join(RESOURCE_DIR, "templates"),
            static_folder=os.path.join(RESOURCE_DIR, "templates"))
app.secret_key = "uab-lab-secret-" + str(time.time())

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reservas (
            id TEXT PRIMARY KEY, data TEXT NOT NULL,
            sala TEXT NOT NULL DEFAULT 'Laboratório UAB',
            turno TEXT NOT NULL DEFAULT '',
            slot TEXT DEFAULT '',
            nome TEXT NOT NULL, email TEXT DEFAULT '',
            matricula TEXT, finalidade TEXT NOT NULL,
            atendente TEXT DEFAULT '',
            grupo_id TEXT DEFAULT '',
            recorrente INTEGER DEFAULT 0,
            criado_em TEXT NOT NULL
        )
    """)
    # Migrações seguras para bancos antigos
    for col in ["turno TEXT NOT NULL DEFAULT ''",
                "atendente TEXT DEFAULT ''",
                "grupo_id TEXT DEFAULT ''",
                "recorrente INTEGER DEFAULT 0"]:
        try: conn.execute(f"ALTER TABLE reservas ADD COLUMN {col}")
        except Exception: pass
    try: conn.execute("DROP INDEX IF EXISTS idx_slot")
    except Exception: pass
    # O índice único agora considera (data, turno) pois só há 1 laboratório
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_turno ON reservas(data, sala, turno)")
    conn.commit()
    conn.close()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/config")
def api_config():
    c = carregar_config()
    return jsonify({"turnos": c["turnos"]})

@app.route("/api/reservas", methods=["GET"])
def api_listar():
    data = request.args.get("data", "")
    conn = get_db()
    rows = conn.execute("SELECT * FROM reservas WHERE data = ? ORDER BY turno", (data,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/reservas", methods=["POST"])
def api_criar():
    d = request.get_json(silent=True) or {}
    for c in ("data", "turno", "nome", "finalidade", "atendente"):
        if not str(d.get(c, "")).strip():
            return jsonify({"erro": f"Campo obrigatório ausente: {c}"}), 400

    grupo_id = d.get("grupo_id") or f"g{int(time.time()*1000)}-{os.urandom(3).hex()}"
    rid = f"{int(time.time()*1000)}-{os.urandom(3).hex()}"
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO reservas (id,data,sala,turno,slot,nome,email,matricula,finalidade,atendente,grupo_id,recorrente,criado_em) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, d["data"], NOME_LAB, d["turno"], d["turno"],
             d["nome"].strip(), (d.get("email") or "").strip(),
             (d.get("matricula") or "").strip(), d["finalidade"].strip(),
             d["atendente"].strip(), grupo_id,
             1 if d.get("recorrente") else 0,
             datetime.now().isoformat())
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return jsonify({"erro": "Este turno já está reservado."}), 409
    conn.close()
    return jsonify({"ok": True, "id": rid, "grupo_id": grupo_id})

@app.route("/api/grupos/<grupo_id>", methods=["DELETE"])
def api_apagar_grupo(grupo_id):
    if not session.get("admin"):
        return jsonify({"erro": "Apenas administradores podem cancelar."}), 403
    conn = get_db()
    conn.execute("DELETE FROM reservas WHERE grupo_id = ?", (grupo_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/login", methods=["POST"])
def api_login():
    d = request.get_json(silent=True) or {}
    if d.get("senha") == carregar_config()["admin_senha"]:
        session["admin"] = True
        return jsonify({"ok": True})
    return jsonify({"erro": "Senha incorreta."}), 401

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop("admin", None)
    return jsonify({"ok": True})

@app.route("/api/status")
def api_status():
    return jsonify({"admin": bool(session.get("admin"))})

@app.route("/api/exportar")
def api_exportar():
    if not session.get("admin"):
        return jsonify({"erro": "Acesso negado."}), 403
    conn = get_db()
    rows = conn.execute("SELECT * FROM reservas ORDER BY data, turno").fetchall()
    conn.close()
    def gerar():
        yield "\uFEFFData;Turno;Solicitante;Atendente;Finalidade;Recorrente\r\n"
        for r in rows:
            linha = [r["data"], r["turno"], r["nome"], r["atendente"],
                     r["finalidade"], "Sim" if r["recorrente"] else "Não"]
            yield ";".join('"' + str(c).replace('"', '""') + '"' for c in linha) + "\r\n"
    return Response(gerar(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=reservas-uab.csv"})

@app.route("/api/config", methods=["PUT"])
def api_config_salvar():
    if not session.get("admin"):
        return jsonify({"erro": "Acesso negado."}), 403
    d = request.get_json(silent=True) or {}
    cfg = carregar_config()
    if d.get("admin_senha"):
        cfg["admin_senha"] = str(d["admin_senha"])
    salvar_config(cfg)
    return jsonify({"ok": True})

class ServerThread(threading.Thread):
    def __init__(self, app, host, port):
        super().__init__(daemon=True)
        self.srv = make_server(host, port, app)
    def run(self): self.srv.serve_forever()
    def shutdown(self): self.srv.shutdown()

_server = None

@app.route("/api/sair", methods=["POST"])
def api_sair():
    if not session.get("admin"): return jsonify({"erro": "Negado"}), 403
    def parar():
        time.sleep(0.4)
        if _server: _server.shutdown()
    threading.Thread(target=parar, daemon=True).start()
    return jsonify({"ok": True})

def porta_em_uso(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0

def abrir_navegador(port):
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2): break
        except OSError: time.sleep(0.1)
    webbrowser.open(f"http://127.0.0.1:{port}")

def main():
    global _server
    try:
        init_db()
        if porta_em_uso(PORTA):
            webbrowser.open(f"http://127.0.0.1:{PORTA}")
            return
        threading.Thread(target=abrir_navegador, args=(PORTA,), daemon=True).start()
        _server = ServerThread(app, "127.0.0.1", PORTA)
        _server.start()
        _server.join()
    except Exception as e:
        try:
            import tkinter.messagebox as mb
            mb.showerror("Erro", f"Não foi possível iniciar:\n\n{e}")
        except Exception: pass
        sys.exit(1)

if __name__ == "__main__":
    main()