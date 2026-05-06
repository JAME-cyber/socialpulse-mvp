# SocialPulse Annemasse Agency 🚀

> **Le système de 7 agents IA qui prospecte automatiquement les PME locales**
> Adapté du [scénario @browomo](https://x.com/browomo/status/2051747188787523825) pour **Annemasse, Gaillard, Ville-la-Grand, Saint-Julien-en-Genevois** (Haute-Savoie, 74)

## 🎯 Ce que fait le système

```
1. SCOUT    → Découvre les PME via OpenStreetMap (gratuit) + Apify Google Maps (optionnel)
2. DIAGNOSER→ Score chaque lead (0-100) + diagnostic + cold message personnalisé
3. BUILDER  → Génère une landing page HTML/CSS personnalisée pour les top 5 leads
4. FILMER   → Crée une vidéo 10s verticale 1080×1920 (HyperFrame + GSAP)
5. PITCHER  → Prépare le cold message adapté au canal (email/SMS/Instagram/LinkedIn)
6. CHECKER  → Vérifie personnalisation, absence de buzzwords IA, opt-out
7. MOBILE   → Rapport des leads prêts à envoyer
```

## 💰 Comparaison des coûts

| Composant | Tweet (original) | Nous (open-source) |
|-----------|------------------|---------------------|
| Google Maps | Apify ($$$) | Overpass API (gratuit) + Apify (optionnel) |
| Landing pages | Lovable ($29/mois) | HTML local (gratuit) |
| Vidéos | Higgsfield ($$$) | HyperFrame + FFmpeg (gratuit, local) |
| LLM | Claude API ($480/mois) | OpenRouter DeepSeek (~$30/mois) |
| Calendly | Calendly Pro | Cal.com (open-source) / free tier |
| **Total** | **~$540/mois** | **~$30/mois** |

## 📊 Résultats du premier run

```
✅ 2 352 leads découverts (dont 1 700+ sans site web)
✅ 30 leads diagnostiqués et scorés
✅ 5 landing pages HTML générées
✅ 5 vidéos HyperFrame générées
✅ 5 cold messages prêts à envoyer
✅ Coût total: $0.00 (Overpass API = gratuit)
✅ 54 entrées dans le journal WORM
```

### Répartition des leads sans site web

| Secteur | Sans site web |
|---------|--------------|
| Restaurant | 999 |
| Salon de coiffure | 262 |
| Beauté | 93 |
| Boulangerie / Pâtisserie | 67 |
| Garage auto | 63 |
| Santé | 31 |
| Immobilier | 27 |
| Fleuriste | 25 |
| Sport | 21 |
| Kiné / Ostéopathe | 18 |

## 🏗️ Architecture

```
annemasse-agency/
├── orchestrator.py      # Orchestrateur + 7 agents
├── campaign.yaml        # Config campagne (secteurs, villes, scoring)
├── .env                 # Variables d'environnement
├── state/
│   ├── lead-queue.json  # Queue des leads (2352)
│   └── stats.json       # Stats globales
├── clients/             # Dossiers par lead
│   ├── as-de-pique/
│   │   ├── index.html   # Landing page
│   │   └── video.html   # Vidéo HyperFrame
│   └── ...
├── output/
│   ├── pitch-report.json    # Messages prêts à envoyer
│   └── mobile-report.json   # Leads approuvés
└── logs/
    └── journal-*.json   # Journal WORM (audit trail)
```

## 🚀 Usage

```bash
# Charger les variables d'environnement
export $(grep -v '^#' ~/.hermes/.env | xargs)

# Pipeline complet (7 agents)
python3 orchestrator.py --full

# Agent individuel
python3 orchestrator.py --agent scout
python3 orchestrator.py --agent diagnoser
python3 orchestrator.py --agent builder
python3 orchestrator.py --agent filmer
python3 orchestrator.py --agent pitcher
python3 orchestrator.py --agent checker
python3 orchestrator.py --agent mobile

# Statut
python3 orchestrator.py --status
```

## 🎨 Les 7 agents en détail

### 1. Scout (Discovery)
- **Source primaire**: OpenStreetMap via Overpass API (100% gratuit, pas de rate limit)
- **Source secondaire**: Apify Google Maps (optionnel, payant)
- **17 types de commerces** recherchés dans un bounding box couvrant Annemasse + Gaillard + Ville-la-Grand + Saint-Julien
- Filtre: pas de site web = meilleur prospect

### 2. Diagnoser (Scoring + Diagnosis)
- **Scoring déterministe** (0% LLM) pour tous les leads: website status, review gap, sector, location
- **LLM diagnosis** (OpenRouter/DeepSeek) seulement pour les top 5 leads
- **Template diagnosis** pour les 25 suivants
- Médiateur vérifie chaque scoring

### 3. Builder (Landing Pages)
- Génère une landing page HTML/CSS responsive par lead
- Couleurs adaptées au secteur (restaurant=ambre, coiffure=rose, etc.)
- Mobile-first, prête à déployer
- 100% local, pas de service externe

### 4. Filmer (Vidéos)
- HyperFrame: HTML + GSAP → vidéo animée 10s en 1080×1920
- 4 scènes: Hook → Card → Score → CTA
- Progress bar, animations GSAP
- Render via Puppeteer + FFmpeg (local, gratuit)

### 5. Pitcher (Cold Messages)
- Canal adapté au secteur:
  - 📧 Email: avocats, comptables, kinés
  - 📱 SMS: plombiers, garagistes
  - 📸 Instagram DM: restaurants, coiffeurs, fleuristes
  - 💼 LinkedIn: agents immobiliers

### 6. Checker (Quality Evals)
- Vérifie: personnalisation (nom du commerce mentionné)
- Détecte: marqueurs IA, buzzwords
- Vérifie: mention opt-out (email/SMS seulement)
- Vérifie: longueur du message

### 7. Mobile (Report)
- Génère le rapport des leads approuvés
- Prêt pour envoi manuel ou via API

## 🔒 Conformité

- **Journal WORM**: chaque action est hash-chainé (SHA-256)
- **Médiateur déterministe**: règles JsonLogic, 0% LLM dans les décisions critiques
- **Opt-out**: mention STOP dans les emails/SMS
- **RGPD**: prospection B2B, base légale intérêt légitime

## 📈 Potentiel de revenus

Avec 2 352 leads et ~1 700 sans site web:
- **Prix landing page**: 350€
- **Prix landing + vidéo**: 500€
- **Conversion conservative** (2%): 34 deals × 400€ = **13 600€/mois**
- **Coût**: ~30€/mois
- **Marge**: ~99.8%
