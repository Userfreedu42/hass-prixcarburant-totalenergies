from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries

from .const import DOMAIN, DEFAULT_RADIUS_KM, DEFAULT_SCAN_MINUTES


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 3

    async def async_step_user(self, user_input=None):
        if user_input:
            return self.async_create_entry(
                title=f"Prix Carburant Total Energies — {user_input['radius_km']} km",
                data={
                    "latitude": float(user_input["latitude"]),
                    "longitude": float(user_input["longitude"]),
                    "radius_km": float(user_input["radius_km"]),
                    "stations": [],
                },
                options={"scan_interval": int(user_input["scan_interval"])},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("latitude", default=self.hass.config.latitude): vol.Coerce(float),
                vol.Required("longitude", default=self.hass.config.longitude): vol.Coerce(float),
                vol.Required("radius_km", default=DEFAULT_RADIUS_KM): vol.All(
                    vol.Coerce(float), vol.Range(min=1, max=100)
                ),
                vol.Required("scan_interval", default=DEFAULT_SCAN_MINUTES): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=120)
                ),
            }),
        )
