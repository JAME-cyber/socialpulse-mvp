# SocialPulse — Brief de Repositionnement Conformité (v2 — révisé après contre-analyse)

> **Audit Gardien des Normes × GPT-5.5 + contre-analyse adversariale · 26 juin 2026**
> **Pipeline 3-étages : génération → audit → contre-audit. Coût total : $0.26 · 3 min.**

---

## ⚠️ Verdict révisé : **OUI MAIS** (et non « NON » comme la première passe le suggérait)

La contre-analyse adversariale a fait **tomper 14 des 16 FATAL initiaux au rang de MAJOR**. SocialPulse n'est pas le blocage juridique que le premier audit décrivait — c'est un produit **mal encadré**, déployable **sous conditions strictes**, sans pivot produit obligatoire.

### Tableau récapitulatif des passes

| Passe | Verdict | FATAL | Coût |
|-------|---------|-------|------|
| 1. Audit seul | 6 RED / 1 AMBER | 16 | $0.11 |
| 2. + Contre-analyse | 6 AMBER | **2 maintenus** + 14 nuancés en MAJOR | +$0.15 |
| **Total** | **OUI MAIS** | **2 vrais blockers** | $0.26 |

---

## 🎯 Les 2 seuls vrais FATAL (confirmés par la défense elle-même)

La contre-analyse les a attaqués et a **échoué**. Ce sont les blockers réels :

### 🔴 FATAL #1 — La mention email `art. L.223-1` est objectivement fausse
- **Confiance : 0.98** (l'avocat concède lui-même « grievance la plus solide »)
- **Le droit :** Code conso L.223-1 = **Bloctel / démarchage téléphonique**, pas l'email. La mention affichée à des prospects est juridiquement inexacte et trompeuse.
- **Fix :** 5 minutes. Remplacer par `CPCE art. L.34-5 + notice RGPD + opt-out`. Blocker trivial.

### 🔴 FATAL #2 — Le SMS cold B2C sans consentement
- **La défense est « faible »** (GPT-5.5 le concède).
- **Le droit :** SMS = ePrivacy + CPCE L.34-5, opt-in obligatoire pour personnes physiques. Le `STOP=désinscription` ne rend pas licite l'envoi initial.
- **Fix :** Couper le canal SMS, ou le réserver aux PM avec preuve de consentement. Blocker simple.

→ **Ces 2 fixes = ~1 jour de dev. Ils lèvent tous les vrais FATAL.**

---

## ✅ Ce que l'audit initial a EXAGÉRÉ (la défense a eu raison)

Ces 14 ex-FATAL sont en réalité des **MAJOR** (à encadrer, pas bloquants) :

| Ex-FATAL surclassé | Vérité juridique | Statut réel |
|---|---|---|
| Maquette BUILDER au nom du commerce (CPI L713-2) | L713-2 vise l'usage « dans la vie des affaires ». Une **maquette interne non publiée** ne constitue pas un usage public. | MAJOR |
| Cold email B2B illicite par principe | Doctrine CNIL (délib. 2013-367) : opt-out suffisant en B2B quand offre liée à la fonction. Le STOP existant marche pour PM. | MAJOR |
| OSM/Overpass illicite | ODbL **autorise** la prospection commerciale avec attribution. SCOUT sur OSM = OK. | GREEN (avec attribution) |
| Scraping Google Maps = pénal | Risque **contractuel** (ToS Google) + CPI L342-1 (droit sui generis bases de données), pas pénal. | MAJOR |
| DM IG/LinkedIn automatisés | Entrent dans ePrivacy « courrier électronique » mais régime nuancé selon contexte, pas automatiquement opt-in strict. | MAJOR |
| Score lead 0-100 = art.22 RGPD | Profilage oui (art.4.4) mais **pas art.22** (pas de décision aux effets juridiques). À documenter, pas interdit. | MAJOR |

---

## 🟡 La condition structurelle qui reste vraie : le classifieur PM/EI

Même après contre-analyse, **un point tient** (confiance 0.97) :

> **Un entrepreneur individuel / artisan / commerçant personne physique = donnée personnelle RGPD.** La défense a nuancé (« un gérant de SARL reste pro pour sa fonction ») mais n'a pas invalidé le principe.

→ Le manque de classification **personne morale / entrepreneur individuel** reste le défaut racine. C'est le **seul fix structurel** vraiment important (via API Sirene `forme_juridique`). Une fois en place :
- Les PM → régime B2B opt-out (légal en l'état)
- Les EI → à traiter comme données perso (opt-in ou intérêt légitime documenté)

---

## 📋 Plan d'action RÉVISÉ (allégé vs v1)

### 🔴 Immédiat (1 jour) — lève les 2 vrais FATAL
1. **Corriger la mention CHECKER** : `L.223-1` → `CPCE L.34-5 + notice RGPD`
2. **Couper le SMS cold** (ou restreindre aux PM avec preuve)

### 🟠 Court terme (1 semaine) — le fix structurel
3. **Implémenter le classifieur PM/EI** via API Sirene `forme_juridique`. Le seul fix à fort ratio impact/effort.
4. **Brancher le WORM existant** sur la preuve de consentement + date/source/finalité.

### 🟢 Optionnel (pas obligatoire) — réduction de risque
5. LIA (Legitimate Interest Assessment) documenté par catégorie de lead
6. Réécrire CHECKER pour valider base légale (pas juste opt-out)
7. **Le pivot inbound** : ce n'est plus une « obligation », c'est une **optimisation de risque**. Recommandé mais tu peux légalement rester outbound B2B encadré.

---

## 🎭 Ce que ça change pour ta décision go/no-go

| Question | Réponse révisée |
|---|---|
| SocialPulse est-il déployable en l'état ? | **Non** — mais seulement à cause de 2 fixes triviaux (mention + SMS) |
| Le pivot inbound est-il obligatoire ? | **Non** — c'est une optimisation, pas une condition de légalité |
| Le business model outbound est-il mort ? | **Non** — le B2B PM en opt-out reste légal (CNIL délib. 2013-367) |
| Quelle est la vraie urgence ? | 1 jour de dev (2 fixes) + 1 semaine (classifieur) |

---

## 🧠 Leçon méthodologique (générale)

L'audit seul a surqualifié 14 FATAL en MAJOR. Sans contre-analyse, j'aurais recommandé un pivot produit lourd qui **n'était pas juridiquement obligatoire**. 

**Règle intégrée au factory :** tout audit doit maintenant passer par une contre-analyse adversariale. Coût ×1.5 mais verdict fiable. Le système complet (3-étages) est désormais dans `~/usecases-factory/generate_usecases.py`.

---

## 📊 Synthèse comparative

| Critère | v1 (audit seul) | **v2 (audit + contre)** |
|---|---|---|
| Verdict | 6 RED, NON déployable | **6 AMBER, OUI MAIS** |
| FATAL réels | 16 (surclassés) | **2** |
| Pivot inbound | « Obligation » | « Optimisation recommandée » |
| Effort de mise en conformité | Lourd (pivot produit) | **Léger** (2 fixes + 1 classifieur) |
| Confiance du verdict | Médiocre (mono-passe) | **Forte** (deux passes adversariales) |

---

## 📁 Fichiers de référence

- `/tmp/socialpulse_audit_7agents.json` — audit initial (47 issues)
- `/tmp/socialpulse_contre_analyse.json` — contre-analyse (16 défenses + 8 vérifications juridiques)
- `~/usecases-factory/generate_usecases.py` — pipeline 3-étages (génération → audit → contre-audit)

---

*Généré par le pipeline Usecases Factory 3-étages · Gardien des Normes + Avocat du diable × GPT-5.5 · ancré dans le code réel de `socialpulse-mvp/annemasse-agency/`*
