from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List, Optional
import json
import os
import time
from database import inizializza_db, SessionLocal, MessaggioDB, UtenteDB, cifra_pin
from supabase import create_client, Client
from fastapi.responses import FileResponse
from fastapi import FastAPI, HTTPException
app = FastAPI()
@app.get("/manifest.json")
async def get_manifest():
    return FileResponse("manifest.json")

@app.get("/sw.js")
async def get_sw():
    return FileResponse("sw.js", media_type="application/javascript")

@app.get("/icon.png")
async def get_icon():
    return FileResponse("icon.png")
# =========================================================================
# CONFIGURAZIONE SUPABASE
# =========================================================================
# NOTA: usa sempre variabili d'ambiente in produzione. Le chiavi qui sotto
# sono solo fallback per lo sviluppo locale.
SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://yuuubmiwsiiudbrameys.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or "sb_publishable_bkFPdaZx-LRYlSKv3MIceA_Qb3wdEy3"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

BUCKET_NAME = "appunti-files"
@app.get("/health-supabase")
async def health_supabase():
    try:
        # Query semplice e pulita che sveglia Supabase senza argomenti complessi
        response = supabase.table("eventi").select("*").limit(1).execute()
        return {"status": "online", "supabase": "connected"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
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

# PIN spostato in variabile d'ambiente: NON lasciare il valore reale nel
# codice sorgente se il repository è (o potrebbe diventare) pubblico.
PIN_DIO_INFORMATICO = ( "0742")

studenti_classe = ["Forganni F.", "Galletta A.", "Ficarra G.", "Cucinotta D.", "Soraci A.", "Manganaro G.", "Boemi M.", "Bellinghieri P.", "Celeste G.", "Mazzeo G.", "Perrone E.", "Bertuccelli F.", "Alibrandi P.", "Spagnolo C.", "La Rosa G.", "Sansone M.", "Scalia S."]

calendario_classe = []


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
        print(f"[dati-interrogazioni] ERRORE: {e}")
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
        print(f"[aggiungi-in-coda] ERRORE: {e}")
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
        print(f"[sposta-a-storico] ERRORE: {e}")
        return {"stato": "ERRORE", "messaggio": str(e)}


# =========================================================================
# 2. SEZIONE BACHECA APPUNTI (Con Cloud Storage su Supabase)
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
            return {"stato": "ERRORE", "messaggio": "PIN Dio errato! 🔐"}
        autore_effettivo = "Dio Informatico"
    else:
        autore_effettivo = autore if autore and autore.strip() else "Studente Anonimo"

    try:
        # Nome file sicuro: rimuove spazi/caratteri che possono rompere l'URL
        nome_pulito = "".join(c for c in file.filename if c.isalnum() or c in "._-")
        nome_unico_file = f"{int(time.time())}-{nome_pulito}"

        contenuto_file = await file.read()

        if not contenuto_file:
            return {"stato": "ERRORE", "messaggio": "Il file caricato è vuoto."}

        # 1. Carica il file binario nel bucket Storage di Supabase,
        #    specificando il content-type così il browser lo visualizza
        #    correttamente invece di scaricarlo o mostrarlo come testo.
        supabase.storage.from_(BUCKET_NAME).upload(
            path=nome_unico_file,
            file=contenuto_file,
            file_options={
                "content-type": file.content_type or "application/octet-stream",
                "upsert": "true"
            }
        )

        # 2. Ottieni l'URL pubblico del file.
        #    NB: funziona solo se il bucket "appunti-files" è impostato
        #    come PUBLIC su Supabase Dashboard -> Storage -> bucket -> Make public.
        url_res = supabase.storage.from_(BUCKET_NAME).get_public_url(nome_unico_file)

        # get_public_url può restituire una stringa o un oggetto a seconda
        # della versione della libreria: normalizziamo qui.
        if isinstance(url_res, dict):
            url_pubblico = url_res.get("publicUrl") or url_res.get("publicURL") or str(url_res)
        else:
            url_pubblico = str(url_res)

        # 3. Salva i metadati nel database SQL di Supabase
        supabase.table("files_salvati").insert({
            "titolo": titolo,
            "materia": materia,
            "autore": autore_effettivo,
            "tipo": tipo,
            "url_file": url_pubblico,
            "nome_originale": file.filename,
            "caricato_da": autore_effettivo
        }).execute()

        return {"stato": "OK", "messaggio": "Appunto caricato con successo!"}

    except Exception as e:
        print(f"[upload-appunti] ERRORE: {e}")
        return {"stato": "ERRORE", "messaggio": f"Errore Cloud: {str(e)}"}


@app.get("/lista-appunti")
async def ottieni_appunti():
    try:
        res = supabase.table("files_salvati").select("*").order("id", desc=True).execute()
        return res.data  # array puro, come /lista-eventi
    except Exception as e:
        print(f"[lista-appunti] ERRORE: {e}")
        return []


# =========================================================================
# 3. SEZIONE CALENDARIO COMPITI
# =========================================================================

# --- SEZIONE CALENDARIO COMPITI (PERSISTENTE) ---

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
    
    try:
        # Ora punta alla tabella 'eventi'
        supabase.table("eventi").insert({
            "titolo": titolo,
            "materia": materia,
            "data": data,
            "tipo": tipo
        }).execute()
        
        return {"stato": "OK", "messaggio": "Evento salvato nel cloud!"}
    except Exception as e:
        return {"stato": "ERRORE", "messaggio": str(e)}

@app.get("/lista-eventi")
async def ottieni_eventi():
    try:
        # Ora legge dalla tabella 'eventi'
        res = supabase.table("eventi").select("*").order("data").execute()
        return res.data
    except Exception as e:
        return []

@app.post("/elimina-evento")
async def elimina_evento(
    evento_id: int = Form(...),
    pin: str = Form(...)
):
    if pin != PIN_DIO_INFORMATICO:
        return {"stato": "ERRORE", "messaggio": "Non autorizzato! 🔐"}
    
    try:
        # Elimina dalla tabella 'eventi'
        supabase.table("eventi").delete().eq("id", evento_id).execute()
        return {"stato": "OK", "messaggio": "Evento rimosso con successo!"}
    except Exception as e:
        return {"stato": "ERRORE", "messaggio": str(e)}




# =========================================================================
# 4. CHAT LIVE (SUPABASE CLOUD PERSISTENT)
# =========================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connessioni_attive.append(websocket)
    
    try:
        res = supabase.table("messaggi").select("*").order("created_at", desc=False).limit(50).execute()
        cronologia = res.data if res.data else []
        
        for msg in cronologia:
            if isinstance(msg, dict):
                mittente_val = str(msg.get("mittente", ""))
                contenuto_val = str(msg.get("contenuto", ""))
            else:
                mittente_val = str(getattr(msg, "mittente", ""))
                contenuto_val = str(getattr(msg, "contenuto", ""))
            
            await websocket.send_text(json.dumps({
                "mittente": mittente_val,
                "contenuto": contenuto_val,
                "storico": True
            }))
    except Exception as e:
        print(f"Errore nel caricamento cronologia chat: {e}")

    try:
        while True:
            dati_ricevuti = await websocket.receive_text()
            payload = json.loads(dati_ricevuti)
            
            mittente = payload.get("mittente", "").strip()
            contenuto = payload.get("contenuto", "").strip()
            
            if not mittente or not contenuto:
                continue

            try:
                supabase.table("messaggi").insert({
                    "mittente": mittente,
                    "contenuto": contenuto
                }).execute()
                
                for connessione in connessioni_attive:
                    await connessione.send_text(json.dumps({
                        "mittente": mittente,
                        "contenuto": contenuto,
                        "storico": False
                    }))
            except Exception as e:
                print(f"Errore nel salvataggio/invio messaggio WS: {e}")
                    
    except WebSocketDisconnect:
        connessioni_attive.remove(websocket)