import asyncio
import json
import logging
import time
import uuid
from typing import Set

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# --- Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("F1MockServer")

app = FastAPI()

# CORS pour autoriser tout le monde
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Constantes & État ---
class ChaosManager:
    def __init__(self):
        self.should_kill_connections = False
        self.is_frozen = False


chaos = ChaosManager()

# --- Endpoints Chaos ---


@app.get("/chaos/kill")
async def chaos_kill():
    """Coupe brutalement toutes les connexions."""
    chaos.should_kill_connections = True
    logger.warning(">>> CHAOS: KILL ACTIVÉ")
    return {"status": "Kill signal sent"}


@app.get("/chaos/freeze")
async def chaos_freeze():
    """Gèle l'envoi de données (simulation lag)."""
    chaos.is_frozen = not chaos.is_frozen
    status = "FROZEN" if chaos.is_frozen else "ACTIVE"
    logger.warning(f">>> CHAOS: FLUX {status}")
    return {"status": f"Stream is {status}"}


# --- SignalR Legacy Endpoints ---


@app.get("/signalr/negotiate")
async def negotiate(request: Request):
    """
    Endpoint de négociation compatible avec l'ancien client F1.
    Répond à GET /signalr/negotiate
    """
    logger.info("Négociation reçue (Legacy).")
    # Le format exact attendu par les vieux clients SignalR
    data = {
        "Url": "/signalr",
        "ConnectionToken": str(uuid.uuid4()),
        "ConnectionId": str(uuid.uuid4()),
        "KeepAliveTimeout": 20.0,
        "DisconnectTimeout": 30.0,
        "ConnectionTimeout": 110.0,
        "TryWebSockets": True,
        "ProtocolVersion": "1.5",
        "TransportConnectTimeout": 5.0,
        "LogToConsole": True,
    }
    return JSONResponse(content=data)


@app.websocket("/signalr/connect")
async def websocket_endpoint(websocket: WebSocket):
    """
    Endpoint WebSocket compatible avec l'URL /signalr/connect
    """
    await websocket.accept()
    client_id = str(uuid.uuid4())[:8]
    logger.info(f"Client {client_id} connecté via WebSocket.")

    try:
        # 1. Attente du message "Subscribe" (Logique du script original)
        # Le client F1 envoie généralement un premier message pour s'abonner
        try:
            subscribe_raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
            subscribe_msg = json.loads(subscribe_raw)

            if subscribe_msg.get("M") == "Subscribe":
                logger.info(
                    f"Client {client_id} a envoyé 'Subscribe'. Démarrage du flux."
                )
            else:
                logger.warning(
                    f"Message inattendu du client {client_id}: {subscribe_msg}"
                )
        except asyncio.TimeoutError:
            logger.warning(f"Client {client_id} n'a pas envoyé Subscribe à temps.")
            await websocket.close()
            return

        # 2. Boucle d'envoi des données
        msg_count = 1

        while True:
            # --- CHAOS: KILL ---
            if chaos.should_kill_connections:
                logger.warning(f"Kill switch activé pour {client_id}")
                await websocket.close(code=1011)  # Erreur serveur interne simulée
                break

            # --- CHAOS: FREEZE ---
            if not chaos.is_frozen:
                # Format du message F1 (Legacy)
                # Structure: {"M": [{"H": "Streaming", "M": "feed", "A": [...]}]}
                payload_data = (
                    f"Mock data #{msg_count} for {client_id} at {time.time():.2f}"
                )

                message = {"M": [{"H": "Streaming", "M": "feed", "A": [payload_data]}]}

                await websocket.send_text(json.dumps(message))
                logger.info(f"Envoyé msg #{msg_count} à {client_id}")
                msg_count += 1
            else:
                # Si gelé, on n'envoie rien (même pas de ping applicatif ici,
                # on laisse le ping TCP/WebSocket gérer le keepalive bas niveau)
                pass

            # Gestion des messages entrants (Ping du client, etc.) sans bloquer
            try:
                # On écoute brièvement pour voir si le client parle ou ferme
                req = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                # Si on reçoit quelque chose, on l'ignore ou on log
            except asyncio.TimeoutError:
                pass  # Timeout normal, on continue la boucle

    except WebSocketDisconnect:
        logger.info(f"Client {client_id} déconnecté.")
    except Exception as e:
        logger.error(f"Erreur client {client_id}: {e}")
    finally:
        # Reset automatique du kill switch si c'était le dernier client (optionnel)
        if chaos.should_kill_connections:
            chaos.should_kill_connections = False


if __name__ == "__main__":
    print("Serveur F1 Mock (Compatibilité Legacy) démarré sur port 8080")
    uvicorn.run(app, host="0.0.0.0", port=8080)
