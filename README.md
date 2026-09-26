# Prix Carburant Total Énergies

![Prix Carburant](logo.svg)

Intégration Home Assistant pour récupérer les prix des carburants des stations TotalÉnergies à partir du flux officiel des prix du carburant et des stations TotalÉnergies.

## Installation HACS

1. Dans HACS → Intégrations → menu ⋮ → Dépôts personnalisés.
2. Ajouter `Userfreedu42/hass-prixcarburant-totalenergies` comme **Integration**.
3. Installer **Prix Carburant Total Energies**.
4. Redémarrer Home Assistant.
5. Ajouter l'intégration depuis **Paramètres → Appareils et services → Ajouter une intégration**.

L'intégration utilise la position de Home Assistant pour découvrir les stations dans un rayon configurable. Une sélection manuelle de stations est également disponible.

Carburants pris en charge : Gazole, SP95, SP98, E10, E85 et GPLc.

Les données de stations sont chargées automatiquement pendant la configuration et les prix sont actualisés selon l'intervalle choisi.
