# 📡 Radar Stages

Surveille toutes les 5 minutes (boîtes ★) et toutes les 15 minutes (le reste) les sites carrières de ~240 banques, boutiques M&A, fonds de PE / dette privée et investisseurs institutionnels, et t'envoie une notification Telegram dès qu'un **stage ciblé** (M&A, PE, dette privée, spring week, off-cycle…) est publié.

- 🔥 **Notification instantanée** pour chaque nouvelle offre ciblée
- ☀️ **Récap chaque matin à 7h** : nouveautés des dernières 24h + deadlines proches + springs attendues + sources en panne
- 📊 **Tableau de bord en ligne** : Priorités, Nouveautés (par date de publication réelle), Tableau façon TrackR, Springs 2027 attendues, Pages étudiantes surveillées, Calendrier, suivi de tes candidatures
- ✅ **Éligibilité** : chaque offre ciblée est lue (année de diplôme demandée, dates, langues, visa…) et marquée Éligible / À vérifier / Non éligible selon ton profil (`config.json` → `profile`)
- 📄 **Pages étudiantes** : ~35 pages « Students & Graduates » relues à chaque scan, alerte Telegram dès qu'une phrase sur les candidatures change (`pages.csv`)
- 💸 **0 €** : tourne gratuitement sur GitHub (pas besoin que ton Mac soit allumé)

---

## Installation (≈ 20 minutes, une seule fois)

### Étape 1 — Créer ton bot Telegram

1. Installe Telegram sur ton téléphone et crée un compte (si ce n'est pas déjà fait).
2. Dans la recherche Telegram, tape **@BotFather** (badge bleu officiel) et ouvre la conversation.
3. Envoie `/newbot`, puis :
   - un nom, par ex. `Radar Stages`
   - un identifiant qui finit par `bot`, par ex. `radar_stages_adrien_bot`
4. BotFather te répond avec un **token** du genre `7123456789:AAH...`. Garde-le pour toi : c'est la clé de ton bot.
5. Clique sur le lien de ton bot (`t.me/radar_stages_adrien_bot`) et appuie sur **Démarrer**.
6. Dans le Terminal, va dans le dossier du projet et lance (remplace par ton token) :
   ```bash
   cd "$HOME/Desktop/Master in FI/Career Center/radar-stages"
   python3 -m radar telegram 7123456789:AAH...
   ```
   Tu reçois « ✅ Radar Stages est bien connecté » sur Telegram, et le Terminal affiche ton **TELEGRAM_CHAT_ID** (un nombre). Note-le.

### Étape 2 — Mettre le projet sur GitHub

1. Crée un compte gratuit sur **github.com**.
2. Installe **GitHub Desktop** (desktop.github.com) et connecte-toi avec ce compte.
3. Dans GitHub Desktop : *File → Add Local Repository…* → choisis le dossier `radar-stages`. GitHub Desktop dit que ce n'est pas encore un dépôt : clique sur **create a repository**, laisse les options par défaut, puis **Create Repository**.
4. Clique sur **Publish repository** → **décoche « Keep this code private »** (public = minutes illimitées + tableau de bord gratuit) → *Publish*.

### Étape 3 — Donner les clés Telegram à GitHub (en secret)

Sur github.com, dans ton dépôt `radar-stages` :
1. **Settings → Secrets and variables → Actions → New repository secret**
2. Nom `TELEGRAM_BOT_TOKEN` → valeur : ton token → *Add secret*
3. Nom `TELEGRAM_CHAT_ID` → valeur : ton chat id → *Add secret*

Les secrets ne sont jamais visibles publiquement, même si le dépôt est public.

### Étape 4 — Activer le tableau de bord

**Settings → Pages** → *Source* : « Deploy from a branch » → Branch : `main` / dossier `/docs` → *Save*.
Ton tableau de bord sera à l'adresse `https://TON-PSEUDO.github.io/radar-stages/` (le lien est aussi dans chaque message Telegram).

### Étape 5 — Lancer le radar

Onglet **Actions** → si GitHub le demande, clique *I understand my workflows, go ahead and enable them* → **Radar Stages** → **Run workflow**.

Après ~2 minutes tu reçois le message « 📡 Radar Stages activé ! » avec les meilleures offres déjà ouvertes. Ensuite, tout est automatique.

---

## Utilisation au quotidien

| Je veux… | Comment |
|---|---|
| Ajouter / retirer une boîte | Modifier `companies.csv` (Excel/Numbers ou directement sur github.com). Une ligne `source = manuel` apparaît dans le tableau de bord mais n'est pas scannée. |
| Ajouter une spring / un programme à surveiller | Ajouter une ligne à `programmes.csv` (date d'ouverture de l'an dernier, date attendue, deadline `closes` si connue, mots-clés). Rappel le matin quand l'ouverture approche et à J-14 → J-0 de la deadline. |
| Changer l'heure du récap | `config.json` → `digest_hour` |
| Mettre à jour mon profil (année de diplôme, dispo, langues) | `config.json` → `profile` |
| Surveiller une nouvelle page étudiants | Ajouter une ligne à `pages.csv` (`company,label,url`) |
| Être notifié aussi pour les stages « hors cible » | `config.json` → `"instant_levels": ["A", "B"]` |
| Lancer un scan tout de suite | github.com → Actions → Radar Stages → Run workflow |
| Tester en local | `python3 -m radar test` (toutes les sources) ou `python3 -m radar test Lazard KKR` |

**Ciblée (A)** = stage/spring/off-cycle en M&A, IB, PE, dette privée, restructuring, ECM/DCM, infra, immobilier… ou tout stage « métier » chez une boutique / un fonds. **Autre (B)** = stage non ciblé (tech, risques, audit, sales & trading, events…) : visible dans le tableau de bord et le récap du matin, sans notification instantanée.

## Sources

- **Sites carrières des boîtes** (`companies.csv`) : Workday, Oracle, Greenhouse, Oleeo, SmartRecruiters…
- **Sources découvertes automatiquement** : le radar suit les liens « Apply » des pages étudiants et de YourFinanceJob, teste les plateformes qu'il ne connaît pas encore et les ajoute seul (prévenu sur Telegram).
- **YourFinanceJob** (agrégateur public, ~1 600 offres de ~280 boîtes) : complète ce que les sites des boîtes ne montrent pas.
- **TrackR** (frise publique des springs, relue chaque jour) et **L3vlUp** (springs ouvertes + deadlines, relu toutes les 6 h) pour l'onglet Springs.

## Rythme des scans

- toutes les 5 min : les boîtes ★ (mode rapide)
- toutes les ~15 min : toutes les sources, pages étudiants, découverte de sources
- toutes les heures : lecture intégrale des grands sites (JPMorgan, Citi…) pour ne rien rater
- une offre qui disparaît est vérifiée en ouvrant son lien : « Fermée » dès qu'elle n'existe plus

## Comment ça marche

`radar/sources.py` sait lire les plateformes de recrutement les plus utilisées en finance (Workday, Oracle, Greenhouse, Lever, Oleeo/tal.net, SmartRecruiters, Recruitee, Teamtailor, Ashby, Pinpoint, Workable, iCIMS, Talentsoft…) plus les API maison de Goldman Sachs et Deutsche Bank. Pour les boîtes sans plateforme, le mode `watch` surveille le texte de la page carrière.

Chaque scan compare avec `data/state.json` : une offre jamais vue = notification. Une offre absente 3 scans de suite = marquée « fermée ». Une source qui renvoie soudain moitié moins d'offres est ignorée pour ce scan (protection contre les pages mal chargées).

Si une boîte change de site, elle apparaît « en panne » dans le récap du matin et dans l'onglet *Boîtes* : il suffit de corriger sa ligne dans `companies.csv` (ou de demander à Claude).

**Limites connues** : BNP Paribas, Société Générale, Natixis, UBS et quelques autres bloquent la lecture automatique ou n'ont pas de plateforme lisible → ils sont listés « à la main » dans l'onglet *Boîtes*. Pour ces boîtes, crée des alertes e-mail sur leur site et sur JobTeaser.
