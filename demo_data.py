"""Remplit une base de démonstration (membres fictifs, chantiers, PDF et Word d'exemple).

Usage :  python demo_data.py
À ne PAS lancer sur la base de production.
"""
import io
import os

os.environ.setdefault("DB_PATH", os.path.join(os.path.dirname(__file__), "data", "demo.db"))

import docx  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

import db as database  # noqa: E402
from app import app, storage  # noqa: E402
from services import extract_text  # noqa: E402


def make_pdf(lines):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in lines:
        c.drawString(60, y, line)
        y -= 18
    c.save()
    return buf.getvalue()


def make_docx(paragraphs):
    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


MEMBRES = [
    ("admin@copro-demo.fr", "Marc Henry", "Lot 7", "admin"),
    ("julien@copro-demo.fr", "Julien Dubreuil", "Lot 4", "membre"),
    ("sophie@copro-demo.fr", "Sophie Lambert", "Lot 8", "membre"),
    ("camille@copro-demo.fr", "Camille Martin", "Lot 12", "membre"),
]

CHANTIERS = [
    ("Remplacement chaudière collective", "Chauffage / énergie", "Voté en AG", 68000, 20400,
     "2026-11-15", "2027-02-28", 1,
     "Chaudière fioul de 1994 remplacée par une chaudière gaz à condensation.\n"
     "Acompte de 30 % versé à Thermique Paris Est après le vote de l'AG du 8 octobre."),
    ("Ravalement de façade rue", "Façade / ravalement", "Devis en cours", 145000, 0,
     None, "2027-03-15", 2,
     "Injonction de la Ville (ravalement décennal). 3 devis reçus, un 4e attendu."),
    ("Audit énergétique / DPE collectif", "Chauffage / énergie", "Terminé", 4200, 4200,
     "2026-03-01", "2026-06-30", 1, "Rapport remis en juin, classe E. Sert de base au plan de travaux."),
    ("Isolation des combles", "Toiture", "Idée", 32000, None, None, None, None,
     "Recommandé par l'audit énergétique (gain estimé 15 % sur le chauffage)."),
    ("Mise aux normes ascenseur", "Ascenseur", "En cours", 18500, 9200,
     "2026-09-01", "2026-12-10", 3, "Remplacement des portes palières et de l'armoire de commande."),
]

DOCS = [
    ("pdf", "PV Assemblée générale du 8 octobre 2026", "PV d'AG", "2026-10-08", [0, 1, 4],
     ["PROCES-VERBAL DE L'ASSEMBLEE GENERALE ORDINAIRE", "Copropriete du 4 rue de Moscou, 91300 Massy",
      "Seance du 8 octobre 2026", "",
      "Resolution 12 : remplacement de la chaudiere collective fioul par une chaudiere",
      "gaz a condensation. Devis Thermique Paris Est retenu pour 68 000 euros TTC.",
      "Adoptee a la majorite de l'article 25.", "",
      "Resolution 13 : ravalement de la facade rue. L'assemblee mandate le conseil",
      "syndical pour obtenir un quatrieme devis avant l'AG extraordinaire de mars.",
      "", "Resolution 15 : travaux de mise aux normes de l'ascenseur, budget 18 500 euros."]),
    ("pdf", "Devis chaudière — Thermique Paris Est", "Devis", "2026-09-02", [0],
     ["THERMIQUE PARIS EST - Devis n. 2026-0912", "Fourniture et pose chaudiere gaz a condensation 220 kW",
      "Depose et evacuation de la chaudiere fioul existante et de la cuve", "Tubage du conduit de fumee",
      "Montant total TTC : 68 000 euros", "Validite du devis : 3 mois", "Eligible aux aides CEE."]),
    ("docx", "Devis ravalement — Façades Durand", "Devis", "2026-08-28", [1],
     ["FACADES DURAND - Devis ravalement", "Echafaudage sur la facade rue, 6 niveaux.",
      "Nettoyage de la pierre de taille, rejointoiement, traitement hydrofuge.",
      "Reprise des balcons en fer forge et peinture des garde-corps.",
      "Montant total TTC : 152 300 euros. Duree des travaux : 14 semaines."]),
    ("docx", "Devis ravalement — Bâtiment Rénov", "Devis", "2026-09-10", [1],
     ["BATIMENT RENOV - Proposition de ravalement",
      "Facade rue : nettoyage par micro-gommage, reprise ponctuelle des pierres.",
      "Option isolation thermique non retenue (facade haussmannienne protegee).",
      "Montant total TTC : 138 900 euros."]),
    ("pdf", "Rapport d'audit énergétique", "Diagnostic", "2026-06-20", [2, 0, 3],
     ["AUDIT ENERGETIQUE - 4 rue de Moscou", "Etiquette energie actuelle : E (268 kWh/m2/an)",
      "Poste principal de deperdition : toiture et combles non isoles (30 %).",
      "Scenario 1 : isolation des combles + remplacement chaudiere -> etiquette C.",
      "Economie estimee sur les charges de chauffage : 35 %."]),
    ("pdf", "Contrat d'entretien ascenseur — Otis", "Contrat", "2025-12-01", [4],
     ["CONTRAT D'ENTRETIEN ASCENSEUR", "Visite mensuelle, depannage 7j/7 sous 4 heures.",
      "Prix annuel : 2 850 euros HT, revisable selon indice.", "Echeance : 30 novembre 2027."]),
    ("docx", "Attestation d'assurance immeuble 2026", "Assurance", "2026-01-05", [],
     ["Attestation d'assurance multirisque immeuble", "Copropriete 4 rue de Moscou 91300 Massy",
      "Garanties : incendie, degat des eaux, responsabilite civile du syndicat.",
      "Periode de validite : du 1er janvier au 31 decembre 2026."]),
]


def run():
    if os.path.exists(database.DB_PATH):
        os.remove(database.DB_PATH)
    database.init_db()
    conn = database.connect()
    for email, name, lot, role in MEMBRES:
        conn.execute("INSERT INTO users (email, name, lot, role) VALUES (?, ?, ?, ?)", (email, name, lot, role))
    ch_ids = []
    for t, cat, st, prevu, engage, debut, ech, resp, desc in CHANTIERS:
        cur = conn.execute("""INSERT INTO chantiers (title, category, status, budget_prevu, budget_engage,
                              date_debut, date_echeance, responsable_id, description)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                           (t, cat, st, prevu, engage, debut, ech, resp, desc))
        ch_ids.append(cur.lastrowid)
    for kind, title, cat, ddate, links, content in DOCS:
        data = make_pdf(content) if kind == "pdf" else make_docx(content)
        fname = title.replace(" — ", "_").replace(" ", "_").replace("'", "") + "." + kind
        text = extract_text(data, fname)
        key = storage.save(data, fname, None)
        cur = conn.execute("""INSERT INTO documents (title, category, doc_date, filename, storage_key, size,
                              has_text, uploaded_by, mime) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                           (title, cat, ddate, fname, key, len(data), 1 if text else 0,
                            "application/pdf" if kind == "pdf" else
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
        database.index_document(conn, cur.lastrowid, title, text)
        for i in links:
            conn.execute("INSERT INTO chantier_documents VALUES (?, ?)", (ch_ids[i], cur.lastrowid))
    # Dossiers et photos de démonstration
    def folder(name, parent=None):
        return conn.execute("INSERT INTO folders (name, parent_id, created_by) VALUES (?, ?, 1)", (name, parent)).lastrowid
    f_ag = folder("Assemblées générales"); f_ag26 = folder("2026", f_ag)
    f_contrats = folder("Contrats"); f_photos = folder("Photos"); f_facade = folder("Façade", f_photos)
    folder("Chaufferie", f_photos); folder("Diagnostics")
    placement = {"PV d'AG": f_ag26, "Contrat": f_contrats, "Assurance": f_contrats}
    for cat, fid in placement.items():
        conn.execute("UPDATE documents SET folder_id = ? WHERE category = ?", (fid, cat))
    from PIL import Image, ImageDraw
    from services import make_thumbnail, thumbnail_key
    colors = [((196, 170, 132), "Facade cote rue"), ((150, 160, 172), "Balcon 2e etage"),
              ((176, 120, 92), "Fissure pierre"), ((120, 140, 110), "Corniche"), ((200, 190, 170), "Porche")]
    for i, (rgb, label) in enumerate(colors):
        im = Image.new("RGB", (1600, 1200), rgb)
        d = ImageDraw.Draw(im)
        for k in range(0, 1600, 160):
            d.rectangle([k, 0, k + 70, 1200], fill=tuple(max(0, c - 25) for c in rgb))
        d.rectangle([520, 380, 1080, 820], outline=(255, 255, 255), width=14)
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=85); data = buf.getvalue()
        fname = f"IMG_20261028_{i:02d}.jpg"
        key = storage.save(data, fname, "image/jpeg")
        cur = conn.execute("""INSERT INTO documents (title, category, doc_date, filename, storage_key, size, has_text,
                              uploaded_by, mime, folder_id) VALUES (?, 'Photo', '2026-10-28', ?, ?, ?, 0, 1, 'image/jpeg', ?)""",
                           (label.replace("cote", "côté").replace("etage", "étage"), fname, key, len(data), f_facade))
        database.index_document(conn, cur.lastrowid, label, "")
        conn.execute("INSERT INTO chantier_documents VALUES (?, ?)", (ch_ids[1], cur.lastrowid))
        if i < 3:  # les autres sont créées au premier affichage, comme pour les photos déjà déposées
            storage.put(thumbnail_key(cur.lastrowid), make_thumbnail(data), "image/jpeg")
    conn.execute("INSERT INTO journal (user_id, action, detail) VALUES (1, 'Base de démonstration créée', '')")
    conn.commit()
    conn.close()
    print("Démo prête :", database.DB_PATH)
    print("Connectez-vous avec admin@copro-demo.fr (le lien s'affiche à l'écran en mode test).")


if __name__ == "__main__":
    with app.app_context():
        run()
