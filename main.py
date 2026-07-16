from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import json
import os
from fastapi import File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
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
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 2. Diciamo a FastAPI di rendere accessibile la cartella "uploads" via browser
# Chiunque vada su http://localhost:3000/uploads/nomefile.pdf potrà scaricarlo!
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Per ora usiamo una lista temporanea in memoria per i test degli appunti
# (poi la collegheremo al database!)
# Lista temporanea che ora tiene traccia anche del tipo di appunto
bacheca_appunti = []

# Il tuo PIN da "Dio Informatico" (cambialo con quello che usi davvero!)
PIN_DIO_INFORMATICO = "1234" 

@app.post("/upload-appunti")
async def carica_appunto(
    titolo: str = Form(...),
    materia: str = Form(...),
    autore: str = Form(...),
    tipo: str = Form(...), # "dio" o "normale"
    pin: str = Form(None), # Il PIN passato dal frontend (opzionale per i normali)
    file: UploadFile = File(...)
):
    if not file.filename:
        return {"stato": "ERRORE", "messaggio": "Nessun file valido caricato."}

    # Blocco di sicurezza: se il tipo è "dio", serve il PIN corretto
    if tipo == "dio":
        if pin != PIN_DIO_INFORMATICO:
            return {"stato": "ERRORE", "messaggio": "Non sei il Dio Informatico! Accesso negato. ⚡"}
        # Forza l'autore a essere il tuo nome reale per evitare impersonificazioni
        autore = "Dio Informatico"

    try:
        percorso_file = os.path.join(UPLOAD_DIR, file.filename)
        
        with open(percorso_file, "wb") as buffer:
            contenuto = await file.read()
            buffer.write(contenuto)
            
        nuovo_appunto = {
            "id": len(bacheca_appunti) + 1,
            "titolo": titolo,
            "materia": materia,
            "autore": autore,
            "tipo": tipo, # Salviamo se è "dio" o "normale"
            "file_url": f"http://localhost:3000/uploads/{file.filename}"
        }
        
        bacheca_appunti.append(nuovo_appunto)
        return {"stato": "OK", "messaggio": "Appunto caricato con successo!", "appunto": nuovo_appunto}
        
    except Exception as e:
        return {"stato": "ERRORE", "messaggio": f"Errore: {str(e)}"}
@app.get("/lista-appunti")
async def ottieni_appunti():
    # Restituisce la lista di tutti gli appunti caricati
    return bacheca_appunti
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



# Lista temporanea in memoria per il calendario della classe
calendario_classe = []

# Il tuo PIN da "Dio Informatico" (assicurati che coincida con quello che usi per gli appunti!)
PIN_DIO_INFORMATICO = "1234" 

@app.post("/aggiungi-evento")
async def aggiungi_evento(
    titolo: str = Form(...),       # Es. "Compito in classe di Informatica"
    materia: str = Form(...),      # Es. "Informatica"
    data: str = Form(...),         # Data in formato YYYY-MM-DD
    tipo: str = Form(...),         # "verifica", "interrogazione", "compito"
    pin: str = Form(...)           # PIN di sicurezza obbligatorio
):
    if pin != PIN_DIO_INFORMATICO:
        return {"stato": "ERRORE", "messaggio": "Non hai i permessi per modificare il calendario! 🔐"}
        
    nuovo_evento = {
        "id": len(calendario_classe) + 1,
        "titolo": titolo,
        "materia": materia,
        "data": data,
        "tipo": tipo
    }
    
    calendario_classe.append(nuovo_evento)
    
    # Ordiniamo la lista per data, così i compiti più vicini appaiono sempre per primi!
    calendario_classe.sort(key=lambda x: x['data'])
    
    return {"stato": "OK", "messaggio": "Evento aggiunto al calendario!", "evento": nuovo_evento}

@app.get("/lista-eventi")
async def ottieni_eventi():
    return calendario_classe