TOOLS = [
    {
        "name": "get_all_sensors",
        "description": "Dohvati trenutno stanje svih senzora i uređaja u kući.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "_noop": {"type": "string", "description": "Ignorisi ovaj parametar."}
            },
            "additionalProperties": False
        }
    },
    {
        "name": "get_room_status",
        "description": "Dohvati stanje svih uređaja u određenoj prostoriji.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prostorija": {
                    "type": "string",
                    "description": "Naziv prostorije, npr. 'dnevna_soba'"
                }
            },
            "required": ["prostorija"],
            "additionalProperties": False
        }
    },
    {
        "name": "set_svjetlo",
        "description": "Upali ili ugasi svjetlo u prostoriji.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prostorija": {
                    "type": "string",
                    "description": "Naziv prostorije, npr. 'dnevna_soba'"
                },
                "komanda": {
                    "type": "string",
                    "enum": ["ON", "OFF"],
                    "description": "ON = upali, OFF = ugasi"
                }
            },
            "required": ["prostorija", "komanda"],
            "additionalProperties": False
        }
    },
    {
        "name": "set_ventilator",
        "description": "Upali ili ugasi ventilator u prostoriji.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prostorija": {
                    "type": "string",
                    "description": "Naziv prostorije, npr. 'dnevna_soba'"
                },
                "komanda": {
                    "type": "string",
                    "enum": ["ON", "OFF"],
                    "description": "ON = upali, OFF = ugasi"
                }
            },
            "required": ["prostorija", "komanda"],
            "additionalProperties": False
        }
    },
    {
        "name": "set_prozor",
        "description": "Otvori ili zatvori prozor/roletu u prostoriji.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prostorija": {
                    "type": "string",
                    "description": "Naziv prostorije, npr. 'dnevna_soba'"
                },
                "komanda": {
                    "type": "string",
                    "enum": ["ON", "OFF"],
                    "description": "ON = otvori, OFF = zatvori"
                }
            },
            "required": ["prostorija", "komanda"],
            "additionalProperties": False
        }
    },
    {
        "name": "set_termostat",
        "description": "Postavi željenu temperaturu termostata u prostoriji.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prostorija": {
                    "type": "string",
                    "description": "Naziv prostorije, npr. 'dnevna_soba'"
                },
                "temperatura": {
                    "type": "number",
                    "description": "Temperatura u Celzijusima, npr. 21"
                }
            },
            "required": ["prostorija", "temperatura"],
            "additionalProperties": False
        }
    },
    {
        "name": "detect_anomalies",
        "description": "Provjeri sve senzore i prijavi anomalije: dim, visoka/niska temperatura, otvoreni prozori, pokret.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "_noop": {"type": "string", "description": "Ignorisi ovaj parametar."}
            },
            "additionalProperties": False
        }
    },
    {
        "name": "upravljaj_uredjajem",
        "description": (
            "Direktna komanda na openHAB Item po njegovom TAČNOM nazivu "
            "(ne MQTT topic!). Koristi samo kad drugi toolovi nisu dovoljni "
            "(npr. uređaj koji nema dedicirani set_* tool). Naziv Itema mora "
            "biti tačan onako kako postoji u openHAB-u, npr. 'Dnevna_Soba_Ventilator' "
            "— provjeri get_all_sensors ili get_room_status da vidiš tačne nazive."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_name": {
                    "type": "string",
                    "description": "Tačan naziv openHAB Itema, npr. 'Dnevna_Soba_Ventilator'"
                },
                "komanda": {
                    "type": "string",
                    "description": "Vrijednost koju šaljemo, npr. 'ON' ili '21'"
                }
            },
            "required": ["item_name", "komanda"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_action_history",
        "description": "Dohvati listu zadnjih izvrsenih akcija agenta. Pozovi ovo da provjeriš šta je vec uradeno i izbjegneš ponavljanje.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "description": "Broj zadnjih akcija koje zelis vidjeti (default: 10, max: 50)"
                }
            },
            "additionalProperties": False
        }
    }
]