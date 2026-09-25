# TotalEnergies Prix Carburant

Intégration Home Assistant pour récupérer les prix des carburants TotalEnergies à partir du flux officiel des prix carburant.

## Installation HACS

1. Dans HACS → Intégrations → menu ⋮ → Dépôts personnalisés.
2. Ajouter `Userfreedu42/hass-prixcarburant-totalenergies` comme **Integration**.
3. Installer **TotalEnergies Prix Carburant**.
4. Redémarrer Home Assistant.
5. Ajouter l'intégration depuis **Paramètres → Appareils et services → Ajouter une intégration**.

L'intégration utilise la position Home Assistant pour découvrir les stations dans un rayon configurable. Une sélection manuelle de stations est également disponible.

Carburants pris en charge : Gazole, SP95, SP98, E10, E85 et GPLc.

Les données de stations sont chargées automatiquement pendant la configuration et les prix sont actualisés selon l'intervalle choisi.
