# Référence juridique et réglementaire — modèle AQL

> **À lire avant tout lancement.** AQL n'a ni émetteur, ni premine, ni
> administrateur : les paiements en USDT sont reçus et répartis par un
> contrat. Ce modèle doit faire l'objet d'une analyse juridique dans chaque
> juridiction où le réseau est exploité ou promu.

Ce document n'est pas un avis juridique. Il liste les sujets que l'analyse doit
couvrir, et la façon dont le code y répond déjà.

## 1. Statut du jeton

- L'AQL n'est ni vendu ni pré-alloué : il n'est créé qu'en récompense d'un
  travail vérifié, comme le bitcoin.
- Les détenteurs qui stakent reçoivent une part des paiements des
  utilisateurs. Dans plusieurs juridictions, un droit à des revenus peut
  faire qualifier un jeton d'instrument financier. Le point est à trancher
  pour chaque pays où le réseau est promu.
- L'absence d'émetteur ne supprime pas les obligations des personnes qui
  opèrent des parties du réseau : coordinateur, oracles, sites qui intègrent
  un achat par carte.

## 2. Flux de paiement

- Le protocole ne reçoit que de l'USDT, directement dans le contrat
  AQLNetwork, qui le répartit à la seconde. Personne ne détient les fonds des
  utilisateurs.
- L'achat d'USDT par carte passe par un service tiers, qui vérifie lui-même
  l'identité de l'acheteur. Le site qui intègre ce service doit ouvrir un
  compte chez lui et respecter ses conditions.

## 3. Fiscalité

Mineurs et stakers perçoivent des revenus (AQL, USDT) imposables selon leur
juridiction. Le site le rappelle et ne donne aucun conseil en investissement.

## 4. Données personnelles

- Un compte ne demande aucune donnée personnelle : seulement une clé et un
  crédit.
- Le mineur qui sert une requête la voit en clair. C'est inévitable pour
  faire tourner le modèle, et c'est affiché à l'utilisateur avant le premier
  message.
- L'historique des conversations reste dans le navigateur de l'utilisateur.
  Le réseau de stockage ne reçoit que des données chiffrées par l'application.

## 5. Contenu généré

- Le réseau sert un modèle open-weights sous licence permissive, dont il
  faut respecter les conditions d'usage.
- Les prompts candidats sont filtrés avant toute mesure : liens, contacts et
  code sont refusés (voir DECISIONS.md, point 10 bis).

## 6. Règles de communication appliquées dans ce dépôt

- Jamais « rendement garanti », « rente », « la valeur va monter ». Toujours
  « variable », « peut être nul », « le prix peut baisser jusqu'à zéro ».
- Le halving est un fait technique côté offre, jamais une promesse de prix.
- Aucune jauge de comparaison non mesurée (« X % du niveau de tel modèle ») :
  seuls les scores réellement mesurés au même test sont affichés.
- Toute modification des contrats doit être ré-auditée et re-testée avant
  redéploiement, et annoncée comme telle.
