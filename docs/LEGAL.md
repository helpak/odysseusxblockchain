# Référence juridique et réglementaire

> **Statut.** Le fondateur indique avoir fait valider ces points par ses
> conseils juridiques dans la juridiction d'exploitation du projet. Cette page
> reste la référence des obligations à **maintenir** en exploitation (toute
> extension à de nouveaux pays, tout listing ou toute nouvelle forme de
> distribution rouvre l'analyse).

Ce document n'est pas un avis juridique. Il liste les sujets couverts par la
validation initiale et à surveiller en continu.

## 1. ODY est très probablement un instrument financier réglementé

Un jeton qui donne droit à une **part des revenus** d'un projet, dont la
communication insiste sur la **perspective de gain** liée au travail d'une
équipe, coche les critères classiques d'un titre financier :

- **France / UE** : un jeton avec droit à dividendes relève potentiellement des
  **titres financiers** (MiFID II / prospectus) et non du régime MiCA des
  utility tokens ; l'AMF requalifie facilement. Une offre au public sans
  prospectus approuvé est illégale.
- **USA** : test de Howey — investissement d'argent, entreprise commune,
  espérance de profit issue des efforts d'autrui. La SEC poursuit régulièrement
  des projets identiques (vente non enregistrée de securities).

Conséquences pratiques : pas de vente publique d'ODY, pas de listing, pas de
promesse de rendement, tant que la structure juridique (société, juridiction,
prospectus ou exemptions, restrictions par pays) n'est pas validée par un
conseil. Le mot **"garanti" est à bannir** de toute communication — ce dépôt
formule partout les dividendes comme *variables et possiblement nuls*.

## 2. Paiements par carte et conversion en stablecoin

- Les PSP (Stripe, Adyen…) **interdisent généralement** dans leurs CGU
  l'utilisation de leurs rails pour financer des distributions crypto ; le
  compte peut être gelé avec les fonds. Il faut un PSP compatible crypto et un
  montage validé (facturation du service IA d'un côté, trésorerie crypto de
  l'autre).
- Convertir des EUR/USD en stablecoin et les redistribuer peut faire de
  l'opérateur un **prestataire de services sur actifs numériques** (PSAN/AMF en
  France, MSB/FinCEN aux USA) avec enregistrement, KYC/AML et obligations de
  reporting.

## 3. Fiscalité

- Les 10 % fondateur (tokens et revenus) sont un revenu imposable dès
  perception ; les dividendes des stakers aussi, dans leur juridiction.
- L'émission et la distribution peuvent créer des obligations déclaratives pour
  l'entité émettrice (TVA sur l'abonnement IA, IS sur les revenus, etc.).

## 4. Données personnelles (RGPD)

Le réseau archive des **conversations d'utilisateurs** sur des machines de
tiers. Obligations minimales :

- chiffrement de bout en bout AVANT archivage (le réseau ne doit voir que des
  blobs opaques — c'est le contrat d'interface de `storage_net.py`) ;
- base légale, information des utilisateurs, droit à l'effacement (prévoir la
  suppression des clés de déchiffrement = effacement effectif) ;
- les nœuds de stockage étant potentiellement hors UE, encadrer les transferts.

## 5. Le contenu généré par le réseau

Les candidats d'amélioration proviennent de tiers anonymes. Avant intégration
au cœur IA : revue (humaine ou automatisée) contre l'injection de prompts
malveillants, les contenus illicites et les portes dérobées. Le quorum de votes
v1 est un filtre de qualité, pas un filtre de sécurité.

## 6. Communication — règles d'hygiène appliquées dans ce dépôt

- Jamais "rendement garanti", "rente", "la valeur va monter" → toujours
  "variable", "peut être nul", "actif expérimental, perte totale possible".
- Le calendrier d'émission (halving) est un fait technique côté offre ; il ne
  doit jamais être présenté comme une promesse de prix.
- Toute modification des contrats après le lancement doit être ré-auditée et
  re-testée avant redéploiement — et communiquée comme telle.
