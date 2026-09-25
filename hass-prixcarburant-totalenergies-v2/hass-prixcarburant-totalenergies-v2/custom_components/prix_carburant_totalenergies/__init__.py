from __future__ import annotations
import io, math, zipfile, xml.etree.ElementTree as ET, logging
from datetime import timedelta
import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import DOMAIN,DEFAULT_SCAN_MINUTES,INSTANT_URL

_LOGGER=logging.getLogger(__name__)
PLATFORMS=["sensor","binary_sensor"]

def _local(t): return t.rsplit("}",1)[-1].lower()
def _text(e,n):
    for c in list(e):
        if _local(c.tag)==n:return (c.text or "").strip()
    return ""
def _coord(v):
    try:
        x=float(v);return x/100000 if abs(x)>180 else x
    except:return None
def distance(a,b,c,d):
    r=6371.0088;p1=math.radians(a);p2=math.radians(c)
    x=math.radians(c-a);y=math.radians(d-b)
    q=math.sin(x/2)**2+math.cos(p1)*math.cos(p2)*math.sin(y/2)**2
    return 2*r*math.asin(math.sqrt(q))

def parse(raw,cfg):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        n=next(x for x in z.namelist() if x.lower().endswith(".xml"))
        root=ET.fromstring(z.read(n))
    wanted=set(map(str,cfg.get("stations",[]))); lat0=cfg["latitude"];lon0=cfg["longitude"];radius=cfg["radius_km"]
    out={}
    for p in root.iter():
        if _local(p.tag)!="pdv":continue
        a={_local(k):v for k,v in p.attrib.items()};sid=str(a.get("id",""))
        lat=_coord(a.get("latitude"));lon=_coord(a.get("longitude"))
        if lat is None or lon is None:continue
        dist=distance(lat0,lon0,lat,lon)
        if wanted and sid not in wanted:continue
        if not wanted and dist>radius:continue
        fuels={}
        for e in p.iter():
            if _local(e.tag)!="prix":continue
            q={_local(k):v for k,v in e.attrib.items()};n=(q.get("nom") or "").lower()
            if "gazole" in n:f="gazole"
            elif "sp95" in n and "e10" not in n:f="sp95"
            elif "sp98" in n:f="sp98"
            elif "e10" in n:f="e10"
            elif "e85" in n:f="e85"
            elif "gpl" in n:f="gplc"
            else:continue
            fuels[f]={"price":float(q["valeur"].replace(",",".")) if q.get("valeur") else "rupture","updated":q.get("maj")}
        out[sid]={"station_id":sid,"latitude":lat,"longitude":lon,"distance_km":round(dist,2),
                  "postal_code":a.get("cp"),"address":_text(p,"adresse"),"city":_text(p,"ville"),
                  "fuels":fuels,"services":sorted({(e.text or "").strip() for e in p.iter() if _local(e.tag)=="service" and e.text and e.text.strip()})}
    return out

async def async_setup(hass,config): hass.data.setdefault(DOMAIN,{});return True
async def async_setup_entry(hass,entry):
    c=Coordinator(hass,entry);await c.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id]=c
    await hass.config_entries.async_forward_entry_setups(entry,PLATFORMS);return True
async def async_unload_entry(hass,entry):
    ok=await hass.config_entries.async_unload_platforms(entry,PLATFORMS)
    if ok:hass.data[DOMAIN].pop(entry.entry_id,None)
    return ok

class Coordinator(DataUpdateCoordinator):
    def __init__(self,hass,entry):
        super().__init__(hass,logger=_LOGGER,name=DOMAIN,update_interval=timedelta(minutes=entry.options.get("scan_interval",DEFAULT_SCAN_MINUTES)))
        self.entry=entry
    async def _async_update_data(self):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
                async with s.get(INSTANT_URL) as r:r.raise_for_status();raw=await r.read()
            return await self.hass.async_add_executor_job(parse,raw,self.entry.data)
        except Exception as e:raise UpdateFailed(str(e)) from e
