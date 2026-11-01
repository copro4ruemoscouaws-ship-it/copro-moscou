"""Services : extraction de texte, stockage des fichiers (disque ou S3), envoi d'emails."""
import io
import os
import uuid

# ---------------------------------------------------------------- Extraction

def extract_text(data: bytes, filename: str) -> str:
    """Renvoie le texte d'un PDF, Word (.docx) ou fichier texte. Chaîne vide sinon."""
    ext = os.path.splitext(filename.lower())[1]
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        if ext == ".docx":
            import docx
            d = docx.Document(io.BytesIO(data))
            chunks = [p.text for p in d.paragraphs]
            for table in d.tables:
                for row in table.rows:
                    chunks.append(" | ".join(c.text for c in row.cells))
            return "\n".join(chunks).strip()
        if ext in (".txt", ".md", ".csv"):
            return data.decode("utf-8", errors="ignore").strip()
    except Exception as exc:  # fichier corrompu ou protégé : on garde le document sans texte
        print(f"[extraction] {filename}: {exc}")
    return ""


# ---------------------------------------------------------------- Stockage

def content_disposition(filename, as_attachment=False):
    """En-tête de téléchargement compatible avec les accents (RFC 6266 / 5987).

    S3 n'accepte que des caractères ASCII : on donne un nom sans accents pour les
    anciens navigateurs, et le vrai nom encodé dans filename* pour les autres.
    """
    import unicodedata
    from urllib.parse import quote
    plain = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    plain = "".join(ch for ch in plain if ch not in '"\\' and 32 <= ord(ch) < 127).strip() or "document"
    kind = "attachment" if as_attachment else "inline"
    return f"{kind}; filename=\"{plain}\"; filename*=UTF-8''{quote(filename, safe='')}"


class LocalStorage:
    """Fichiers sur le disque du serveur (développement, ou petit serveur sans S3)."""

    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def save(self, data: bytes, filename: str, mime: str) -> str:
        key = f"{uuid.uuid4().hex}{os.path.splitext(filename)[1].lower()}"
        with open(os.path.join(self.root, key), "wb") as f:
            f.write(data)
        return key

    def path(self, key):
        return os.path.join(self.root, key)

    def get(self, key):
        """Contenu d'un fichier, ou None s'il n'existe pas."""
        try:
            with open(self.path(key), "rb") as f:
                return f.read()
        except (FileNotFoundError, IsADirectoryError):
            return None

    def put(self, key, data: bytes, mime: str):
        os.makedirs(os.path.dirname(self.path(key)) or self.root, exist_ok=True)
        with open(self.path(key), "wb") as f:
            f.write(data)

    def delete(self, key):
        try:
            os.remove(self.path(key))
        except FileNotFoundError:
            pass

    def download_url(self, key, filename, as_attachment=False):
        return None  # l'application sert le fichier elle-même


class S3Storage:
    """Fichiers dans un bucket S3 privé ; téléchargement par lien temporaire signé."""

    def __init__(self, bucket, region):
        import boto3
        self.bucket = bucket
        self.s3 = boto3.client("s3", region_name=region)

    def save(self, data: bytes, filename: str, mime: str) -> str:
        key = f"documents/{uuid.uuid4().hex}{os.path.splitext(filename)[1].lower()}"
        self.s3.put_object(
            Bucket=self.bucket, Key=key, Body=data,
            ContentType=mime or "application/octet-stream",
            ServerSideEncryption="AES256",
        )
        return key

    def delete(self, key):
        self.s3.delete_object(Bucket=self.bucket, Key=key)

    def get(self, key):
        """Contenu d'un objet, ou None s'il n'existe pas.

        Sans le droit ListBucket, S3 répond « accès refusé » plutôt que « introuvable »
        pour un objet absent : toute erreur est donc traitée comme une absence.
        """
        from botocore.exceptions import ClientError
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError:
            return None

    def put(self, key, data: bytes, mime: str):
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data,
                           ContentType=mime or "application/octet-stream",
                           ServerSideEncryption="AES256")

    def download_url(self, key, filename, as_attachment=False):
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key,
                    "ResponseContentDisposition": content_disposition(filename, as_attachment)},
            ExpiresIn=300,
        )


IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def is_image(filename):
    return os.path.splitext((filename or "").lower())[1] in IMAGE_EXT


def thumbnail_key(doc_id):
    # Sous documents/ : couvert par la politique IAM de copro-app, sans droit supplémentaire.
    return f"documents/vignettes/{doc_id}.jpg"


def make_thumbnail(data: bytes, size=480) -> bytes:
    """Miniature JPEG carrée-ish, orientée correctement (photos de téléphone)."""
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(data)) as img:
        if img.format == "JPEG":
            img.draft("RGB", (size * 2, size * 2))   # décode en basse résolution : peu de mémoire
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            background = Image.new("RGB", img.size, (248, 244, 234))
            rgba = img.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        img.thumbnail((size, size))
        out = io.BytesIO()
        img.convert("RGB").save(out, "JPEG", quality=80, optimize=True)
        return out.getvalue()


def make_storage(config):
    if config.get("STORAGE") == "s3":
        return S3Storage(config["S3_BUCKET"], config["AWS_REGION"])
    return LocalStorage(config["UPLOAD_DIR"])


# ---------------------------------------------------------------- Emails

def send_login_email(config, to_email, name, link, code):
    subject = f"Votre code de connexion : {code} — Copropriété 4 rue de Moscou"
    body = (
        f"Bonjour {name},\n\n"
        f"Pour vous connecter à l'espace copropriété, cliquez sur ce lien :\n\n{link}\n\n"
        f"Ou saisissez ce code sur la page de connexion :  {code}\n\n"
        f"Le lien et le code sont valables 15 minutes et ne servent qu'une fois.\n"
        f"Si vous n'avez pas demandé à vous connecter, ignorez ce message.\n"
    )
    if config.get("MAIL") == "ses":
        import boto3
        from email.utils import formataddr, parseaddr
        # Le nom affiché contient des accents : il doit être encodé (RFC 2047) pour SES.
        display, address = parseaddr(config["MAIL_FROM"])
        source = formataddr((display, address), charset="utf-8") if display else address
        ses = boto3.client("ses", region_name=config["AWS_REGION"])
        ses.send_email(
            Source=source,
            Destination={"ToAddresses": [to_email]},
            Message={"Subject": {"Data": subject, "Charset": "UTF-8"},
                     "Body": {"Text": {"Data": body, "Charset": "UTF-8"}}},
        )
    else:
        print(f"\n[email simulé] À : {to_email}\n{body}", flush=True)
