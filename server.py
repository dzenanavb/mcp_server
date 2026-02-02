import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import paho.mqtt.client as mqtt

# -------------------------------------------------
# Logging
# -------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smart-home-mcp")

# -------------------------------------------------
# MQTT setup with try-except
# -------------------------------------------------
mqtt_client = mqtt.Client(protocol=mqtt.MQTTv311)  # koristi MQTTv311 da izbaci warning

try:
    mqtt_client.connect("127.0.0.1", 1883, 60)
    mqtt_client.loop_start()
    logger.info("MQTT broker connected")
except Exception as e:
    logger.error(f"Ne mogu se spojiti na MQTT broker: {e}")

# -------------------------------------------------
# MCP HTTP Handler
# -------------------------------------------------
class MCPHandler(BaseHTTPRequestHandler):

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)

        method = data.get("method")
        req_id = data.get("id")

        logger.info(f"MCP method: {method}")

        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "SmartHome", "version": "1.0"}
                }
            }

        elif method == "notifications/initialized":
            response = {"jsonrpc": "2.0", "id": req_id, "result": {}}

        elif method == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "upravljaj_uredjajem",
                            "description": "Upali ili ugasi uređaj preko MQTT-a",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "uredjaj_id": {"type": "string"},
                                    "komanda": {"type": "string", "enum": ["ON", "OFF"]}
                                },
                                "required": ["uredjaj_id", "komanda"]
                            }
                        }
                    ]
                }
            }

        elif method == "tools/call":
            args = data.get("params", {}).get("arguments", {})
            uredjaj_id = args.get("uredjaj_id")
            komanda = args.get("komanda")

            logger.info(f"MQTT publish -> {uredjaj_id} : {komanda}")

            # Pokušaj publish, ali ne ruši server ako ne ide
            try:
                mqtt_client.publish(f"cmnd/{uredjaj_id}/POWER", komanda)
            except Exception as e:
                logger.error(f"MQTT publish failed: {e}")

            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {"type": "text", "text": f"OK ✅ {uredjaj_id} -> {komanda}"}
                    ]
                }
            }

        else:
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": "Unknown method"}
            }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode("utf-8"))

# -------------------------------------------------
# Start server
# -------------------------------------------------
if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 5000), MCPHandler)
    logger.info("SmartHome MCP server running on http://0.0.0.0:5000")
    server.serve_forever()
