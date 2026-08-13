from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List, Optional
import json
import os
import time
from database import inizializza_db, SessionLocal, MessaggioDB, UtenteDB, cifra_pin
from supabase import create_client, Client

app = FastAPI()

# Configurazione Supabase con chiavi di fallback
SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://yuuubmiwsiiudbrameys.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or "sb_publishable_bkFPdaZx-LRYlSKv3MIceA_Qb3wdEy3"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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

# UNICO PIN DI CONTROLLO GENERALE
PIN_DIO_INFORMATICO = "0742" 

# Lista studenti fissa
studenti_classe = ["Forganni F.", "Galletta A.", "Ficarra G.", "Cucinotta D.", "Soraci A.", "Manganaro G.", "Boemi M.", "Bellinghieri P.", "Celeste G.", "Mazzeo G.", "Perrone E.", "Bertuccelli F.", "Alibrandi P.", "Spagnolo C.", "La Rosa G.", "Sansone M.", "Scalia S."]

calendario_classe = [] # Puoi spostarlo su Supabase in seguito se ti serve


# =========================================================================
# 1. SEZIONE INTERROGAZIONI (Permanente su Supabase Cloud)
# =========================================================================

@app.get("/dati-interrogazioni")
async def ottieni_dati_interrogazioni():
    try:
        in_coda_res = supabase.table("interrogazioni").select("*").eq("stato", "in_coda").order("created_at").execute()
        storico_res = supabase.table("interrogazioni").select("*").eq("stato", "completato").order("updated_at", desc=True).execute()
        
        return {
            "studenti": studenti_classe,
            "in_coda": in_coda_res.data,
            "storico": storico_res.data
        }
    except Exception as e:
        return {"studenti": studenti_classe, "in_coda": [], "storico": []}

@app.post("/aggiungi-in-coda")
async def aggiungi_in_coda(
    studente: str = Form(...),
    materia: str = Form(...),
    giorno: Optional[str] = Form(None),
    esclusi: Optional[str] = Form(None),
    pin: str = Form(...)
):
    if pin != PIN_DIO_INFORMATICO:
        return {"stato": "ERRORE", "messaggio": "PIN Errato! 🔐"}
    
    nota_esclusi = esclusi if esclusi and esclusi.strip() else "Nessuno"
    
    try:
        supabase.table("interrogazioni").insert({
            "studente": studente,
            "materia": materia,
            "giorno": giorno if giorno and giorno.strip() else "Da definire",
            "esclusi_al_giro": nota_esclusi,
            "stato": "in_coda"
        }).execute()
        return {"stato": "OK", "messaggio": f"{studente} aggiunto ai candidati di {materia}!"}
    except Exception as e:
        return {"stato": "ERRORE", "messaggio": str(e)}

@app.post("/sposta-a-storico")
async def sposta_a_storico(
    coda_id: int = Form(...),
    pin: str = Form(...),
    data_interrogazione: Optional[str] = Form(None)
):
    if pin != PIN_DIO_INFORMATICO:
        return {"stato": "ERRORE", "messaggio": "PIN Errato! 🔐"}
    
    try:
        supabase.table("interrogazioni").update({
            "stato": "completato",
            "data_completato": data_interrogazione if data_interrogazione else "Recentemente"
        }).eq("id", coda_id).execute()
        
        return {"stato": "OK", "messaggio": "Studente spostato nello storico!"}
    except Exception as e:
        return {"stato": "ERRORE", "messaggio": str(e)}


# =========================================================================
# 2. SEZIONE BACHECA APPUNTI (Con Cloud Storage Infinito per PDF/Foto)
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

    # LOGICA CORRETTA PER AUTORE
    if tipo == "dio":
        if pin != PIN_DIO_INFORMATICO:
            return {"stato": "ERRORE", "messaggio": "PIN Dio errato! 🔐"}
        autore_effettivo = "Dio Informatico"
    else:
        autore_effettivo = autore if autore and autore.strip() else "Studente Anonimo"

    try:
        nome_unico_file = f"{int(time.time())}-{file.filename}"
        contenuto_file = await file.read()

        # 1. Carica il file binario nel bucket Storage di Supabase
        supabase.storage.from_("appunti-files").upload(
            path=nome_unico_file,
            file=contenuto_file
        )

        # 2. Ottieni l'URL pubblico del file
        url_res = supabase.storage.from_("appunti-files").get_public_url(nome_unico_file)

        # 3. Salva i metadati nel database SQL di Supabase
        supabase.table("files_salvati").insert({
            "titolo": titolo,
            "materia": materia,
            "autore": autore_effettivo,
            "tipo": tipo,
            "url_file": url_res,
            "nome_originale": file.filename,
            "caricato_da": autore_effettivo
        }).execute()
        
        return {"stato": "OK", "messaggio": "Appunto caricato con successo!"}
        
    except Exception as e:
        return {"stato": "ERRORE", "messaggio": f"Errore Cloud: {str(e)}"}


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

                if utente.token != token:
                    if tipo_azione == "verifica_pin":
                        pin_inserito = payload.get("pin", "")
                        if str(utente.pin_hash) == cifra_pin(pin_inserito):
                            utente.token = token
                            db.commit()
                            await websocket.send_text(json.dumps({"stato": "SBLOCCATO", "info": "Dispositivo autorizzato!"}))
                        else:
                            await websocket.send_text(json.dumps({"stato": "ERRORE_PIN", "info": "PIN errato! Accesso negato."}))
                    else:
                        await websocket.send_text(json.dumps({"stato": "RICHIEDI_SBLOCCO_PIN"}))
                    continue

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