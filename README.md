<p align="center"><img src="assets/icon.png" width="128" alt="Pawsync Feeder icon"></p>

# Pawsync Feeder for Home Assistant

[![hacs][hacs-badge]][hacs-url] [![Validate][validate-badge]][validate-url]

*[Version française](README.fr.md)*

Home Assistant integration for **Pawsync** smart pet feeders, with a built-in dashboard card.
Tested with the **PPF-R361S-WEU** (`VS_WB_PFM_PPF-R361S-WEU_EU`); other Pawsync feeders using the same cloud
API should work too.

It builds on the cloud protocol reverse-engineered by the community
([jasonmeisel/pawsync-hass](https://github.com/jasonmeisel/pawsync-hass),
[smcneece/pawsync-hass](https://github.com/smcneece/pawsync-hass), MIT licence), rewritten from scratch.

> This project is not affiliated with, endorsed by, or connected to Pawsync or VeSync.

## Highlights

| | pawsync-hass | Pawsync Feeder |
|---|---|---|
| API client | global state shared between accounts | one client per account, no global state |
| Expired token | re-login in some places | automatic re-login and retry on **every** call |
| Changed password | errors in the log | Home Assistant **re-authentication** flow |
| Time zone / country | hard-coded `America/Los_Angeles`, `US` | taken from your HA settings (correct "today" totals) |
| Units | custom US / metric switch | native grams, standard per-entity unit conversion |
| Names | English only | translated (**English**, **French**) |
| Polling | sequential | status, logs and pets fetched in parallel; firmware every 6 h |
| Firmware | binary sensor | native **update** entity |
| Events | — | **event** entity (scheduled meal, extra meal, pet ate) |
| Diagnostics | — | downloadable, personal data redacted |
| `feed` action | targets a sensor entity | targets a **device**, amount in grams |
| Dashboard | — | **built-in card**, registered automatically |

## Entities (per feeder)

- **Sensors**: food in bowl (live scale), hopper level, food left in hopper, food supply (days), desiccant
  remaining (days), next meal (timestamp) and amount, planned daily total, last dispensed time and amount,
  dispensed today, last eaten time, amount and duration, eaten today, alerts; for the linked pet: weight,
  intake today, daily target, meals today.
- **Binary sensors**: online, bowl (problem when removed), mains power, desiccant expired.
- **Buttons**: extra meal, meal call, tare bowl scale, reset desiccant.
- **Switches**: smart feeding, slow feeding, precision mode, sleep mode.
- **Times**: sleep mode start / end.
- **Numbers**: extra meal size (g, stored locally), hopper fill after a refill (ml).
- **Event**: `feeding` (types `scheduled_meal`, `extra_meal`, `eaten`, with the amount).
- **Update**: firmware (information only — install updates from the Pawsync app).

## Installation

### HACS (recommended)

1. In HACS, open the **⋮** menu → **Custom repositories**.
2. Add `https://github.com/globoudou/pawsync_feeder`, type **Integration**.
3. Search for **Pawsync Feeder** and click **Download**.
4. Restart Home Assistant.

### Manual

Copy `custom_components/pawsync_feeder` into your Home Assistant `config/custom_components/` folder and restart.

### Configuration

**Settings → Devices & services → Add integration → Pawsync Feeder**, then sign in with your Pawsync app
credentials. The polling interval (default 5 minutes) can be changed from the integration's options.

Requires Home Assistant 2025.8 or newer. The integration icon is shown from Home Assistant 2026.3 onwards.

## Dashboard card

The integration ships its own card and adds it to your dashboard resources automatically (storage mode,
the default). After an update, fully close and reopen the mobile app.

**Edit dashboard → Add card →** search for **Pawsync Feeder**. The card finds the feeder's entities on its
own and shows: hopper and bowl levels, alerts (offline, bowl removed, desiccant), next and last meal, today's
totals, a **Feed** button with confirmation, portion size, meal call and sleep mode.

```yaml
type: custom:pawsync-feeder-card
# device: <device id>   # optional if you only have one feeder
# title: Kibble         # optional
```

If the card shows "Custom element doesn't exist", add the resource by hand: enable **Advanced mode** in your
profile, then **Settings → Dashboards → ⋮ → Resources → Add resource**, URL
`/pawsync_feeder/pawsync-feeder-card.js`, type **JavaScript module**.

## Actions

`pawsync_feeder.feed` — dispense an extra meal now.

```yaml
action: pawsync_feeder.feed
data:
  device_id: <your feeder device id>
  amount: 11   # grams, optional (defaults to the "Extra meal size" number)
```

## Automation example

```yaml
triggers:
  - trigger: state
    entity_id: event.my_feeder_feeding
    attribute: event_type
    to: eaten
actions:
  - action: notify.mobile_app_my_phone
    data:
      message: "The cat ate {{ trigger.to_state.attributes.amount }} g"
```

## Known limitations

- Unofficial cloud API: Pawsync may change it without notice.
- Hopper capacity is assumed to be 3.6 L (used to convert the fill percentage).
- All calls go to `smartapi.pawsync.com`, the host used by the app (works for EU accounts too).
- Switches change state immediately; if the cloud does not confirm, the real state comes back on the next refresh.

## Troubleshooting

Download the diagnostics from the integration's **⋮** menu (credentials and personal data are redacted) and
attach them to an [issue](https://github.com/globoudou/pawsync_feeder/issues).

## Development

```bash
pip install pytest-homeassistant-custom-component
pytest tests
```

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://hacs.xyz/docs/faq/custom_repositories
[validate-badge]: https://github.com/globoudou/pawsync_feeder/actions/workflows/validate.yaml/badge.svg
[validate-url]: https://github.com/globoudou/pawsync_feeder/actions/workflows/validate.yaml
