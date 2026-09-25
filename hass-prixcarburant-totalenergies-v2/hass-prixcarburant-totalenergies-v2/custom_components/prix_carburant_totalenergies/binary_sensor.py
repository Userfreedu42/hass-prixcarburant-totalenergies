from homeassistant.components.binary_sensor import BinarySensorEntity
from .const import DOMAIN
async def async_setup_entry(hass,entry,add):
    c=hass.data[DOMAIN][entry.entry_id];add([Rupture(c,s) for s in c.data])
class Rupture(BinarySensorEntity):
    _attr_device_class="problem"
    def __init__(self,c,s):self.c=c;self.sid=s;self._attr_unique_id=f"totalenergies_{s}_rupture";self._attr_name=f"TotalEnergies {s} — Rupture"
    @property
    def is_on(self):return any(x.get("price")=="rupture" for x in self.c.data[self.sid].get("fuels",{}).values())
    @property
    def extra_state_attributes(self):return {"ruptures":[k for k,x in self.c.data[self.sid].get("fuels",{}).items() if x.get("price")=="rupture"]}
