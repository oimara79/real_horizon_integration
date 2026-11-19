# Horizon Profile

Home Assistant custom integration that generates a terrain horizon profile from Copernicus GLO-30 elevation data and exposes it as a sensor for the [True Horizon Profile Card](https://github.com/oimara79/real_horizon_card).

## Installation

### HACS

1. In HACS, open **Integrations** and select the menu to add a custom repository.
2. Add `oimara79/real_horizon_integration` and select **Integration** as the category.
3. Install **Horizon Profile** and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration**, search for **Horizon Profile**, and add it.

### Manual

1. Copy `custom_components/horizon_profile` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration**, search for **Horizon Profile**, and add it.

## Data and requirements

The integration uses Home Assistant's configured latitude and longitude. On first setup, it downloads the required Copernicus GLO-30 elevation tiles, calculates a 360° horizon profile at a default 0.2° azimuth step, and stores the result in Home Assistant's persistent storage. Later setups reuse the cache unless the location or generator settings change. Internet access is required for the initial download.

Home Assistant installs the declared Python dependencies (`numpy`, `pyproj`, and `scipy`). The bundled generator reads the GeoTIFF tiles directly and does not require Rasterio or GDAL.

The integration provides a `sensor.horizon_profile` sensor. Its state is `ready`; the `profile_csv` attribute contains the measurements as CSV with `azimuth,height` columns, which can be used by the card.

It also provides four timestamp sensors and a visibility sensor, refreshed once per minute:

- `sensor.sun_next_visible_setting`: next time the sun goes behind the generated horizon.
- `sensor.sun_next_visible_rising`: next time the sun emerges above the generated horizon.
- `sensor.sun_first_visible_sunrise_today`: earliest visible rising event on the current Home Assistant local date.
- `sensor.sun_last_visible_sunset_today`: latest visible setting event on the current local date.
- `sensor.sun_visible`: `sun is visible` when the sun is above the horizon profile at its current azimuth; otherwise `sun is not visible`.

The terrain can cause more than one visible rising or setting in a day. The two “next” sensors report the next matching event, including tomorrow when there is no later matching event today. The daily sensors report the first rise and last setting respectively. If there are no matching crossings today or tomorrow, the corresponding next-event sensor has no state; if there is no crossing of that type today, its daily sensor has no state.

Use the profile sensor with the card like this:

```yaml
type: custom:true-horizon-profile-card
entity: sensor.horizon_profile
```

The card can also be used independently by supplying CSV data directly in its YAML configuration.

## Moving from the combined repository

If you previously installed the integration from `real_horizon_card`, switch its source to this repository and make sure there is only one copy of `custom_components/horizon_profile` in your Home Assistant configuration. Keep the existing Horizon Profile config entry; the integration domain and sensor data format are unchanged.

## Standalone generator

The bundled `horizon.py` command-line wrapper can generate a CSV profile outside Home Assistant when its Python dependencies are installed:

```text
python horizon.py 47.7231 12.8786 --max-dist 50000 --az-step 1 --out horizon.csv
```

Use `--help` to see all available options.
