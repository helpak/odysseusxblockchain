# Registre des décisions AQL

Chaque problème du projet est posé comme une question. La **réponse
recommandée est en premier (✅) et c'est elle qui est appliquée**. Les autres
options sont gardées avec la raison de leur rejet, pour que tout le monde
puisse vérifier le raisonnement.

État : **fait** = codé et vérifié dans ce dépôt ; **documenté** = règle
d'exploitation, rien à coder ; **v2** = prévu, pas encore codé.

---

## Économie

### 1. Comment le prix de l'AQL est-il fixé, sans intervention humaine ?
- ✅ **Par le marché, automatiquement** : un pool d'échange AQL/USDT (Uniswap).
  Le prix découle des achats et des ventes, et les écarts entre plateformes
  sont corrigés par l'arbitrage. Le protocole ne fixe aucun prix, exactement
  comme pour Bitcoin. Le site affiche le prix lu dans le pool.
- ❌ Vote du prix tous les 2 jours : un prix voté n'oblige personne à acheter
  ni à vendre à ce prix. Les détenteurs auraient intérêt à voter haut, et le
  vrai prix serait celui des échanges de toute façon.
- ❌ Prix garanti par le contrat (rachat à prix fixe) : il faudrait une réserve
  de dollars pour honorer ce prix, et elle serait vidée à la première vague de
  ventes.

État : **fait**. Le tableau de bord lit le prix du pool dès que son adresse
est renseignée.

### 2. Qui crée la liquidité de départ du pool ?
- ✅ **Les premiers mineurs et détenteurs, librement.** Créer un pool Uniswap
  ne demande aucune permission. Comme pour Bitcoin à ses débuts, le marché naît
  quand des gens veulent échanger.
- ❌ Liquidité détenue par le protocole : il faudrait prélever sur les 67/33,
  ce qui change la répartition décidée et retarde les paiements des mineurs.

État : **documenté**.

### 3. Comment le prix de l'IA (par million de tokens) est-il fixé ?
- ✅ **Automatiquement selon la charge du réseau**, sur le principe des frais
  de base d'Ethereum. À chaque époque : réseau saturé, le prix monte (+12,5 %
  au plus) ; réseau sous-utilisé, il baisse (−12,5 % au plus). Bornes minimale
  et maximale. Plus il y a de mineurs, plus le prix baisse ; plus il y a de
  demande, plus les mineurs gagnent.
- Option v2 : chaque mineur fixe son propre prix (enchères). Plus fin, mais
  plus lent à servir et plus complexe.
- ❌ Prix fixé par une équipe : intervention humaine.

État : **fait**.

### 4. Quelles formules d'abonnement ?
- ✅ **Crédits prépayés en USDT**, en trois formules : Essai (5 USDT),
  Standard (20 USDT) et Pro (100 USDT). Les crédits sont consommés au prix du
  moment. Les limites : le crédit restant, plus un plafond de requêtes par
  minute et par compte.
- ❌ Abonnement illimité à prix fixe : un utilisateur intensif coûterait plus
  qu'il ne paie, et les mineurs seraient sous-payés.

État : **fait**.

### 5. Les détenteurs reçoivent-ils de l'USDT ou de l'AQL racheté ?
- ✅ **De l'USDT, directement.** C'est stable, lisible, et sans effet sur le
  marché.
- Option : racheter de l'AQL sur le marché et le redistribuer. Ça soutient le
  prix, mais c'est plus complexe et ça peut être anticipé par des traders.

État : **fait** (contrat AQLStaking).

### 6. Comment payer par carte bancaire sans société au centre du réseau ?
- ✅ **Un bouton « Acheter des USDT par carte »** qui mène à un service
  d'achat de crypto. C'est ce service qui vérifie l'identité de l'acheteur. Le
  protocole ne touche jamais d'euros ni de dollars. L'adresse du service se
  configure sur le site.
- ❌ Compte de paiement par carte (type Stripe) : il exige une société
  titulaire qui encaisse l'argent, ce qui contredit un réseau sans
  opérateur central. Ce service a été supprimé.

État : **fait**.

### 7. Comment éviter des frais Ethereum trop lourds ?
- ✅ **Payer en une fois, réclamer en une fois.** Les crédits sont prépayés
  (aucune transaction par requête), et `claimMany` réclame plusieurs époques
  en une seule transaction.
- Option : passer sur une couche 2 (moins chère, mais séquenceur centralisé).
  Les contrats sont compatibles si le besoin se présente.

État : **fait**.

## Minage et vérification

### 8. Comment empêcher qu'on gagne plus en multipliant les nœuds (attaque sybil) ?
- ✅ **Ne payer que du travail utile, vérifié et proportionnel au volume.**
  Diviser sa puissance en 50 nœuds ne rapporte rien de plus. Le bench SHA-256,
  facile à multiplier et inutile pour l'IA, est supprimé. Les votes subjectifs
  sont remplacés par une mesure au benchmark.
- Option v2 : staker de l'AQL pour avoir le droit de miner. Ça freinerait les
  petits mineurs, donc seulement si les attaques apparaissent.

État : **fait**.

### 9. Comment vérifier que les mineurs servent vraiment l'IA ?
- ✅ **Contrôle aléatoire avec arbitrage.** 5 % des requêtes sont rejouées
  par un autre mineur (autre wallet), à température 0, et les réponses sont
  comparées. En cas d'écart, un troisième mineur départage : celui qui
  s'écarte de l'arbitre perd 3 points de réputation et les gains de cette
  réponse. Sous un seuil, un mineur est exclu du service.
- ❌ Preuves cryptographiques d'inférence : pas encore praticables pour de
  grands modèles.

Limite assumée : deux machines honnêtes peuvent produire des réponses un peu
différentes, d'où un seuil de similarité tolérant. Un tricheur prudent peut
passer quelques contrôles, mais pas des centaines. État : **fait**.

### 10. Comment prouver qu'une amélioration améliore vraiment l'IA ?
- ✅ **Mesure sur un benchmark public et figé.** Un candidat (prompt système)
  est mesuré contre la version actuelle par 2 mineurs vérificateurs tirés au
  sort. Il n'est accepté que si les 2 mesurent un gain d'au moins 2 points.
  L'auteur est payé seulement dans ce cas.
- ❌ Votes de mineurs : subjectifs, et ouverts à la collusion. Supprimés.
- Option v2 : améliorations de poids (LoRA), avec le même protocole, quand les
  mineurs auront une chaîne d'entraînement.

État : **fait** pour les prompts.

### 10 bis. Et si une « amélioration » glissait une consigne nuisible ?
- ✅ **Filtre avant toute mesure.** Un prompt candidat qui contient un lien,
  un nom de domaine, une adresse de contact, une adresse de wallet, une
  messagerie ou du code est refusé d'office. Un bon prompt système n'en a
  jamais besoin, alors qu'un prompt promu s'applique à tous les utilisateurs.
- ❌ Ne mesurer que le score : un candidat pourrait gagner des points tout en
  recommandant un site frauduleux.

État : **fait** (filtre testé sur 8 cas nuisibles).

### 11. Comment comparer l'IA aux meilleurs modèles, toutes les 2 heures ?
- ✅ **Même test pour tous.** Le coordinateur fait passer le benchmark public
  au réseau toutes les 2 heures, ainsi qu'aux modèles de référence configurés
  (n'importe quelle API compatible OpenAI, avec une clé facultative). Les
  scores s'affichent côte à côte, avec leur historique.
- ❌ Afficher les scores publiés par les laboratoires : ce n'est pas le même
  test, la comparaison serait trompeuse.
- ❌ Jauge « % du niveau de Claude » : ce serait une affirmation non mesurée.

État : **fait**.

### 12. Quel modèle le réseau sert-il ?
- ✅ **Un modèle open-weights sous licence permissive** (Apache 2.0, par
  exemple Qwen) : usage commercial sans restriction.
- À éviter : les licences « communautaires » qui restreignent l'usage
  commercial ou au-delà d'un certain nombre d'utilisateurs.

État : **documenté** (page « Miner »).

## Confiance et sécurité

### 13. Combien d'oracles, et qui les opère ?
- ✅ **5 oracles, seuil de 3, opérés par des personnes différentes**, chacun
  avec son propre daemon. Un oracle peut être remplacé au même seuil.
- ❌ Un seul oracle : point unique de défaillance.

Limite v1 : tous les oracles lisent le même coordinateur. En v2, chaque oracle
recalcule les gains de façon indépendante. État : **fait** (contrats et
daemon) ; le choix des 5 opérateurs se fait au déploiement.

### 14. Le coordinateur est centralisé : que faire ?
- ✅ **v1 assumée et transparente** : code ouvert, et chaque règlement est
  public avec ses preuves, que n'importe qui peut revérifier.
- v2 : plusieurs coordinateurs, et recalcul indépendant par les oracles.

État : **documenté**.

### 15. Comment protéger la vie privée des conversations ?
- ✅ **L'historique reste dans le navigateur de l'utilisateur.** Le réseau de
  stockage ne reçoit que des données chiffrées par l'application.
- **Point à afficher clairement** : le mineur qui sert une requête la voit en
  clair, car c'est inévitable pour faire tourner le modèle. Le portail le dit
  aux utilisateurs avant le premier message.

État : **fait**.

### 16. Comment éviter les abus (spam, rafales de requêtes) ?
- ✅ **Plafond de requêtes par minute et par compte**, et aucune requête sans
  crédit.

État : **fait**.

## Déploiement

### 17. Où héberger chaque partie ?
- ✅ **Le site sur Vercel** (statique uniquement), **le coordinateur sur un
  serveur Docker derrière HTTPS**, et **les oracles sur des machines
  séparées**.
- ❌ Tout sur Vercel : le coordinateur a besoin d'une base persistante et de
  processus permanents, ce que Vercel ne fournit pas.

État : **fait** (configuration Vercel corrigée).

### 18. Comment garantir que le coordinateur et la chaîne comptent les mêmes époques ?
- ✅ **Une seule genèse** : le déploiement affiche `GENESIS_TS`, et le
  coordinateur utilise exactement cette valeur.

État : **fait**.

### 19. Le cadre juridique est-il réglé ?
- ✅ **Analyse juridique avant tout lancement**, dans chaque juridiction où
  le réseau est exploité ou promu (voir LEGAL.md).

État : **à faire par les opérateurs avec leurs conseils**, avant le lancement.
