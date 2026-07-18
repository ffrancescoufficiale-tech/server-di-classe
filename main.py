from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List, Optional
import json
import os
from database import inizializza_db, SessionLocal, MessaggioDB, UtenteDB, cifra_pin

app = FastAPI()

@app.get("/")
async def home_test():
    return {"messaggio": "Il server funziona ed è il file corretto!"}
inizializza_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURAZIONI GLOBALI ---
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

connessioni_attive: List[WebSocket] = []

# UNICO PIN DI CONTROLLO GENERALE (Usa questo per tutto: appunti, interrogazioni, calendario)
PIN_DIO_INFORMATICO = "0742" 


# --- STATO IN MEMORIA (Temporaneo prima del DB) ---
bacheca_appunti = []
calendario_classe = []

# Tabelle per le Interrogazioni
studenti_classe = ["Forganni F.", "Galletta A.", "Ficarra G.", "Cucinotta D.", "Soraci A.", "Manganaro G.", "Boemi M.", "Bellinghieri P.", "Celeste G.", "Mazzeo G.", "Perrone E.", "Bertuccelli F.", "Alibrandi P.", "Spagnolo C.", "La Rosa G.", "Sansone M.", "Scalia S."]
interrogazioni_in_coda = []
storico_interrogazioni = []

id_coda_counter = 1
id_storico_counter = 1


# =========================================================================
# 1. SEZIONE INTERROGAZIONI (Flusso Coda -> Storico con ultimi in evidenza)
# =========================================================================

@app.get("/dati-interrogazioni")
async def ottieni_dati_interrogazioni():
    return {
        "studenti": studenti_classe,
        "in_coda": interrogazioni_in_coda,
        "storico": storico_interrogazioni
    }

@app.post("/aggiungi-in-coda")
async def aggiungi_in_coda(
    studente: str = Form(...),
    materia: str = Form(...),
    giorno: Optional[str] = Form(None),
    esclusi: Optional[str] = Form(None), # <--- Nuova stringa ricevuta dal frontend
    pin: str = Form(...)
):
    global id_coda_counter
    if pin != PIN_DIO_INFORMATICO:
        return {"stato": "ERRORE", "messaggio": "PIN Errato! 🔐"}
    
    # Se ci sono esclusi, creiamo una nota pulita, altrimenti scriviamo "Nessuno"
    nota_esclusi = esclusi if esclusi and esclusi.strip() else "Nessuno"
    
    nuovo = {
        "id": id_coda_counter,
        "studente": studente,
        "materia": materia,
        "giorno": giorno if giorno and giorno.strip() else "Da definire",
        "esclusi_al_giro": nota_esclusi # <--- Salviamo il record
    }
    interrogazioni_in_coda.append(nuovo)
    id_coda_counter += 1
    return {"stato": "OK", "messaggio": f"{studente} aggiunto ai candidati di {materia}!"}

@app.post("/sposta-a-storico")
async def sposta_a_storico(
    coda_id: int = Form(...),
    pin: str = Form(...),
    data_interrogazione: Optional[str] = Form(None) # <--- Riceve la data dal frontend
):
    global id_storico_counter
    if pin != PIN_DIO_INFORMATICO:
        return {"stato": "ERRORE", "messaggio": "PIN Errato! 🔐"}
    
    for item in interrogazioni_in_coda:
        if item["id"] == coda_id:
            interrogazioni_in_coda.remove(item)
            
            archiviato = {
                "id": id_storico_counter,
                "studente": item["studente"],
                "materia": item["materia"],
                # Se il frontend passa la data usiamo quella, altrimenti fallback su "Recentemente"
                "data_completato": data_interrogazione if data_interrogazione else "Recentemente",
                "esclusi_al_giro": item.get("esclusi_al_giro", "Nessuno")
            }
            storico_interrogazioni.insert(0, archiviato) 
            id_storico_counter += 1
            return {"stato": "OK", "messaggio": "Studente spostato nello storico!"}
            
    return {"stato": "ERRORE", "messaggio": "Elemento non trovato in coda."}

# =========================================================================
# 2. SEZIONE BACHECA APPUNTI
# =========================================================================

@app.post("/upload-appunti")
async def carica_appunto(
    titolo: str = Form(...),
    materia: str = Form(...),
    autore: str = Form(...),
    tipo: str = Form(...), 
    pin: Optional[str] = Form(None), 
    file: UploadFile = File(...)
):
    if not file.filename:
        return {"stato": "ERRORE", "messaggio": "Nessun file valido caricato."}

    if tipo == "dio":
        if pin != PIN_DIO_INFORMATICO:
            return {"stato": "ERRORE", "messaggio": "Non sei il Dio Informatico! Accesso negato. ⚡"}
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
            "tipo": tipo, 
            "file_url": f"https://server-di-classe.onrender.com/uploads/{file.filename}"
        }
        
        bacheca_appunti.append(nuovo_appunto)
        return {"stato": "OK", "messaggio": "Appunto caricato con successo!", "appunto": nuovo_appunto}
        
    except Exception as e:
        return {"stato": "ERRORE", "messaggio": f"Errore: {str(e)}"}

@app.get("/lista-appunti")
async def ottieni_appunti():
    return bacheca_appunti


# =========================================================================
# 3. SEZIONE CALENDARIO COMPITI
# =========================================================================

@app.post("/aggiungi-evento")
async def aggiungi_evento(
    titolo: str = Form(...),       
    materia: str = Form(...),      
    data: str = Form(...),         
    tipo: str = Form(...),         
    pin: str = Form(...)           
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
    calendario_classe.sort(key=lambda x: x['data'])
    
    return {"stato": "OK", "messaggio": "Evento aggiunto al calendario!", "evento": nuovo_evento}

@app.get("/lista-eventi")
async def ottieni_eventi():
    return calendario_classe


# =========================================================================
# 4. CHAT LIVE (WEBSOCKET & DB SECURITY)
# =========================================================================

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
            
            tipo_azione = payload.get("azione", "messaggio") 
            mittente = payload.get("mittente", "").strip()
            token = payload.get("token", "").strip()
            
            if not mittente or not token:
                continue

            db = SessionLocal()
            try:
                utente = db.query(UtenteDB).filter(UtenteDB.nickname == mittente).first()

                # --- CASO 1: NUOVO UTENTE (Creazione PIN dispositivo) ---
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
                        await websocket.send_text(json.dumps({"stato": "RICHIEDI_CREAZIONE_PIN"}))
                    continue

                # --- CASO 2: UTENTE ESISTENTE MA DISPOSITIVO DIVERSO (Sblocco) ---
                if utente.token != token:
                    if tipo_azione == "verifica_pin":
                        pin_inserito = payload.get("pin", "")
                        # NOTA: qui ho corretto la logica di controllo hash che avevi invertito
                        if str(utente.pin_hash) == cifra_pin(pin_inserito):
                            utente.token = token
                            db.commit()
                            await websocket.send_text(json.dumps({"stato": "SBLOCCATO", "info": "Dispositivo autorizzato!"}))
                        else:
                            await websocket.send_text(json.dumps({"stato": "ERRORE_PIN", "info": "PIN errato! Accesso negato."}))
                    else:
                        await websocket.send_text(json.dumps({"stato": "RICHIEDI_SBLOCCO_PIN"}))
                    continue

                # --- CASO 3: INVIO MESSAGGIO AUTORIZZATO ---
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
                print(f"Errore nella gestione della richiesta WS: {e}")
            finally:
                db.close()
                    
    except WebSocketDisconnect:
        connessioni_attive.remove(websocket)

#speriamo funzioniiii