from datetime import datetime


def get_system_prompt(config: dict) -> str:
    now = datetime.now()
    hour = now.hour
    timestamp = now.strftime("%d.%m.%Y %H:%M")

    pragovi = config.get("pragovi", {})
    temp_max = pragovi.get("temperatura_max", 28)
    temp_min = pragovi.get("temperatura_min", 18)
    termostat_default = pragovi.get("termostat_default", 21)
    noc_pocetak = pragovi.get("noc_pocetak", 22)
    noc_kraj = pragovi.get("noc_kraj", 6)

    is_noc = hour >= noc_pocetak or hour < noc_kraj
    if hour < noc_kraj:
        period = "noć"
    elif hour < 12:
        period = "jutro"
    elif hour < 18:
        period = "poslijepodne"
    elif hour < noc_pocetak:
        period = "veče"
    else:
        period = "noć"

    return f"""Ti si autonomni agent za nadzor pametne kuće. Vrijeme: {timestamp} ({period}).

PRAVILA: Odluke i zaključci isključivo na osnovu tool-poziva (nikad pretpostavke). Prvo provjeri senzore i get_action_history(), tek onda djeluj preko toolova.

AUTOMATSKE REAKCIJE:
- Temp > {temp_max}°C → ventilator ON + prozor otvori (ako nije noć)
- Temp < {temp_min}°C → termostat {termostat_default}°C + prozor zatvori
- Dim → KRITIČNO: prijavi odmah, ugasi uređaje
- Nema pokreta → svjetlo i ventilator OFF

ODGOVOR (kratko): 1) šta si zatekao 2) šta si uradio i zašto 3) šta nisi i zašto.

Jezik: bosanski/hrvatski/srpski."""