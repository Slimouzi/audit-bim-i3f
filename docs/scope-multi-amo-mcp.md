# Scope — profils MCP multi-AMO

> **Document historique.** Rédigé quand la distribution s'appelait
> `audit-bim-i3f` ; elle se nomme **`audit-bim-mcp`** depuis la 0.11.0
> (2026-08-08). Les noms cités ci-dessous n'ont **pas** été réécrits : ce
> document est une trace de décision, pas une consigne courante.

Objectif : faire d'`audit-bim-i3f` un MCP enfant qui compose des briques BIM
génériques, puis préparer un prochain MCP AMO BIM in Motion sans copier la logique
I3F.

Cette V1 ne change aucun comportement I3F. Elle ajoute seulement un registre de
profils (`audit_bim.profiles`) et un tool read-only (`list_mcp_profiles`) qui
rend visible la frontière entre socle réutilisable et spécialisation client.

## Architecture cible

Un MCP client ne doit porter que ce qui lui est propre :

- prompt et posture AMO ;
- référentiel contractuel ;
- règles d'audit client ;
- packs de rapports et conventions documentaires ;
- paramètres de mission validés par l'utilisateur.

Le reste doit venir des briques génériques :

| Brique | État | Destination |
|---|---|---|
| Extraction BIMData / snapshot | externalisée | `bimdata-read` |
| Calculs IFC OpenShell | externalisée | `ifc-geometry-mcp` |
| Moteur d'audit | externalisée | `bim-audit-engine` |
| Requêtes / sélections | externalisée | `bim-query` |
| BCF | externalisée | `bim-publication` |
| Smart Views | externalisée | `bim-publication` |
| Classification | dans ce dépôt | futur `bim-classifier` |
| DOE | dans ce dépôt | futur `bim-doe` |
| Enrichissement | dans ce dépôt | futur `bim-enrichment` |
| Reporting | dans ce dépôt | futur `bim-reporting` |

## Règle de découpage

Une brique générique ne connaît aucun maître d'ouvrage. Elle manipule des
contrats stables (`ModelSnapshot`, `Finding`, contrats JSON de quantités,
payloads BCF/SmartView, manifestes de rapports). Elle ne contient pas de nom de
chantier, pas de CCH I3F, pas de table propriétaire, pas de template Tarare.

Un MCP enfant compose ces briques et ajoute ses choix métier. I3F garde donc
`requirements_i3f`, `audit_rules_i3f`, `report_pack_avp_i3f` et son prompt. BIM
in Motion devra créer ses propres référentiels, prompts et packs, sans importer
le pack AVP I3F.

## V1 livrée

- `audit_bim.profiles` décrit les modules génériques et les profils connus.
- Le profil `i3f` reste le défaut et le seul profil opérationnel.
- Le profil `bim_in_motion` est préparatoire : il active les mêmes briques
  génériques mais ne possède encore aucun pack de rapport.
- `list_mcp_profiles` expose cette carte aux agents et aux développeurs.

## Suite recommandée

1. Extraire le socle de reporting vers `bim-reporting` : modèles de livrables,
   manifeste, helpers Word/Excel/PDF, QA gates génériques. Garder `avp_i3f` comme
   pack enfant I3F.
2. Extraire `bim-classifier` : catalogues, signaux, suggestion store et planners
   prepare/apply, en séparant les tables client.
3. Extraire `bim-doe`, puis `bim-enrichment` : connecteurs et rapprochements
   neutres d'abord, règles client ensuite.
4. Créer le dépôt MCP BIM in Motion : dépendre des briques génériques, déclarer
   le profil `bim_in_motion`, puis ajouter prompt, référentiel et packs propres.
5. Durcir les tests d'architecture : aucun nouveau module générique ne doit
   importer `audit_bim.reporting.avp`, `audit_bim.requirements` ou un nom client.

Critère de merge pour chaque extraction : parité sur fixtures, suite I3F verte,
aucun changement de surface MCP I3F sauf ajout documenté, et recette live I3F
non régressée quand la brique touche aux livrables.
