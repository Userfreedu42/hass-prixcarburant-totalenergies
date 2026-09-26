# Prix Carburant Total Énergies

![Prix Carburant](logo.svg)

Intégration Home Assistant pour récupérer les prix et les ruptures des carburants des stations TotalEnergies.

Les stations sont croisées avec le catalogue **stations-service-1** et les prix/ruptures proviennent du flux instantané v2 de la DGCCRF. Le flux officiel est mis à jour toutes les 10 minutes. citeturn7search2

## Installation HACS

1. Dans HACS → Intégrations → menu ⋮ → Dépôts personnalisés.
2. Ajouter `Userfreedu42/hass-prixcarburant-totalenergies` comme **Integration**.
3. Installer **Prix Carburant Total Energies**.
4. Redémarrer Home Assistant.
5. Ajouter l'intégration depuis **Paramètres → Appareils et services → Ajouter une intégration**.

L'intégration utilise la position configurée dans Home Assistant pour rechercher les stations dans un rayon configurable.

## Version 0.4.0

- correction de la requête géographique pour l'API Explore v2.1 : `within_distance()` au lieu de l'ancienne forme `distance()` ;
- correction du filtre `id IN (...)` : les identifiants du flux sont des entiers et ne doivent pas être entourés de guillemets ;
- conservation exclusive des stations Total, Total Access et variantes TotalEnergies présentes dans le catalogue ;
- prise en compte prioritaire du champ officiel `rupture` et des champs de rupture temporaire/définitive ;
- les statuts `inconnu`, `problème`, `erreur`, etc. ne sont plus affichés ;
- nom des appareils au format `code postal — ville` ;
- les capteurs de carburant restent nommés simplement `Gazole`, `E10`, `SP98`, etc. et les capteurs de statut `Gazole — Rupture`, etc.

Le schéma v2.1 documente bien `rupture`, `carburants_disponibles`, `carburants_indisponibles`, `carburants_rupture_temporaire`, `carburants_rupture_definitive` et les champs `*_rupture_type`. citeturn1search0turn7search2

### À propos de TotalEnergies

La carte officielle TotalEnergies permet de retrouver les stations et les carburants/services proposés. citeturn0search0 Pour l'état **Rupture / Non**, l'intégration utilise le flux gouvernemental officiel, qui expose explicitement les ruptures par carburant ; c'est la source machine-readable la plus adaptée pour Home Assistant. citeturn1search0

Carburants pris en charge : Gazole, SP95, SP98, E10, E85 et GPLc.
