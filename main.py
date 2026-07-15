from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import json

from database import inizializza_db, SessionLocal, MessaggioDB, UtenteDB, cifra_pin

app = FastAPI()
inizializza_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

connessioni_attive: List[WebSocket] = []

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connessioni_attive.append(websocket)
    
    db = SessionLocal()
    try:
        cronologia = db.query(MessaggioDB).order_by(MessaggioDB.data_invio.asc()).limit(50).all()
        for msg in cronologia:
            await websocket.send_text(json.dumps({
                "mittente": msg.mittente,
                "contenuto": msg.contenuto_criptato,
                "storico": True
            }))
    finally:
        db.close()

    try:
        while True:
            dati_ricevuti = await websocket.receive_text()
            payload = json.loads(dati_ricevuti)
            
            tipo_azione = payload.get("azione", "messaggio") # "messaggio", "registra_pin", "verifica_pin"
            mittente = payload.get("mittente", "").strip()
            token = payload.get("token", "").strip()
            
            if not mittente or not token:
                continue

            db = SessionLocal()
            try:
                utente = db.query(UtenteDB).filter(UtenteDB.nickname == mittente).first()

                # --- CASO 1: NUOVO UTENTE (Richiesta di creazione PIN) ---
                if utente is None:
                    if tipo_azione == "registra_pin":
                        pin = payload.get("pin", "")
                        if len(pin) >= 4:
                            nuovo_utente = UtenteDB(
                                nickname=mittente, 
                                token=token, 
                                pin_hash=cifra_pin(pin)
                            )
                            db.add(nuovo_utente)
                            db.commit()
                            await websocket.send_text(json.dumps({"stato": "REGISTRATO", "info": "Nickname riservato con successo!"}))
                        else:
                            await websocket.send_text(json.dumps({"stato": "ERRORE_PIN", "info": "Il PIN deve essere di almeno 4 cifre!"}))
                    else:
                        # Diciamo al frontend che il nick è nuovo e serve un PIN
                        await websocket.send_text(json.dumps({"stato": "RICHIEDI_CREAZIONE_PIN"}))
                    continue

                # --- CASO 2: UTENTE ESISTENTE MA TOKEN DIVERSO (Richiesta Sblocco) ---
                if utente.token != token:
                    if tipo_azione == "verifica_pin":
                        pin_inserito = payload.get("pin", "")
                        if str(utente.pin_hash) != cifra_pin(pin_inserito):
                            # PIN Corretto! Aggiorniamo il token dell'utente autorizzando il nuovo dispositivo
                            utente.token = token
                            db.commit()
                            await websocket.send_text(json.dumps({"stato": "SBLOCCATO", "info": "Dispositivo autorizzato!"}))
                        else:
                            await websocket.send_text(json.dumps({"stato": "ERRORE_PIN", "info": "PIN errato! Accesso negato."}))
                    else:
                        # Chiediamo al frontend di mostrare il pop-up del PIN
                        await websocket.send_text(json.dumps({"stato": "RICHIEDI_SBLOCCO_PIN"}))
                    continue

                # --- CASO 3: TUTTO OK (Invio messaggio) ---
                if tipo_azione == "messaggio":
                    contenuto = payload.get("contenuto", "").strip()
                    if contenuto:
                        nuovo_msg = MessaggioDB(mittente=mittente, contenuto_criptato=contenuto)
                        db.add(nuovo_msg)
                        db.commit()
                        
                        for connessione in connessioni_attive:
                            await connessione.send_text(json.dumps({
                                "mittente": mittente,
                                "contenuto": contenuto,
                                "storico": False
                            }))
            except Exception as e:
                print(f"Errore: {e}")
            finally:
                db.close()
                    
    except WebSocketDisconnect:
        connessioni_attive.remove(websocket)