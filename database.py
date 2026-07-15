from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import hashlib # Ci serve per non salvare il PIN in chiaro!

DATABASE_URL = "sqlite:///./database.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UtenteDB(Base):
    __tablename__ = "utenti"
    
    id = Column(Integer, primary_key=True, index=True)
    nickname = Column(String, unique=True, index=True)
    token = Column(String) 
    pin_hash = Column(String) # Qui salviamo l'hash del PIN (es: "81dc9bdb...")

class MessaggioDB(Base):
    __tablename__ = "messaggi"

    id = Column(Integer, primary_key=True, index=True)
    mittente = Column(String, index=True)
    contenuto_criptato = Column(String)
    data_invio = Column(DateTime, default=datetime.utcnow)

# Funzione di utilità per trasformare il PIN in un codice indecifrabile
def cifra_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()

def inizializza_db():
    Base.metadata.create_all(bind=engine)