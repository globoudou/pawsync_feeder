# Pawsync Feeder — intégration Home Assistant

Intégration Home Assistant pour les distributeurs de croquettes **Pawsync** (testée en simulation pour le
modèle **PPF-R361S-WEU**, `VS_WB_PFM_PPF-R361S-WEU_EU`).

Elle réutilise le protocole cloud découvert par la communauté
([jasonmeisel/pawsync-hass](https://github.com/jasonmeisel/pawsync-hass),
[smcneece/pawsync-hass](https://github.com/smcneece/pawsync-hass), licence MIT), réécrit proprement.

## Ce qui change par rapport aux intégrations existantes

| | pawsync-hass | Pawsync Feeder |
|---|---|---|
| Client API | état global partagé entre comptes | un client par compte, sans état global |
| Jeton expiré | ré-auth au cas par cas | ré-auth + nouvel essai automatique sur **chaque** appel |
| Mot de passe changé | erreurs dans les logs | flux de **ré-authentification** HA |
| Fuseau / pays | `America/Los_Angeles`, `US` en dur | pris dans la config HA (stats « aujourd'hui » justes) |
| Unités | bascule maison US / métrique | grammes natifs, conversion HA standard par entité |
| Noms | anglais en dur | traductions **FR** / EN |
| Requêtes | en série | statuts, journaux et animaux en parallèle ; firmware toutes les 6 h |
| Firmware | binary_sensor | entité **update** native |
| Événements | — | entité **event** (repas programmé, repas supplémentaire, animal a mangé) |
| Diagnostics | — | téléchargeables, données sensibles masquées |
| Action `feed` | par entity_id d'un capteur | par **appareil**, quantité en grammes |

## Entités (par distributeur)

- **Capteurs** : croquettes dans la gamelle (balance en direct), niveau du réservoir, croquettes restantes,
  autonomie (jours), déshydratant (jours), prochain repas (horodatage), quantité du prochain repas,
  total programmé, dernière distribution / quantité, distribué aujourd'hui, dernier repas mangé / quantité /
  durée, mangé aujourd'hui, alertes ; pour l'animal lié : poids, consommation du jour, objectif, nombre de repas.
- **Capteurs binaires** : en ligne, gamelle (problème si retirée), alimentation secteur, déshydratant épuisé.
- **Boutons** : repas supplémentaire, appel du repas, tarer la balance, réinitialiser le déshydratant.
- **Interrupteurs** : distribution intelligente, distribution lente, mode précision, mode nuit.
- **Heures** : début / fin du mode nuit.
- **Nombres** : portion du repas supplémentaire (g, stockée localement), remplissage du réservoir après recharge (ml).
- **Événement** : `repas` (types `scheduled_meal`, `extra_meal`, `eaten`, avec la quantité).
- **Mise à jour** : firmware (information seulement, l'installation se fait depuis l'app).

## Installation

1. Copier `custom_components/pawsync_feeder` dans le dossier `config/custom_components/` de Home Assistant
   (ou ajouter ce dépôt comme dépôt personnalisé HACS, type *Intégration*).
2. Redémarrer Home Assistant.
3. *Paramètres → Appareils et services → Ajouter une intégration → Pawsync Feeder*, puis les identifiants
   de l'app Pawsync.

Elle peut cohabiter avec `pawsync` (domaine différent), pratique pour comparer avant de désinstaller l'ancienne.

Home Assistant 2025.8 ou plus récent est requis.

## Exemple d'automatisation

```yaml
triggers:
  - trigger: state
    entity_id: event.gamelle_repas
    attribute: event_type
    to: eaten
actions:
  - action: notify.mobile_app_telephone
    data:
      message: "Le chat a mangé {{ trigger.to_state.attributes.amount }} g"
```

## Limites connues

- API cloud non officielle : Pawsync peut la modifier sans préavis.
- La capacité du réservoir est fixée à 3,6 L (utilisée pour convertir le pourcentage de remplissage).
- Toute l'API est appelée sur `smartapi.pawsync.com`, l'hôte utilisé par l'app ; des comptes européens
  l'utilisent sans souci d'après les retours de la communauté.
- Les interrupteurs passent immédiatement dans le nouvel état ; si le cloud ne confirme pas, l'état réel
  revient au rafraîchissement suivant.

## Développement

```bash
pip install pytest-homeassistant-custom-component
pytest tests
```
