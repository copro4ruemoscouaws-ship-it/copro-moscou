# Espace copropriété — 4 rue de Moscou

Site privé pour les 18 membres du conseil syndical : documents avec recherche dans le contenu des PDF et Word, chantiers (chauffage, façade, ascenseur…) liés à leurs documents, tableau de bord, connexion par lien email sans mot de passe.

## Fonctionnalités

- **Téléphone, tablette et ordinateur** : l'interface s'adapte à la taille de l'écran (menu compact, boutons faciles à toucher, chantiers sur 1, 2 ou 5 colonnes). Depuis un téléphone, on peut déposer une photo d'un document prise sur le moment. Le site peut être ajouté à l'écran d'accueil du téléphone comme une application (icône « 4 »).

- **Documents** : dépôt de plusieurs fichiers à la fois (PDF, Word, Excel, photos), catégorie, date, liaison à un ou plusieurs chantiers.
- **Dossiers et sous-dossiers** : les administrateurs créent, renomment, déplacent et suppriment les dossiers (supprimer un dossier ne supprime jamais les documents : ils remontent d'un niveau). Tous les membres choisissent le dossier au dépôt et peuvent déplacer des documents, un par un depuis leur fiche ou plusieurs à la fois en les cochant. Les documents sans dossier apparaissent dans « Non classés ».
- **Photos** : affichage en vignettes dans chaque dossier et chaque chantier, visionneuse plein écran (flèches du clavier, ou glisser du doigt sur téléphone). Les miniatures sont créées au dépôt, ou au premier affichage pour les photos plus anciennes, et gardées dans S3 (`documents/vignettes/`).
- **Recherche** : dans le titre et le contenu des PDF/Word, avec extraits surlignés. Insensible aux accents (« electricite » trouve « électricité »), recherche par début de mot (« chauff » trouve chauffage, chaufferie), expression exacte entre guillemets (`"article 25"`). Filtres par catégorie et par chantier.
- **Chantiers** : catégorie, étape (Idée → Devis en cours → Voté en AG → En cours → Terminé), budget prévu et engagé, échéance, responsable, notes de suivi, documents liés.
- **Tableau de bord** : nombre de chantiers par étape, chantiers actifs avec avancement budgétaire, budget global, prochaines échéances (en rouge si dépassées), derniers documents.
- **Accès** : connexion par lien email valable 15 minutes et à usage unique. Seules les adresses enregistrées peuvent se connecter. Deux rôles : administrateur (gère les membres, supprime) et membre (consulte, dépose, modifie).
- **Journal d'activité** visible des administrateurs : qui a ajouté, modifié ou supprimé quoi.

Limite : les PDF scannés (photos de pages) n'ont pas de texte ; ils restent trouvables par leur titre. Une reconnaissance de texte (Amazon Textract) pourra être ajoutée plus tard si besoin.

## Pour les membres : se connecter et installer le site sur son téléphone

**Se connecter**
1. Aller sur **4ruedemoscou.fr** et saisir son adresse email.
2. Un email arrive avec un **lien** et un **code à 6 chiffres**, valables 15 minutes.
3. Cliquer sur le lien, **ou** taper le code sur la page de connexion. Le code est pratique quand on lit ses emails sur un appareil et qu'on se connecte sur un autre (téléphone et tablette), ou depuis l'icône sur l'écran d'accueil.
4. On reste connecté 30 jours sur cet appareil.

**Ajouter le site à l'écran d'accueil (comme une application)**
- **iPhone / iPad** (Safari) : bouton Partager □↑ → « Sur l'écran d'accueil ».
- **Android** (Chrome) : menu ⋮ → « Ajouter à l'écran d'accueil » ou « Installer l'application ».

Une icône « 4 » apparaît ; le site s'ouvre en plein écran. À la première ouverture depuis l'icône, se connecter avec le **code** reçu par email.

## Essayer en local (5 minutes)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt reportlab
python demo_data.py                       # base de démo avec chantiers et documents fictifs
DB_PATH=data/demo.db flask --app app run  # puis ouvrir http://localhost:5000
```

Se connecter avec `admin@copro-demo.fr` : en mode test, le lien de connexion s'affiche directement à l'écran au lieu d'être envoyé par email.

## Architecture AWS (région Stockholm, eu-north-1)

Les nouveaux comptes AWS européens sont rattachés à la région Stockholm : c'est dans l'Union européenne, le RGPD s'applique pleinement.

| Élément | Service | Rôle |
|---|---|---|
| Serveur | Lightsail, Ubuntu 24.04, plan 1 Go de mémoire | Site + base SQLite |
| Documents | S3, bucket `copro-4moscou-documents` (privé, chiffré, versions) | Fichiers + sauvegardes nocturnes de la base |
| Emails | SES, domaine `4ruedemoscou.fr`, plan Essentials | Envoi des liens de connexion |
| Domaine | OVHcloud, `4ruedemoscou.fr` | Adresse du site, zone DNS |
| HTTPS | Let's Encrypt (certbot) | Certificat gratuit |

Coût attendu : environ 6 à 10 € par mois pour AWS, plus le domaine (7,79 € HT par an). Vérifiez les tarifs à jour.

## Mise en ligne, étape par étape

Les étapes 1 à 4 ont été faites le 28 octobre 2026 ; elles sont décrites pour mémoire.

### 1. Compte et budget AWS ✅
- Compte créé (plan gratuit jusqu'au 28 avril 2027 : aucune facturation possible tant qu'on ne passe pas au plan payant).
- Budget `copro-mensuel` à 15 $ avec alertes email.
- **À faire** : double authentification sur le profil AWS (profile.aws.amazon.com → Sécurité) et sur la boîte Gmail du compte.

### 2. Bucket S3 ✅
- `copro-4moscou-documents`, Stockholm, accès public bloqué, gestion des versions activée.
- Règle `nettoyage` : anciennes versions supprimées après 90 jours, chargements incomplets après 7 jours.

### 3. Utilisateur IAM de l'application ✅ (à compléter)
- `copro-app`, sans accès console, politique en ligne `copro-app-documents` (accès S3).
- **À faire** : remplacer la politique par le contenu complet de `deploy/iam-policy.json`, qui ajoute l'envoi d'emails SES depuis `ne-pas-repondre@4ruedemoscou.fr`.
- **À faire au moment de l'installation** : créer une clé d'accès (*Application exécutée en dehors d'AWS*) et la coller directement dans `/etc/copro.env` sur le serveur. Ne jamais l'envoyer par email ou chat.

### 4. Emails (SES) ✅ (validation en cours)
- Identités : domaine `4ruedemoscou.fr` (3 enregistrements CNAME DKIM ajoutés chez OVH) et adresse `copro4ruemoscou.aws@gmail.com`.
- Entrée DMARC chez OVH : TXT `_dmarc` = `v=DMARC1; p=none;`
- SES démarre en « bac à sable » : envoi uniquement vers des adresses vérifiées. Une fois le site en ligne, demander l'accès production (SES → *Configurer* → *Demander un accès à la production*, usage : emails transactionnels de connexion, environ 50 par mois, 18 destinataires connus).

### 5. Serveur Lightsail
1. Lightsail → *Créer une instance* → région **Stockholm**, *Linux/Unix*, *Système d'exploitation uniquement* → **Ubuntu 24.04**, plan 1 Go.
2. *Réseau* : attacher une **IP statique**, ouvrir le port **443 (HTTPS)**.
3. Chez OVH, zone DNS de `4ruedemoscou.fr` : remplacer les enregistrements `A` de la racine (`@`) et de `www` (actuellement 213.186.33.5, page d'attente OVH) par l'IP statique. Garder les enregistrements MX, DKIM et DMARC.
4. Activer les *snapshots automatiques* de l'instance (sauvegarde complète quotidienne).

### 6. Installation
Depuis votre ordinateur :
```bash
scp -r copro-moscou ubuntu@IP_DU_SERVEUR:~
ssh ubuntu@IP_DU_SERVEUR
cd copro-moscou && sudo bash deploy/install.sh
sudo nano /etc/copro.env          # coller les deux valeurs de la clé AWS de copro-app
sudo bash deploy/install.sh       # relancer une fois le fichier complété
sudo certbot --nginx -d 4ruedemoscou.fr -d www.4ruedemoscou.fr
```

Créer le premier administrateur :
```bash
sudo -u copro bash -c 'set -a; source /etc/copro.env; cd /srv/copro/app; /srv/copro/venv/bin/flask --app app add-admin'
```
Ensuite, tout se fait depuis le site : page **Membres** → ajouter les 17 autres membres.

### 7. Vérifications
- Se connecter avec l'adresse administrateur : le lien arrive par email (et ne s'affiche **pas** à l'écran, car `DEV_SHOW_LINK=0`).
- Déposer un PDF, chercher un mot de son contenu.
- Le lendemain, vérifier la présence d'un fichier dans `s3://…/sauvegardes/`.

## Mises à jour du site

Le code de référence est sur GitHub (dépôt privé `copro4ruemoscouaws-ship-it/copro-moscou`). Pour installer une nouvelle version sur le serveur :

1. Déposer l'archive `copro-moscou.zip` à la racine du bucket S3, puis créer un lien présigné d'une heure (Actions → Partager avec une URL présignée).
2. Dans le terminal du serveur (Lightsail → Connect using SSH) :
```bash
# Sauvegarde de la base avant toute mise à jour
sudo sqlite3 /srv/copro/data/copro.db ".backup '/srv/copro/data/copro-avant-maj.db'"
# Récupérer et installer la nouvelle version
cd ~ && curl -fSL -o copro.zip 'LIEN_PRÉSIGNÉ'
rm -rf ~/copro-moscou && unzip -q -o ~/copro.zip -d ~
sudo cp -r ~/copro-moscou/. /srv/copro/app/ && sudo chown -R copro:copro /srv/copro/app
sudo /srv/copro/venv/bin/pip install -q -r /srv/copro/app/requirements.txt
sudo systemctl restart copro && systemctl is-active copro
```
3. Supprimer l'archive du bucket.

La base de données est mise à niveau automatiquement au redémarrage, sans perte : les nouvelles colonnes et tables sont ajoutées, rien n'est effacé.

## Restaurer une sauvegarde
Télécharger le fichier voulu depuis la console S3 (dossier `sauvegardes/`), l'envoyer sur le serveur avec `scp`, puis :
```bash
gunzip copro-AAAA-MM-JJ.db.gz
sudo systemctl stop copro
sudo cp copro-AAAA-MM-JJ.db /srv/copro/data/copro.db && sudo chown copro:copro /srv/copro/data/copro.db
sudo systemctl start copro
```

## Sécurité et RGPD
- Site non indexé par les moteurs de recherche, tout le contenu derrière connexion.
- Liens de connexion à usage unique, stockés uniquement sous forme chiffrée (empreinte SHA-256).
- Protection contre les envois de formulaires frauduleux (jeton CSRF), cookies de session sécurisés en HTTPS.
- Documents dans un bucket S3 privé et chiffré ; téléchargement par lien temporaire de 5 minutes.
- Données hébergées dans l'Union européenne (région Stockholm).
- Pensez à informer les membres des données conservées (nom, email, lot) et à retirer l'accès d'un membre qui quitte le conseil (page Membres → « Retirer l'accès »).

## Fichiers du projet
```
app.py               Application (pages, connexion, droits)
db.py                Schéma SQLite et recherche plein texte
services.py          Extraction PDF/Word, stockage disque ou S3, emails SES
templates/, static/  Interface (app.js : visionneuse photos, sélection multiple)
demo_data.py         Données de démonstration
deploy/              Installation serveur, nginx, systemd, sauvegarde, droits IAM
```
