from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN,FUEL_LABELS

async def async_setup_entry(hass,entry,add):
    c=hass.data[DOMAIN][entry.entry_id]
    ents=[]
    for sid in c.data:
        for f,l in FUEL_LABELS.items():ents.append(Fuel(c,sid,f,l))
    add(ents)

class Fuel(SensorEntity):
    _attr_native_unit_of_measurement=UnitOfVolume.LITERS
    def __init__(self,c,sid,f,l):
        self.c=c;self.sid=sid;self.f=f;self._attr_name=f"TotalEnergies {sid} — {l}"
        self._attr_unique_id=f"totalenergies_{sid}_{f}"
        self._attr_device_info=DeviceInfo(identifiers={(DOMAIN,sid)},name=f"TotalEnergies — {sid}",manufacturer="TotalEnergies")
    @property
    def native_value(self):
        x=self.c.data.get(self.sid,{}).get("fuels",{}).get(self.f)
        return x.get("price") if x else None
    @property
    def extra_state_attributes(self):
        s=self.c.data[self.sid];x=s.get("fuels",{}).get(self.f,{})
        return {"station_id":self.sid,"price_status":"rupture" if x.get("price")=="rupture" else "available",
                "price_updated":x.get("updated"),"distance_km":s.get("distance_km"),
                "latitude":s.get("latitude"),"longitude":s.get("longitude"),"address":s.get("address"),
                "postal_code":s.get("postal_code"),"city":s.get("city"),"services":s.get("services",[])}
