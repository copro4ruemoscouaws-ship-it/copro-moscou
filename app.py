"""Espace copropriété — 4 rue de Moscou.

Application Flask : documents (recherche dans le contenu PDF/Word), chantiers liés
aux documents, tableau de bord, connexion par lien email, rôles admin / membre.
"""
import hashlib
import mimetypes
import os
import secrets
from datetime import datetime, timedelta, date
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from markupsafe import Markup, escape

import db as database
from services import extract_text, make_storage, send_login_email

# ------------------------------------------------------------------ Config

BASE = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    BASE_URL=os.environ.get("BASE_URL", "http://localhost:5000").rstrip("/"),
    STORAGE=os.environ.get("STORAGE", "local"),          # local | s3
    UPLOAD_DIR=os.environ.get("UPLOAD_DIR", os.path.join(BASE, "data", "fichiers")),
    S3_BUCKET=os.environ.get("S3_BUCKET", ""),
    AWS_REGION=os.environ.get("AWS_REGION", "eu-north-1"),  # Stockholm (région du compte)
    MAIL=os.environ.get("MAIL", "console"),               # console | ses
    MAIL_FROM=os.environ.get("MAIL_FROM", "copro@example.com"),
    DEV_SHOW_LINK=os.environ.get("DEV_SHOW_LINK", "1") == "1",  # affiche le lien à l'écran (dev uniquement)
    LOGIN_THROTTLE=int(os.environ.get("LOGIN_THROTTLE", "30")),  # secondes minimum entre deux demandes de code
    MAX_CONTENT_LENGTH=30 * 1024 * 1024,                   # 30 Mo par fichier
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("BASE_URL", "").startswith("https"),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
app.teardown_appcontext(database.close_db)
storage = make_storage(app.config)

ALLOWED_EXT = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".odt", ".txt", ".jpg", ".jpeg", ".png"}

DOC_CATEGORIES = ["PV d'AG", "Convocation AG", "Règlement", "Contrat", "Devis", "Facture",
                  "Diagnostic", "Courrier", "Assurance", "Plan", "Photo", "Autre"]
CHANTIER_CATEGORIES = ["Chauffage / énergie", "Façade / ravalement", "Toiture", "Ascenseur",
                       "Parties communes", "Plomberie", "Électricité", "Sécurité / accès",
                       "Espaces verts", "Autre"]
STATUSES = ["Idée", "Devis en cours", "Voté en AG", "En cours", "Terminé"]


# ------------------------------------------------------------------ Helpers

def euros(value):
    if value is None or value == "":
        return "—"
    return f"{value:,.0f} €".replace(",", " ")


def date_fr(value):
    if not value:
        return "—"
    try:
        d = datetime.fromisoformat(str(value)[:19])
    except ValueError:
        return value
    mois = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août",
            "sept.", "oct.", "nov.", "déc."]
    return f"{d.day} {mois[d.month - 1]} {d.year}"


def datetime_fr(value):
    """Date et heure en heure de Paris (la base enregistre en UTC)."""
    if not value:
        return "—"
    try:
        from zoneinfo import ZoneInfo
        d = datetime.fromisoformat(str(value)[:19]).replace(tzinfo=ZoneInfo("UTC"))
        d = d.astimezone(ZoneInfo("Europe/Paris"))
    except (ValueError, KeyError):
        return value
    jour = date_fr(d.isoformat())
    if d.date() == datetime.now(ZoneInfo("Europe/Paris")).date():
        jour = "aujourd'hui"
    return f"{jour} à {d.hour} h {d.minute:02d}"


def size_fr(n):
    if not n:
        return ""
    for unit in ("o", "Ko", "Mo"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return f"{n:.1f} Go"


def initials(name):
    parts = [p for p in (name or "?").split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def status_slug(status):
    return {"Idée": "idee", "Devis en cours": "devis", "Voté en AG": "vote",
            "En cours": "encours", "Terminé": "termine"}.get(status, "idee")


app.jinja_env.filters.update(euros=euros, date_fr=date_fr, datetime_fr=datetime_fr, size_fr=size_fr,
                             initials=initials, status_slug=status_slug)


def parse_money(value):
    value = (value or "").replace("€", "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(value) if value else None
    except ValueError:
        return None


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


# ------------------------------------------------------------------ Sécurité

@app.before_request
def load_user_and_csrf():
    g.user = None
    uid = session.get("uid")
    if uid:
        user = database.get_db().execute(
            "SELECT * FROM users WHERE id = ? AND active = 1", (uid,)).fetchone()
        if user:
            g.user = user
        else:
            session.clear()
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    if request.method == "POST":
        sent = request.form.get("csrf") or request.headers.get("X-CSRF")
        if not sent or not secrets.compare_digest(sent, session["csrf"]):
            abort(400, "Jeton de sécurité invalide, rechargez la page.")


@app.context_processor
def inject_globals():
    return {"csrf_token": session.get("csrf", ""), "user": g.get("user"),
            "STATUSES": STATUSES, "today": date.today().isoformat()}


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not g.user:
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not g.user:
            return redirect(url_for("login", next=request.path))
        if g.user["role"] != "admin":
            abort(403)
        return view(*a, **kw)
    return wrapped


# ------------------------------------------------------------------ Connexion

def safe_next(value):
    value = value or ""
    return value if value.startswith("/") and not value.startswith("//") else ""


def open_session(user_id):
    session.clear()
    session.permanent = True
    session["uid"] = user_id
    session["csrf"] = secrets.token_urlsafe(24)
    db = database.get_db()
    db.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?", (user_id,))
    database.log(user_id, "Connexion", "")
    db.commit()


@app.route("/connexion", methods=["GET", "POST"])
def login():
    """Étape 1 : l'adresse email. On envoie un lien ET un code à 6 chiffres.

    Le code sert quand le lien s'ouvre ailleurs que là où l'on veut se connecter :
    emails lus sur le téléphone mais site ouvert sur la tablette, ou site ajouté
    à l'écran d'accueil (qui n'est pas le même navigateur que celui de l'email).
    """
    if g.user:
        return redirect(url_for("dashboard"))
    dev = None
    email = ""
    nxt = safe_next(request.args.get("next"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        db = database.get_db()
        now = datetime.utcnow()
        user = db.execute("SELECT * FROM users WHERE email = ? AND active = 1", (email,)).fetchone()
        if user:
            last = db.execute("SELECT created_at FROM login_tokens WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                              (user["id"],)).fetchone()
            recent = last and last["created_at"] > (now - timedelta(seconds=app.config["LOGIN_THROTTLE"])).isoformat()
            if not recent:
                token = secrets.token_urlsafe(32)
                code = f"{secrets.randbelow(1_000_000):06d}"
                db.execute("DELETE FROM login_tokens WHERE user_id = ? OR expires_at < ?", (user["id"], now.isoformat()))
                db.execute("""INSERT INTO login_tokens (token_hash, user_id, expires_at, code_hash, created_at)
                              VALUES (?, ?, ?, ?, ?)""",
                           (hash_token(token), user["id"], (now + timedelta(minutes=15)).isoformat(),
                            hash_token(f"{user['id']}:{code}"), now.isoformat()))
                db.commit()
                link = f"{app.config['BASE_URL']}{url_for('auth', token=token)}"
                if nxt:
                    link += f"?next={nxt}"
                send_login_email(app.config, user["email"], user["name"], link, code)
                if app.config["DEV_SHOW_LINK"]:
                    dev = {"link": link, "code": code}
        # Même écran que l'adresse soit connue ou non : on ne révèle pas qui est membre.
        return render_template("login.html", sent=True, email=email, nxt=nxt, dev=dev)
    return render_template("login.html", sent=False, nxt=nxt, dev=None)


@app.route("/connexion/code", methods=["POST"])
def login_code():
    """Étape 2 (au choix) : saisir le code à 6 chiffres reçu par email."""
    email = (request.form.get("email") or "").strip().lower()
    code = "".join(ch for ch in (request.form.get("code") or "") if ch.isdigit())
    nxt = safe_next(request.form.get("next"))
    db = database.get_db()
    now = datetime.utcnow().isoformat()
    user = db.execute("SELECT * FROM users WHERE email = ? AND active = 1", (email,)).fetchone()
    row = None
    if user:
        row = db.execute("""SELECT * FROM login_tokens WHERE user_id = ? AND used = 0 AND expires_at > ?
                            ORDER BY created_at DESC LIMIT 1""", (user["id"], now)).fetchone()
    if row and row["attempts"] < 5 and len(code) == 6 and \
            secrets.compare_digest(row["code_hash"] or "", hash_token(f"{user['id']}:{code}")):
        db.execute("UPDATE login_tokens SET used = 1 WHERE token_hash = ?", (row["token_hash"],))
        db.commit()
        open_session(user["id"])
        return redirect(nxt or url_for("dashboard"))
    if row:
        db.execute("UPDATE login_tokens SET attempts = attempts + 1 WHERE token_hash = ?", (row["token_hash"],))
        db.commit()
    if row and row["attempts"] + 1 >= 5:
        error = "Trop d'essais. Demandez un nouveau code."
    else:
        error = "Code incorrect ou expiré. Vérifiez les 6 chiffres reçus par email."
    return render_template("login.html", sent=True, email=email, nxt=nxt, dev=None, error=error), 400


@app.route("/auth/<token>")
def auth(token):
    db = database.get_db()
    row = db.execute("SELECT * FROM login_tokens WHERE token_hash = ?", (hash_token(token),)).fetchone()
    if not row or row["used"] or row["expires_at"] < datetime.utcnow().isoformat():
        flash("Ce lien a expiré ou a déjà été utilisé. Demandez-en un nouveau.", "error")
        return redirect(url_for("login"))
    db.execute("UPDATE login_tokens SET used = 1 WHERE token_hash = ?", (row["token_hash"],))
    db.commit()
    open_session(row["user_id"])
    return redirect(safe_next(request.args.get("next")) or url_for("dashboard"))


@app.route("/deconnexion", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------------ Tableau de bord

@app.route("/")
@login_required
def dashboard():
    db = database.get_db()
    counts = {s: 0 for s in STATUSES}
    for r in db.execute("SELECT status, COUNT(*) n FROM chantiers GROUP BY status"):
        counts[r["status"]] = r["n"]
    actifs = db.execute("""
        SELECT c.*, u.name AS responsable,
               (SELECT COUNT(*) FROM chantier_documents cd WHERE cd.chantier_id = c.id) AS nb_docs
        FROM chantiers c LEFT JOIN users u ON u.id = c.responsable_id
        WHERE c.status != 'Terminé'
        ORDER BY CASE c.status WHEN 'En cours' THEN 0 WHEN 'Voté en AG' THEN 1
                 WHEN 'Devis en cours' THEN 2 ELSE 3 END, c.date_echeance IS NULL, c.date_echeance
    """).fetchall()
    echeances = db.execute("""
        SELECT id, title, date_echeance, status FROM chantiers
        WHERE status != 'Terminé' AND date_echeance IS NOT NULL AND date_echeance != ''
        ORDER BY date_echeance LIMIT 5
    """).fetchall()
    budget = db.execute("""
        SELECT COALESCE(SUM(budget_prevu), 0) prevu, COALESCE(SUM(budget_engage), 0) engage
        FROM chantiers WHERE status != 'Idée'
    """).fetchone()
    recents = db.execute("""
        SELECT d.*, u.name AS auteur FROM documents d LEFT JOIN users u ON u.id = d.uploaded_by
        ORDER BY d.uploaded_at DESC LIMIT 6
    """).fetchall()
    nb_docs = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    return render_template("dashboard.html", counts=counts, actifs=actifs, echeances=echeances,
                           budget=budget, recents=recents, nb_docs=nb_docs)


# ------------------------------------------------------------------ Documents

@app.route("/documents")
@login_required
def documents():
    db = database.get_db()
    q = (request.args.get("q") or "").strip()
    cat = request.args.get("categorie") or ""
    chantier = request.args.get("chantier") or ""
    params, where = [], []
    if cat:
        where.append("d.category = ?")
        params.append(cat)
    if chantier:
        where.append("d.id IN (SELECT document_id FROM chantier_documents WHERE chantier_id = ?)")
        params.append(chantier)

    results = []
    if q:
        fq = database.fts_query(q)
        if fq:
            sql = f"""
                SELECT d.*, u.name AS auteur,
                       snippet(documents_fts, 1, '[[', ']]', ' … ', 18) AS extrait,
                       highlight(documents_fts, 0, '[[', ']]') AS titre_hl
                FROM documents_fts
                JOIN documents d ON d.id = documents_fts.rowid
                LEFT JOIN users u ON u.id = d.uploaded_by
                WHERE documents_fts MATCH ? {"AND " + " AND ".join(where) if where else ""}
                ORDER BY bm25(documents_fts, 5.0, 1.0)
                LIMIT 100
            """
            try:
                results = db.execute(sql, [fq] + params).fetchall()
            except Exception:
                results = []
    else:
        sql = f"""
            SELECT d.*, u.name AS auteur, NULL AS extrait, NULL AS titre_hl
            FROM documents d LEFT JOIN users u ON u.id = d.uploaded_by
            {"WHERE " + " AND ".join(where) if where else ""}
            ORDER BY COALESCE(d.doc_date, d.uploaded_at) DESC LIMIT 300
        """
        results = db.execute(sql, params).fetchall()

    links = {}
    if results:
        ids = [r["id"] for r in results]
        for r in db.execute(f"""
            SELECT cd.document_id, c.id, c.title FROM chantier_documents cd
            JOIN chantiers c ON c.id = cd.chantier_id
            WHERE cd.document_id IN ({",".join("?" * len(ids))})""", ids):
            links.setdefault(r["document_id"], []).append(r)

    chantiers = db.execute("SELECT id, title FROM chantiers ORDER BY title").fetchall()
    return render_template("documents.html", results=results, q=q, cat=cat, chantier=chantier,
                           categories=DOC_CATEGORIES, chantiers=chantiers, links=links)


def highlight(text):
    """Convertit les marqueurs [[ ]] de SQLite en <mark>, après échappement HTML."""
    if not text:
        return ""
    safe = str(escape(text))
    return Markup(safe.replace("[[", "<mark>").replace("]]", "</mark>"))


app.jinja_env.filters["hl"] = highlight


@app.route("/documents/nouveau", methods=["GET", "POST"])
@login_required
def document_new():
    db = database.get_db()
    chantiers = db.execute("SELECT id, title, status FROM chantiers ORDER BY status = 'Terminé', title").fetchall()
    preselect = request.args.get("chantier", type=int)
    if request.method == "POST":
        files = [f for f in request.files.getlist("fichiers") if f and f.filename]
        category = request.form.get("category") or "Autre"
        doc_date = request.form.get("doc_date") or None
        title_base = (request.form.get("title") or "").strip()
        linked = [int(x) for x in request.form.getlist("chantiers") if x.isdigit()]
        if not files:
            flash("Choisissez au moins un fichier.", "error")
            return render_template("document_form.html", chantiers=chantiers,
                                   categories=DOC_CATEGORIES, preselect=preselect)
        created = []
        for f in files:
            ext = os.path.splitext(f.filename)[1].lower()
            if ext not in ALLOWED_EXT:
                flash(f"« {f.filename} » ignoré : format non accepté.", "error")
                continue
            data = f.read()
            text = extract_text(data, f.filename)
            title = title_base if (title_base and len(files) == 1) else \
                (f"{title_base} — {os.path.splitext(f.filename)[0]}" if title_base
                 else os.path.splitext(f.filename)[0].replace("_", " "))
            mime = f.mimetype or mimetypes.guess_type(f.filename)[0]
            key = storage.save(data, f.filename, mime)
            cur = db.execute("""
                INSERT INTO documents (title, category, doc_date, filename, storage_key, mime, size,
                                       has_text, uploaded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, category, doc_date, f.filename, key, mime, len(data), 1 if text else 0, g.user["id"]))
            doc_id = cur.lastrowid
            database.index_document(db, doc_id, title, text)
            for cid in linked:
                db.execute("INSERT OR IGNORE INTO chantier_documents VALUES (?, ?)", (cid, doc_id))
            database.log(g.user["id"], "Document ajouté", title)
            created.append((doc_id, title, bool(text), ext))
        db.commit()
        if created:
            sans_texte = [t for (_, t, has, ext) in created if not has and ext in (".pdf", ".docx")]
            msg = f"{len(created)} document(s) ajouté(s)."
            if sans_texte:
                msg += " Aucun texte lisible dans : " + ", ".join(sans_texte) + \
                       " (probablement un scan : seul le titre sera recherchable)."
            flash(msg, "ok")
            if len(created) == 1:
                return redirect(url_for("document_detail", doc_id=created[0][0]))
        return redirect(url_for("documents"))
    return render_template("document_form.html", chantiers=chantiers,
                           categories=DOC_CATEGORIES, preselect=preselect)


def get_document(doc_id):
    doc = database.get_db().execute("""
        SELECT d.*, u.name AS auteur FROM documents d LEFT JOIN users u ON u.id = d.uploaded_by
        WHERE d.id = ?""", (doc_id,)).fetchone()
    if not doc:
        abort(404)
    return doc


@app.route("/documents/<int:doc_id>", methods=["GET", "POST"])
@login_required
def document_detail(doc_id):
    db = database.get_db()
    doc = get_document(doc_id)
    if request.method == "POST":
        title = (request.form.get("title") or doc["title"]).strip()
        category = request.form.get("category") or doc["category"]
        doc_date = request.form.get("doc_date") or None
        linked = {int(x) for x in request.form.getlist("chantiers") if x.isdigit()}
        db.execute("UPDATE documents SET title = ?, category = ?, doc_date = ? WHERE id = ?",
                   (title, category, doc_date, doc_id))
        body = db.execute("SELECT body FROM documents_fts WHERE rowid = ?", (doc_id,)).fetchone()
        database.index_document(db, doc_id, title, body["body"] if body else "")
        db.execute("DELETE FROM chantier_documents WHERE document_id = ?", (doc_id,))
        for cid in linked:
            db.execute("INSERT OR IGNORE INTO chantier_documents VALUES (?, ?)", (cid, doc_id))
        database.log(g.user["id"], "Document modifié", title)
        db.commit()
        flash("Document mis à jour.", "ok")
        return redirect(url_for("document_detail", doc_id=doc_id))

    chantiers = db.execute("SELECT id, title, status FROM chantiers ORDER BY status = 'Terminé', title").fetchall()
    linked = {r["chantier_id"] for r in db.execute(
        "SELECT chantier_id FROM chantier_documents WHERE document_id = ?", (doc_id,))}
    body = db.execute("SELECT body FROM documents_fts WHERE rowid = ?", (doc_id,)).fetchone()
    apercu = (body["body"] if body else "")[:3000]
    return render_template("document_detail.html", doc=doc, chantiers=chantiers, linked=linked,
                           categories=DOC_CATEGORIES, apercu=apercu)


@app.route("/documents/<int:doc_id>/fichier")
@login_required
def document_file(doc_id):
    doc = get_document(doc_id)
    url = storage.download_url(doc["storage_key"], doc["filename"], request.args.get("dl") == "1")
    if url:
        return redirect(url)
    return send_file(storage.path(doc["storage_key"]), mimetype=doc["mime"],
                     download_name=doc["filename"], as_attachment=request.args.get("dl") == "1")


@app.route("/documents/<int:doc_id>/supprimer", methods=["POST"])
@admin_required
def document_delete(doc_id):
    db = database.get_db()
    doc = get_document(doc_id)
    storage.delete(doc["storage_key"])
    database.unindex_document(db, doc_id)
    db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    database.log(g.user["id"], "Document supprimé", doc["title"])
    db.commit()
    flash(f"« {doc['title']} » supprimé.", "ok")
    return redirect(url_for("documents"))


# ------------------------------------------------------------------ Chantiers

@app.route("/chantiers")
@login_required
def chantiers():
    db = database.get_db()
    cat = request.args.get("categorie") or ""
    rows = db.execute(f"""
        SELECT c.*, u.name AS responsable,
               (SELECT COUNT(*) FROM chantier_documents cd WHERE cd.chantier_id = c.id) AS nb_docs
        FROM chantiers c LEFT JOIN users u ON u.id = c.responsable_id
        {"WHERE c.category = ?" if cat else ""}
        ORDER BY c.date_echeance IS NULL, c.date_echeance, c.title
    """, [cat] if cat else []).fetchall()
    par_statut = {s: [r for r in rows if r["status"] == s] for s in STATUSES}
    return render_template("chantiers.html", par_statut=par_statut, cat=cat,
                           categories=CHANTIER_CATEGORIES)


def chantier_form_data():
    return dict(
        title=(request.form.get("title") or "").strip(),
        category=request.form.get("category") or "Autre",
        status=request.form.get("status") if request.form.get("status") in STATUSES else "Idée",
        description=(request.form.get("description") or "").strip(),
        budget_prevu=parse_money(request.form.get("budget_prevu")),
        budget_engage=parse_money(request.form.get("budget_engage")),
        date_debut=request.form.get("date_debut") or None,
        date_echeance=request.form.get("date_echeance") or None,
        responsable_id=request.form.get("responsable_id", type=int),
    )


@app.route("/chantiers/nouveau", methods=["GET", "POST"])
@login_required
def chantier_new():
    db = database.get_db()
    if request.method == "POST":
        d = chantier_form_data()
        if not d["title"]:
            flash("Donnez un nom au chantier.", "error")
        else:
            cur = db.execute("""
                INSERT INTO chantiers (title, category, status, description, budget_prevu, budget_engage,
                                       date_debut, date_echeance, responsable_id)
                VALUES (:title, :category, :status, :description, :budget_prevu, :budget_engage,
                        :date_debut, :date_echeance, :responsable_id)""", d)
            database.log(g.user["id"], "Chantier créé", d["title"])
            db.commit()
            flash("Chantier créé.", "ok")
            return redirect(url_for("chantier_detail", cid=cur.lastrowid))
    membres = db.execute("SELECT id, name FROM users WHERE active = 1 ORDER BY name").fetchall()
    return render_template("chantier_form.html", c=None, membres=membres,
                           categories=CHANTIER_CATEGORIES)


@app.route("/chantiers/<int:cid>")
@login_required
def chantier_detail(cid):
    db = database.get_db()
    c = db.execute("""SELECT c.*, u.name AS responsable FROM chantiers c
                      LEFT JOIN users u ON u.id = c.responsable_id WHERE c.id = ?""", (cid,)).fetchone()
    if not c:
        abort(404)
    docs = db.execute("""
        SELECT d.* FROM documents d JOIN chantier_documents cd ON cd.document_id = d.id
        WHERE cd.chantier_id = ? ORDER BY COALESCE(d.doc_date, d.uploaded_at) DESC""", (cid,)).fetchall()
    autres = db.execute("""
        SELECT id, title, category FROM documents
        WHERE id NOT IN (SELECT document_id FROM chantier_documents WHERE chantier_id = ?)
        ORDER BY uploaded_at DESC LIMIT 200""", (cid,)).fetchall()
    return render_template("chantier_detail.html", c=c, docs=docs, autres=autres)


@app.route("/chantiers/<int:cid>/modifier", methods=["GET", "POST"])
@login_required
def chantier_edit(cid):
    db = database.get_db()
    c = db.execute("SELECT * FROM chantiers WHERE id = ?", (cid,)).fetchone()
    if not c:
        abort(404)
    if request.method == "POST":
        d = chantier_form_data()
        d["id"] = cid
        if not d["title"]:
            flash("Donnez un nom au chantier.", "error")
        else:
            db.execute("""
                UPDATE chantiers SET title=:title, category=:category, status=:status,
                    description=:description, budget_prevu=:budget_prevu, budget_engage=:budget_engage,
                    date_debut=:date_debut, date_echeance=:date_echeance, responsable_id=:responsable_id,
                    updated_at=datetime('now')
                WHERE id = :id""", d)
            detail = d["title"] + (f" → {d['status']}" if d["status"] != c["status"] else "")
            database.log(g.user["id"], "Chantier modifié", detail)
            db.commit()
            flash("Chantier mis à jour.", "ok")
            return redirect(url_for("chantier_detail", cid=cid))
    membres = db.execute("SELECT id, name FROM users WHERE active = 1 ORDER BY name").fetchall()
    return render_template("chantier_form.html", c=c, membres=membres, categories=CHANTIER_CATEGORIES)


@app.route("/chantiers/<int:cid>/lier", methods=["POST"])
@login_required
def chantier_link(cid):
    db = database.get_db()
    doc_id = request.form.get("document_id", type=int)
    action = request.form.get("action", "lier")
    if doc_id:
        if action == "delier":
            db.execute("DELETE FROM chantier_documents WHERE chantier_id = ? AND document_id = ?", (cid, doc_id))
        else:
            db.execute("INSERT OR IGNORE INTO chantier_documents VALUES (?, ?)", (cid, doc_id))
        db.commit()
    return redirect(url_for("chantier_detail", cid=cid))


@app.route("/chantiers/<int:cid>/supprimer", methods=["POST"])
@admin_required
def chantier_delete(cid):
    db = database.get_db()
    c = db.execute("SELECT title FROM chantiers WHERE id = ?", (cid,)).fetchone()
    if c:
        db.execute("DELETE FROM chantiers WHERE id = ?", (cid,))
        database.log(g.user["id"], "Chantier supprimé", c["title"])
        db.commit()
        flash("Chantier supprimé (les documents sont conservés).", "ok")
    return redirect(url_for("chantiers"))


# ------------------------------------------------------------------ Membres (admin)

@app.route("/membres", methods=["GET", "POST"])
@login_required
def membres():
    db = database.get_db()
    if request.method == "POST":
        if g.user["role"] != "admin":
            abort(403)
        action = request.form.get("action")
        uid = request.form.get("user_id", type=int)
        if action == "ajouter":
            email = (request.form.get("email") or "").strip().lower()
            name = (request.form.get("name") or "").strip()
            lot = (request.form.get("lot") or "").strip()
            role = "admin" if request.form.get("role") == "admin" else "membre"
            if "@" not in email or not name:
                flash("Nom et adresse email requis.", "error")
            else:
                try:
                    db.execute("INSERT INTO users (email, name, lot, role) VALUES (?, ?, ?, ?)",
                               (email, name, lot, role))
                    database.log(g.user["id"], "Membre ajouté", f"{name} ({email})")
                    flash(f"{name} peut maintenant se connecter avec {email}.", "ok")
                except Exception:
                    db.execute("UPDATE users SET active = 1, name = ?, lot = ?, role = ? WHERE email = ?",
                               (name, lot, role, email))
                    flash(f"{name} réactivé.", "ok")
        elif uid and uid != g.user["id"]:
            target = db.execute("SELECT name FROM users WHERE id = ?", (uid,)).fetchone()
            if action == "desactiver":
                db.execute("UPDATE users SET active = 0 WHERE id = ?", (uid,))
                database.log(g.user["id"], "Accès retiré", target["name"])
                flash(f"Accès retiré à {target['name']}.", "ok")
            elif action == "reactiver":
                db.execute("UPDATE users SET active = 1 WHERE id = ?", (uid,))
                flash(f"Accès rétabli pour {target['name']}.", "ok")
            elif action in ("admin", "membre"):
                db.execute("UPDATE users SET role = ? WHERE id = ?", (action, uid))
                flash(f"Rôle de {target['name']} mis à jour.", "ok")
        db.commit()
        return redirect(url_for("membres"))
    users = db.execute("SELECT * FROM users ORDER BY active DESC, name COLLATE NOCASE").fetchall()
    journal = []
    if g.user["role"] == "admin":
        journal = db.execute("""SELECT j.*, u.name FROM journal j LEFT JOIN users u ON u.id = j.user_id
                                ORDER BY j.id DESC LIMIT 40""").fetchall()
    return render_template("membres.html", users=users, journal=journal)


# ------------------------------------------------------------------ Erreurs

@app.errorhandler(403)
def forbidden(_e):
    return render_template("erreur.html", titre="Accès réservé",
                           message="Cette action est réservée aux administrateurs."), 403


@app.errorhandler(404)
def not_found(_e):
    return render_template("erreur.html", titre="Page introuvable",
                           message="Ce document ou ce chantier n'existe pas ou a été supprimé."), 404


@app.errorhandler(413)
def too_large(_e):
    return render_template("erreur.html", titre="Fichier trop volumineux",
                           message="La limite est de 30 Mo par envoi. Compressez le PDF ou envoyez les fichiers séparément."), 413


# ------------------------------------------------------------------ CLI

@app.cli.command("init-db")
def init_db_cmd():
    """Crée les tables."""
    database.init_db()
    print("Base initialisée :", database.DB_PATH)


@app.cli.command("add-admin")
def add_admin_cmd():
    """Crée le premier administrateur : ADMIN_EMAIL=... ADMIN_NAME=... flask add-admin"""
    import click
    email = os.environ.get("ADMIN_EMAIL") or click.prompt("Email")
    name = os.environ.get("ADMIN_NAME") or click.prompt("Nom")
    database.init_db()
    conn = database.connect()
    conn.execute("""INSERT INTO users (email, name, role) VALUES (?, ?, 'admin')
                    ON CONFLICT(email) DO UPDATE SET role = 'admin', active = 1""", (email.lower(), name))
    conn.commit()
    conn.close()
    print(f"Administrateur prêt : {name} <{email}>")


database.init_db()

if __name__ == "__main__":
    app.run(debug=True)
