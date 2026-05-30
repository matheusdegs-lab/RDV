from fastapi import FastAPI, Request, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from reportlab.lib.utils import simpleSplit, ImageReader
from reportlab.lib.pagesizes import A4

from datetime import datetime
import hashlib
import base64
import os
import json
from apscheduler.schedulers.background import BackgroundScheduler
from supabase import create_client

from sqlalchemy import create_engine
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Session

from reportlab.pdfgen import canvas

from passlib.context import CryptContext

# =========================
# PASTAS
# =========================

os.makedirs("uploads", exist_ok=True)
os.makedirs("pdfs", exist_ok=True)

# =========================
# APP
# =========================

app = FastAPI()

# =========================
# HEADERS SEM CACHE
# =========================

@app.middleware("http")
async def disable_cache(request: Request, call_next):

    response = await call_next(request)

    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return response

app.mount(
    "/uploads",
    StaticFiles(directory="uploads"),
    name="uploads"
)

templates = Jinja2Templates(
    directory="templates"
)

# =========================
# BANCO DE DADOS
# =========================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./database.db"
)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )

if DATABASE_URL.startswith("sqlite"):

    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )

else:

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True
    )

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

pwd = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

supabase = None

if SUPABASE_URL and SUPABASE_SERVICE_KEY:
    supabase = create_client(
        SUPABASE_URL,
        SUPABASE_SERVICE_KEY
    )


def upload_storage(bucket, caminho_local, nome_destino):

    if not supabase:
        return ""

    try:

        with open(caminho_local, "rb") as f:

            supabase.storage.from_(bucket).upload(
                nome_destino,
                f,
                {"upsert": "true"}
            )

        return supabase.storage.from_(bucket).get_public_url(
            nome_destino
        )

    except Exception as e:

        print("Erro Storage:", e)

        return ""

# =========================
# GET DB
# =========================

def get_db():

    db = SessionLocal()

    try:

        yield db

    finally:

        db.close()

# =========================
# TABELA USUÁRIOS
# =========================

class Usuario(Base):

    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)

    usuario = Column(String)

    senha = Column(String)

    admin = Column(Integer, default=0)

    pode_clientes = Column(Integer, default=0)

    pode_colaborador = Column(Integer, default=0)
    
    ativo = Column(Integer, default=1)

    cliente_id = Column(Integer, default=0)

# =========================
# TABELA CLIENTES
# =========================

class Cliente(Base):

    __tablename__ = "clientes"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    nome = Column(String)

    telefone = Column(String)

    cnpj = Column(String)

    endereco = Column(String)

    ativo = Column(Integer, default=1)

# =========================
# TABELA TORRES
# =========================

class Torre(Base):

    __tablename__ = "torres"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    nome = Column(String)

    cliente_id = Column(Integer)

    numero_serie = Column(String)

    qtd_litros = Column(String)

    foto_perfil = Column(String)

# =========================
# TABELA RELATORIOS
# =========================

class Relatorio(Base):

    __tablename__ = "relatorios"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    numero = Column(String)

    cliente = Column(String)

    torre = Column(String)

    tecnico = Column(String)

    observacoes = Column(String)

    assinatura = Column(String)

    foto = Column(String)

    data_criacao = Column(String)

    status = Column(String)

    hash_relatorio = Column(String)


# =========================
# TABELA HISTÓRICO DE RELATÓRIOS
# =========================

class HistoricoRelatorio(Base):

    __tablename__ = "historico_relatorios"

    id = Column(Integer, primary_key=True, index=True)

    relatorio_id = Column(Integer)

    usuario = Column(String)

    alteracao = Column(String)

    valor_antigo = Column(String)

    valor_novo = Column(String)

    data_hora = Column(String)

# =========================
# CRIAR TABELAS
# =========================

Base.metadata.create_all(bind=engine)

# =========================
# AJUSTES DE COLUNAS EM BANCO EXISTENTE
# =========================

def garantir_coluna(tabela, coluna, tipo):

    # Ajuste automático de colunas antigas apenas para SQLite local.
    # No PostgreSQL/Supabase, as colunas já são criadas pelo Base.metadata.create_all().
    if not DATABASE_URL.startswith("sqlite"):

        return

    try:

        with engine.connect() as conn:

            colunas = [
                linha[1]
                for linha in conn.exec_driver_sql(
                    f"PRAGMA table_info({tabela})"
                ).fetchall()
            ]

            if coluna not in colunas:

                conn.exec_driver_sql(
                    f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}"
                )

                conn.commit()

    except Exception as e:

        print(f"Aviso: não foi possível garantir coluna {coluna} em {tabela}:", e)

garantir_coluna("clientes", "ativo", "INTEGER DEFAULT 1")
garantir_coluna("usuarios", "cliente_id", "INTEGER DEFAULT 0")
garantir_coluna("torres", "numero_serie", "VARCHAR")
garantir_coluna("torres", "qtd_litros", "VARCHAR")
garantir_coluna("torres", "foto_perfil", "VARCHAR")

# =========================
# CRIAR ADMIN PADRÃO
# =========================

db = SessionLocal()

admin_existe = db.query(Usuario).filter(
    Usuario.usuario == "admin"
).first()

if not admin_existe:

    admin = Usuario(

    usuario="admin",

    senha=pwd.hash(
        "admin123"
    ),

    admin=1,

    pode_clientes=1,

    pode_colaborador=1
)

    db.add(admin)

    db.commit()

db.close()

def gerar_backup_diario():

    if not supabase:
        print("Supabase não configurado. Backup ignorado.")
        return

    db = SessionLocal()

    try:

        backup = {
            "data_backup": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

            "usuarios": [
                {
                    "id": u.id,
                    "usuario": u.usuario,
                    "senha": u.senha,
                    "admin": u.admin,
                    "pode_clientes": u.pode_clientes,
                    "pode_colaborador": u.pode_colaborador,
                    "ativo": u.ativo,
                    "cliente_id": u.cliente_id
                }
                for u in db.query(Usuario).all()
            ],

            "clientes": [
                {
                    "id": c.id,
                    "nome": c.nome,
                    "telefone": c.telefone,
                    "cnpj": c.cnpj,
                    "endereco": c.endereco,
                    "ativo": c.ativo
                }
                for c in db.query(Cliente).all()
            ],

            "torres": [
                {
                    "id": t.id,
                    "nome": t.nome,
                    "cliente_id": t.cliente_id,
                    "numero_serie": t.numero_serie,
                    "qtd_litros": t.qtd_litros,
                    "foto_perfil": t.foto_perfil
                }
                for t in db.query(Torre).all()
            ],

            "relatorios": [
                {
                    "id": r.id,
                    "numero": r.numero,
                    "cliente": r.cliente,
                    "torre": r.torre,
                    "tecnico": r.tecnico,
                    "observacoes": r.observacoes,
                    "assinatura": r.assinatura,
                    "foto": r.foto,
                    "data_criacao": r.data_criacao,
                    "status": r.status,
                    "hash_relatorio": r.hash_relatorio
                }
                for r in db.query(Relatorio).all()
            ],

            "historico_relatorios": [
                {
                    "id": h.id,
                    "relatorio_id": h.relatorio_id,
                    "usuario": h.usuario,
                    "alteracao": h.alteracao,
                    "valor_antigo": h.valor_antigo,
                    "valor_novo": h.valor_novo,
                    "data_hora": h.data_hora
                }
                for h in db.query(HistoricoRelatorio).all()
            ]
        }

        nome_backup = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        caminho_backup = f"/tmp/{nome_backup}"

        with open(caminho_backup, "w", encoding="utf-8") as f:
            json.dump(backup, f, ensure_ascii=False, indent=2)

        upload_storage(
            "backups",
            caminho_backup,
            nome_backup
        )

        print("Backup enviado para Supabase Storage:", nome_backup)

    except Exception as e:

        print("Erro ao gerar backup:", e)

    finally:

        db.close()


scheduler = BackgroundScheduler()
scheduler.add_job(
    gerar_backup_diario,
    "cron",
    hour=3,
    minute=0
)
scheduler.start()

# =========================
# LOGIN PAGE
# =========================

@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):

    erro = request.query_params.get("erro")

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "request": request,
            "erro": erro
        }
    )


# =========================
# LOGIN
# =========================

@app.post("/login")
def login(

    usuario: str = Form(""),
    senha: str = Form("")

):

    if usuario == "" or senha == "":

        return RedirectResponse(
            url="/",
            status_code=302
        )

    db = SessionLocal()

    usuario_db = db.query(Usuario).filter(
        Usuario.usuario == usuario
    ).first()

    if not usuario_db:

        db.close()

        return RedirectResponse(
            url="/?erro=login",
            status_code=302
        )

    if usuario_db.ativo != 1:

        db.close()

        return RedirectResponse(
            url="/?erro=desabilitado",
            status_code=302
        )

    senha_correta = pwd.verify(
        senha[:72],
        usuario_db.senha
    )

    if not senha_correta:

        db.close()

        return RedirectResponse(
            url="/?erro=login",
            status_code=302
        )

    response = RedirectResponse(
        url="/dashboard",
        status_code=302
    )

    response.set_cookie("usuario", usuario_db.usuario)
    response.set_cookie("admin", str(usuario_db.admin))
    response.set_cookie("pode_clientes", str(usuario_db.pode_clientes))
    response.set_cookie("pode_colaborador", str(usuario_db.pode_colaborador))
    response.set_cookie("cliente_id", str(usuario_db.cliente_id or 0))

    db.close()

    return response

# =========================
# LOGOUT
# =========================

@app.get("/logout")
def logout():

    response = RedirectResponse(
        url="/",
        status_code=302
    )

    response.delete_cookie("usuario")
    response.delete_cookie("admin")
    response.delete_cookie("pode_clientes")
    response.delete_cookie("pode_colaborador")
    response.delete_cookie("cliente_id")

    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return response

# =========================
# DASHBOARD
# =========================

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):

    if not request.cookies.get("usuario"):

        return RedirectResponse(
            url="/",
            status_code=302
        )

    if (
        request.cookies.get("admin") != "1"
        and request.cookies.get("pode_clientes") != "1"
        and request.cookies.get("pode_colaborador") != "1"
    ):

        return RedirectResponse(
            url="/",
            status_code=302
        )

    db = SessionLocal()

    relatorios = []

    if request.cookies.get("admin") == "1" or request.cookies.get("pode_colaborador") == "1":

        relatorios = db.query(Relatorio).all()

    else:

        cliente_id_cookie = request.cookies.get("cliente_id")

        cliente_vinculado = None

        if cliente_id_cookie and cliente_id_cookie != "0":

            cliente_vinculado = db.query(Cliente).filter(
                Cliente.id == int(cliente_id_cookie)
            ).first()

        if cliente_vinculado:

            relatorios = db.query(Relatorio).filter(
                Relatorio.cliente == cliente_vinculado.nome
            ).all()

    relatorio_ids = [r.id for r in relatorios]

    historicos = []

    if relatorio_ids:

        historicos = db.query(HistoricoRelatorio).filter(
            HistoricoRelatorio.relatorio_id.in_(relatorio_ids)
        ).order_by(HistoricoRelatorio.id.desc()).all()

    historicos_dict = {}

    for historico in historicos:

        if historico.relatorio_id not in historicos_dict:

            historicos_dict[historico.relatorio_id] = []

        historicos_dict[historico.relatorio_id].append(historico)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "relatorios": relatorios,
            "historicos_dict": historicos_dict,
            "admin": request.cookies.get("admin"),
            "pode_clientes": request.cookies.get("pode_clientes"),
            "pode_colaborador": request.cookies.get("pode_colaborador")
        }
    )

# =========================
# CLIENTES
# =========================

@app.get("/clientes", response_class=HTMLResponse)
def clientes(request: Request):

    if not request.cookies.get("usuario"):

        return RedirectResponse(
            url="/",
            status_code=302
        )

    if request.cookies.get("admin") != "1" and request.cookies.get("pode_colaborador") != "1":

        return RedirectResponse(
            url="/dashboard",
            status_code=302
        )

    db = SessionLocal()

    clientes = db.query(Cliente).all()

    return templates.TemplateResponse(
        request,
        "clientes.html",
        {
            "request": request,
            "clientes": clientes,
            "admin": request.cookies.get("admin"),
            "pode_clientes": request.cookies.get("pode_clientes"),
            "pode_colaborador": request.cookies.get("pode_colaborador")
        }
    )

@app.post("/clientes")
def salvar_cliente(

    nome: str = Form(...),
    telefone: str = Form(...),
    cnpj: str = Form(...),
    endereco: str = Form(""),
    numero: str = Form(""),
    bairro: str = Form(""),
    cidade: str = Form(""),
    uf: str = Form("")

):

    db = SessionLocal()

    endereco_completo = endereco

    if numero or bairro or cidade or uf:

        endereco_completo = f"{endereco}, {numero} - {bairro} / {cidade}-{uf}"

    cliente = Cliente(

        nome=nome,
        telefone=telefone,
        cnpj=cnpj,
        endereco=endereco_completo,
        ativo=1
    )

    db.add(cliente)

    db.commit()

    db.close()

    return RedirectResponse(
        url="/clientes",
        status_code=302
    )

@app.post("/editar_cliente/{cliente_id}")
def editar_cliente(

    cliente_id: int,
    nome: str = Form(...),
    telefone: str = Form(...),
    cnpj: str = Form(...),
    endereco: str = Form(""),
    numero: str = Form(""),
    bairro: str = Form(""),
    cidade: str = Form(""),
    uf: str = Form("")

):

    db = SessionLocal()

    cliente = db.query(Cliente).filter(
        Cliente.id == cliente_id
    ).first()

    if cliente:

        endereco_completo = endereco

        if numero or bairro or cidade or uf:

            endereco_completo = f"{endereco}, {numero} - {bairro} / {cidade}-{uf}"

        cliente.nome = nome
        cliente.telefone = telefone
        cliente.cnpj = cnpj
        cliente.endereco = endereco_completo

        db.commit()

    db.close()

    return RedirectResponse(
        url="/clientes",
        status_code=302
    )

@app.post("/desativar_cliente/{cliente_id}")
def desativar_cliente(cliente_id: int):

    db = SessionLocal()

    cliente = db.query(Cliente).filter(
        Cliente.id == cliente_id
    ).first()

    if cliente:

        cliente.ativo = 0

        db.commit()

    db.close()

    return RedirectResponse(
        url="/clientes",
        status_code=302
    )

@app.post("/ativar_cliente/{cliente_id}")
def ativar_cliente(cliente_id: int):

    db = SessionLocal()

    cliente = db.query(Cliente).filter(
        Cliente.id == cliente_id
    ).first()

    if cliente:

        cliente.ativo = 1

        db.commit()

    db.close()

    return RedirectResponse(
        url="/clientes",
        status_code=302
    )

# =========================
# TORRES
# =========================

@app.get("/torres", response_class=HTMLResponse)
def torres(request: Request):

    if not request.cookies.get("usuario"):

        return RedirectResponse(
            url="/",
            status_code=302
        )

    if request.cookies.get("admin") != "1" and request.cookies.get("pode_colaborador") != "1":

        return RedirectResponse(
            url="/dashboard",
            status_code=302
        )

    db = SessionLocal()

    torres = db.query(Torre).all()

    clientes = db.query(Cliente).filter(
        Cliente.ativo == 1
    ).all()

    clientes_todos = db.query(Cliente).all()

    clientes_dict = {
        str(cliente.id): cliente.nome
        for cliente in clientes_todos
    }

    return templates.TemplateResponse(
        request,
        "torres.html",
        {
            "request": request,
            "torres": torres,
            "clientes": clientes,
            "clientes_dict": clientes_dict,
            "admin": request.cookies.get("admin"),
            "pode_clientes": request.cookies.get("pode_clientes"),
            "pode_colaborador": request.cookies.get("pode_colaborador")
        }
    )

@app.post("/torres")
def salvar_torre(

    nome: str = Form(...),
    cliente_id: str = Form(...),
    numero_serie: str = Form(""),
    qtd_litros: str = Form(""),
    foto_perfil: UploadFile = File(None)

):

    db = SessionLocal()

    nome_foto = ""

    if foto_perfil and foto_perfil.filename:

        extensao = foto_perfil.filename.split(".")[-1]

        nome_foto = f"torre_{datetime.now().strftime('%Y%m%d%H%M%S')}.{extensao}"

        caminho_foto = f"uploads/{nome_foto}"

        with open(caminho_foto, "wb") as buffer:

            buffer.write(foto_perfil.file.read())

    torre = Torre(

        nome=nome,
        cliente_id=cliente_id,
        numero_serie=numero_serie,
        qtd_litros=qtd_litros,
        foto_perfil=nome_foto
    )

    db.add(torre)

    db.commit()

    db.close()

    return RedirectResponse(
        url="/torres",
        status_code=302
    )

@app.post("/editar_torre/{torre_id}")
def editar_torre(

    torre_id: int,
    nome: str = Form(...),
    cliente_id: str = Form(...),
    numero_serie: str = Form(""),
    qtd_litros: str = Form(""),
    foto_perfil: UploadFile = File(None)

):

    db = SessionLocal()

    torre = db.query(Torre).filter(
        Torre.id == torre_id
    ).first()

    if torre:

        torre.nome = nome
        torre.cliente_id = cliente_id
        torre.numero_serie = numero_serie
        torre.qtd_litros = qtd_litros

        if foto_perfil and foto_perfil.filename:

            extensao = foto_perfil.filename.split(".")[-1]

            nome_foto = f"torre_{torre_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{extensao}"

            caminho_foto = f"uploads/{nome_foto}"

            with open(caminho_foto, "wb") as buffer:

                buffer.write(foto_perfil.file.read())

            torre.foto_perfil = nome_foto

        db.commit()

    db.close()

    return RedirectResponse(
        url="/torres",
        status_code=302
    )

# =========================
# USUÁRIOS
# =========================

@app.get("/usuarios", response_class=HTMLResponse)
def usuarios(request: Request):

    erro = request.query_params.get("erro")

    # VERIFICA LOGIN
    if not request.cookies.get("usuario"):

        return RedirectResponse(
            url="/",
            status_code=302
        )

    # SOMENTE ADMIN
    if request.cookies.get("admin") != "1":

        return RedirectResponse(
            url="/dashboard",
            status_code=302
        )

    db = SessionLocal()

    usuarios = db.query(
        Usuario
    ).all()

    clientes = db.query(Cliente).filter(
        Cliente.ativo == 1
    ).all()

    clientes_dict = {
        cliente.id: cliente.nome
        for cliente in db.query(Cliente).all()
    }

    db.close()

    return templates.TemplateResponse(
        request=request,
        name="usuarios.html",
        context={
            "request": request,
            "usuarios": usuarios,
            "clientes": clientes,
            "clientes_dict": clientes_dict,
            "erro": erro,

            "admin": request.cookies.get("admin"),
            "pode_clientes": request.cookies.get("pode_clientes"),
            "pode_colaborador": request.cookies.get("pode_colaborador")
        }
    )
    


@app.post("/editar_usuario/{usuario_id}")
def editar_usuario(

    usuario_id: int,

    usuario: str = Form(...),

    senha: str = Form(""),

    admin: str = Form(None),

    pode_clientes: str = Form(None),

    pode_colaborador: str = Form(None),

    cliente_id: str = Form("0"),
    
    ativo: str = Form(None),

):

    db = SessionLocal()

    user = db.query(Usuario).filter(
        Usuario.id == usuario_id
    ).first()

    total_permissoes = sum([
        1 if admin else 0,
        1 if pode_clientes else 0,
        1 if pode_colaborador else 0
    ])

    if total_permissoes != 1:

        db.close()

        return RedirectResponse(
            url="/usuarios",
            status_code=302
        )

    user.usuario = usuario

    if senha and senha.strip() != "":

        user.senha = pwd.hash(
            senha[:72]
        )

    user.admin = 1 if admin else 0

    user.pode_clientes = 1 if pode_clientes else 0

    user.pode_colaborador = 1 if pode_colaborador else 0

    if user.pode_clientes == 1 and user.admin == 0 and user.pode_colaborador == 0:

        user.cliente_id = int(cliente_id) if cliente_id else 0

    else:

        user.cliente_id = 0
    
    user.ativo = 1 if ativo else 0
    
    db.commit()

    return RedirectResponse(
        url="/usuarios",
        status_code=302
    )

@app.post("/usuarios")
def salvar_usuario(

    usuario: str = Form(...),
    senha: str = Form(...),
    confirmar: str = Form(...),
    admin: bool = Form(False),
    pode_clientes: bool = Form(False),
    pode_colaborador: bool = Form(False),
    cliente_id: str = Form("0"),

    db: Session = Depends(get_db)

):

    if senha != confirmar:

        return RedirectResponse(
            url="/usuarios?erro=senhas",
            status_code=302
        )

    total_permissoes = sum([
        1 if admin else 0,
        1 if pode_clientes else 0,
        1 if pode_colaborador else 0
    ])

    if total_permissoes != 1:

        return RedirectResponse(
            url="/usuarios",
            status_code=302
        )

    usuario_existente = db.query(
        Usuario
    ).filter(
        Usuario.usuario == usuario
    ).first()

    if usuario_existente:

        return RedirectResponse(
            url="/usuarios?erro=usuario_existente",
            status_code=302
        )

    novo = Usuario(

        usuario=usuario,

        senha=pwd.hash(
            senha[:72]
        ),

        admin=1 if admin else 0,

        pode_clientes=1 if pode_clientes else 0,

        pode_colaborador=1 if pode_colaborador else 0,

        cliente_id=int(cliente_id) if pode_clientes and not admin and not pode_colaborador and cliente_id else 0
    )
    
    db.add(novo)

    db.commit()

    db.refresh(novo)

    return RedirectResponse(
        url="/usuarios",
        status_code=302
    )


# =========================
# NOVO RELATORIO
# =========================

@app.get("/novo", response_class=HTMLResponse)
def novo_relatorio(request: Request):
    
    
    # VERIFICA LOGIN
    if not request.cookies.get("usuario"):

        return RedirectResponse(
            url="/",
            status_code=302
        )

    if request.cookies.get("admin") != "1" and request.cookies.get("pode_colaborador") != "1":

        return RedirectResponse(
            url="/dashboard",
            status_code=302
        )

    db = SessionLocal()

    clientes = db.query(Cliente).filter(
        Cliente.ativo == 1
    ).all()

    torres = db.query(Torre).all()

    return templates.TemplateResponse(
        request,
        "relatorio.html",
        {
            "request": request,
            "clientes": clientes,
            "torres": torres,

            "admin": request.cookies.get("admin"),
            "pode_clientes": request.cookies.get("pode_clientes"),
            "pode_colaborador": request.cookies.get("pode_colaborador")
        }
    )
    
# =========================
# EDITAR RELATORIO
# =========================

@app.get("/editar-relatorio/{id}", response_class=HTMLResponse)
def editar_relatorio(
    request: Request,
    id: int
):

    if not request.cookies.get("usuario"):

        return RedirectResponse(
            url="/",
            status_code=302
        )

    if request.cookies.get("admin") != "1" and request.cookies.get("pode_colaborador") != "1":

        return RedirectResponse(
            url="/dashboard",
            status_code=302
        )

    db = SessionLocal()

    relatorio = db.query(Relatorio).filter(
        Relatorio.id == id
    ).first()

    return templates.TemplateResponse(
        request,
        "editar_relatorio.html",
        {
            "request": request,
            "relatorio": relatorio,
            "admin": request.cookies.get("admin"),
            "pode_clientes": request.cookies.get("pode_clientes"),
            "pode_colaborador": request.cookies.get("pode_colaborador")
        }
    )


@app.post("/editar-relatorio/{id}")
def salvar_edicao_relatorio(

    request: Request,

    id: int,

    cliente: str = Form(""),
    torre: str = Form(""),
    tecnico: str = Form(""),
    observacoes: str = Form(""),
    status: str = Form("")

):

    if not request.cookies.get("usuario"):

        return RedirectResponse(
            url="/",
            status_code=302
        )

    pode_alterar_status = (
        request.cookies.get("admin") == "1"
        or request.cookies.get("pode_colaborador") == "1"
    )

    if not pode_alterar_status:

        return RedirectResponse(
            url="/dashboard",
            status_code=302
        )

    db = SessionLocal()

    relatorio = db.query(Relatorio).filter(
        Relatorio.id == id
    ).first()

    if not relatorio:

        db.close()

        return RedirectResponse(
            url="/dashboard",
            status_code=302
        )

    usuario_logado = request.cookies.get("usuario") or "Sistema"

    data_hora_alteracao = datetime.now().strftime(
        "%d/%m/%Y %H:%M"
    )

    def registrar_historico(alteracao, valor_antigo, valor_novo):

        historico = HistoricoRelatorio(
            relatorio_id=relatorio.id,
            usuario=usuario_logado,
            alteracao=alteracao,
            valor_antigo=str(valor_antigo or ""),
            valor_novo=str(valor_novo or ""),
            data_hora=data_hora_alteracao
        )

        db.add(historico)

    if relatorio.cliente != cliente:

        registrar_historico(
            "Mudança de cliente",
            relatorio.cliente,
            cliente
        )

        relatorio.cliente = cliente

    if relatorio.torre != torre:

        registrar_historico(
            "Mudança de torre",
            relatorio.torre,
            torre
        )

        relatorio.torre = torre

    if relatorio.tecnico != tecnico:

        registrar_historico(
            "Mudança de técnico responsável",
            relatorio.tecnico,
            tecnico
        )

        relatorio.tecnico = tecnico

    if relatorio.observacoes != observacoes:

        registrar_historico(
            "Alteração de relato",
            relatorio.observacoes,
            observacoes
        )

        relatorio.observacoes = observacoes

    if relatorio.status != "FINALIZADO" and relatorio.status != status:

        registrar_historico(
            "Mudança de status",
            relatorio.status,
            status
        )

        relatorio.status = status

    db.commit()

    db.close()

    return RedirectResponse(
        url="/dashboard",
        status_code=302
    )    

# =========================
# SALVAR RELATÓRIO
# =========================

@app.post("/salvar")
def salvar_relatorio(

    cliente: str = Form(...),
    torre: str = Form(...),
    tecnico: str = Form(...),

    horario_entrada: str = Form(...),
    horario_saida: str = Form(...),

    objetivo: str = Form(...),
    status_visita: str = Form(...),

    produtos: str = Form(...),
    qtd_produtos: str = Form(...),

    relato_visita: str = Form(""),

    cnpj: str = Form(""),
    endereco: str = Form(""),

    nome_assinatura: str = Form(...),

    assinatura: str = Form(...),

    fotos: list[UploadFile] = File(...)

):

    db = SessionLocal()

    total = db.query(Relatorio).count()

    numero = total + 1

    numero_relatorio = f"REL-{numero:03}"

    data_criacao = datetime.now().strftime(
        "%d/%m/%Y %H:%M"
    )

    texto_hash = (
        numero_relatorio +
        cliente +
        torre +
        tecnico +
        nome_assinatura +
        relato_visita +
        data_criacao
    )

    hash_relatorio = hashlib.sha256(
        texto_hash.encode()
    ).hexdigest()

    # ====================================
    # SALVAR FOTOS
    # ====================================

    nomes_fotos = []
    caminhos_fotos = []

    for index, foto in enumerate(fotos):

        if not foto.filename:

            continue

        extensao = foto.filename.split(".")[-1].lower()

        if extensao not in ["jpg", "jpeg", "png", "webp"]:

            extensao = "jpg"

        nome_foto = f"{numero_relatorio}_{index + 1}.{extensao}"

        caminho_foto = f"uploads/{nome_foto}"

        with open(caminho_foto, "wb") as buffer:

            buffer.write(
                foto.file.read()
            )

        nomes_fotos.append(nome_foto)
        caminhos_fotos.append(caminho_foto)

    # ====================================
    # SALVAR ASSINATURA COMO IMAGEM
    # ====================================

    caminho_assinatura = f"uploads/{numero_relatorio}_assinatura.png"

    if assinatura and "," in assinatura:

        assinatura_base64 = assinatura.split(",")[1]

        assinatura_bytes = base64.b64decode(
            assinatura_base64
        )

        with open(caminho_assinatura, "wb") as f:

            f.write(assinatura_bytes)

    # ====================================
    # SALVAR NO BANCO
    # ====================================

    novo = Relatorio(

        numero=numero_relatorio,

        cliente=cliente,

        torre=torre,

        tecnico=tecnico,

        observacoes=relato_visita,

        assinatura=assinatura,

        foto=",".join(nomes_fotos),

        data_criacao=data_criacao,

        status=status_visita,

        hash_relatorio=hash_relatorio
    )

    db.add(novo)

    db.commit()

    db.close()

    # ====================================
    # PDF PROFISSIONAL
    # ====================================

    caminho_pdf = f"pdfs/{numero_relatorio}.pdf"

    c = canvas.Canvas(
        caminho_pdf,
        pagesize=A4
    )

    page_width, page_height = A4

    margem_esquerda = 35
    margem_direita = 35
    margem_topo = 40
    margem_baixo = 35

    largura_util = page_width - margem_esquerda - margem_direita

    y = page_height - margem_topo

    def rodape():

        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.25, 0.25, 0.25)
        c.drawString(
            margem_esquerda,
            18,
            f"HASH: {hash_relatorio}"
        )
        c.drawRightString(
            page_width - margem_direita,
            18,
            f"{numero_relatorio}"
        )

    def nova_pagina():

        c.showPage()
        rodape()
        return page_height - margem_topo

    def garantir_espaco(y_atual, altura_necessaria):

        if y_atual - altura_necessaria < margem_baixo:

            return nova_pagina()

        return y_atual

    def titulo_secao(texto, y_atual):

        y_atual = garantir_espaco(y_atual, 35)

        c.setFillColorRGB(0.17, 0.24, 0.36)
        c.rect(
            margem_esquerda,
            y_atual - 24,
            largura_util,
            24,
            fill=1,
            stroke=0
        )

        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(
            page_width / 2,
            y_atual - 16,
            texto
        )

        c.setFillColorRGB(0, 0, 0)

        return y_atual - 34

    def campo_linha(titulo, valor, y_atual):

        valor = str(valor or "")

        linhas_valor = simpleSplit(
            valor,
            "Helvetica",
            9,
            largura_util - 180
        )

        altura = max(24, 14 + (len(linhas_valor) * 11))

        y_atual = garantir_espaco(y_atual, altura + 5)

        c.setStrokeColorRGB(0.78, 0.78, 0.78)
        c.setFillColorRGB(0.91, 0.93, 0.96)
        c.rect(
            margem_esquerda,
            y_atual - altura,
            160,
            altura,
            fill=1,
            stroke=1
        )

        c.setFillColorRGB(1, 1, 1)
        c.rect(
            margem_esquerda + 160,
            y_atual - altura,
            largura_util - 160,
            altura,
            fill=1,
            stroke=1
        )

        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(
            margem_esquerda + 6,
            y_atual - 15,
            titulo
        )

        texto = c.beginText(
            margem_esquerda + 168,
            y_atual - 15
        )
        texto.setFont("Helvetica", 9)

        for linha in linhas_valor:

            texto.textLine(linha)

        c.drawText(texto)

        return y_atual - altura

    def desenhar_imagem_proporcional(caminho, x, y_topo, largura_max, altura_max):

        try:

            img = ImageReader(caminho)
            img_largura, img_altura = img.getSize()

            escala = min(
                largura_max / img_largura,
                altura_max / img_altura
            )

            largura_img = img_largura * escala
            altura_img = img_altura * escala

            x_img = x + ((largura_max - largura_img) / 2)
            y_img = y_topo - altura_img

            c.drawImage(
                img,
                x_img,
                y_img,
                width=largura_img,
                height=altura_img,
                preserveAspectRatio=True,
                mask="auto"
            )

        except Exception:

            c.setFont("Helvetica", 8)
            c.drawString(
                x,
                y_topo - 20,
                "Não foi possível carregar esta imagem."
            )

    # ====================================
    # CABEÇALHO
    # ====================================

    c.setFillColorRGB(0.10, 0.15, 0.25)
    c.rect(
        margem_esquerda,
        y - 35,
        largura_util,
        35,
        fill=1,
        stroke=0
    )

    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(
        page_width / 2,
        y - 22,
        "RELATÓRIO TÉCNICO DE VISITA"
    )

    c.setFillColorRGB(0, 0, 0)

    y -= 50

    c.setFont("Helvetica-Bold", 10)
    c.drawString(
        margem_esquerda,
        y,
        f"OS Nº: {numero_relatorio}"
    )
    c.drawRightString(
        page_width - margem_direita,
        y,
        f"Data: {data_criacao}"
    )

    y -= 20

    # ====================================
    # INFORMAÇÕES GERAIS
    # ====================================

    y = titulo_secao(
        "INFORMAÇÕES GERAIS DA VISITA",
        y
    )

    campos = [

        ("Téc. Responsável", tecnico),
        ("Cliente", cliente),
        ("Torre", torre),
        ("CNPJ", cnpj),
        ("Endereço", endereco),
        ("Horário entrada", horario_entrada),
        ("Horário saída", horario_saida),
        ("Objetivo da visita", objetivo),
        ("Status da visita", status_visita),
        ("Produtos utilizados", produtos),
        ("Quantidade", qtd_produtos)

    ]

    for titulo, valor in campos:

        y = campo_linha(
            titulo,
            valor,
            y
        )

    y -= 18

    # ====================================
    # RELATO DA VISITA
    # ====================================

    y = titulo_secao(
        "RELATO DA VISITA",
        y
    )

    linhas_relato = []

    for paragrafo in relato_visita.splitlines():

        if paragrafo.strip() == "":

            linhas_relato.append("")

        else:

            linhas_relato.extend(
                simpleSplit(
                    paragrafo,
                    "Helvetica",
                    9,
                    largura_util - 20
                )
            )

    if not linhas_relato:

        linhas_relato = [""]

    c.setFont("Helvetica", 9)

    padding = 10
    altura_linha = 12

    for linha in linhas_relato:

        y = garantir_espaco(
            y,
            altura_linha + 8
        )

        c.drawString(
            margem_esquerda + padding,
            y - altura_linha,
            linha
        )

        y -= altura_linha

    y -= 20

    # ====================================
    # FOTOS DO ATENDIMENTO
    # ====================================

    if caminhos_fotos:

        y = titulo_secao(
            "FOTOS DO ATENDIMENTO",
            y
        )

        largura_foto = (largura_util - 15) / 2
        altura_foto = 145
        espaco_entre_fotos = 15

        for index, caminho_foto in enumerate(caminhos_fotos):

            if index % 2 == 0:

                y = garantir_espaco(
                    y,
                    altura_foto + 35
                )

                linha_y = y

            coluna = index % 2

            x = margem_esquerda + coluna * (largura_foto + espaco_entre_fotos)

            c.setStrokeColorRGB(0.75, 0.75, 0.75)
            c.rect(
                x,
                linha_y - altura_foto,
                largura_foto,
                altura_foto,
                fill=0,
                stroke=1
            )

            desenhar_imagem_proporcional(
                caminho_foto,
                x + 5,
                linha_y - 5,
                largura_foto - 10,
                altura_foto - 25
            )

            c.setFont("Helvetica", 8)
            c.setFillColorRGB(0.20, 0.20, 0.20)
            c.drawCentredString(
                x + (largura_foto / 2),
                linha_y - altura_foto + 8,
                f"Foto {index + 1}"
            )
            c.setFillColorRGB(0, 0, 0)

            if index % 2 == 1 or index == len(caminhos_fotos) - 1:

                y = linha_y - altura_foto - 18

    # ====================================
    # ASSINATURA NO FINAL
    # ====================================

    y -= 10

    y = titulo_secao(
        "ASSINATURA",
        y
    )

    y = garantir_espaco(
        y,
        125
    )

    if os.path.exists(caminho_assinatura):

        desenhar_imagem_proporcional(
            caminho_assinatura,
            page_width / 2 - 120,
            y,
            240,
            70
        )

    y -= 80

    c.line(
        page_width / 2 - 120,
        y,
        page_width / 2 + 120,
        y
    )

    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(
        page_width / 2,
        y - 14,
        nome_assinatura
    )

    c.setFont("Helvetica", 8)
    c.drawCentredString(
        page_width / 2,
        y - 28,
        "Responsável pelo acompanhamento"
    )

    rodape()

    c.save()

        # ====================================
    # ENVIAR ARQUIVOS PARA SUPABASE STORAGE
    # ====================================

    for caminho_foto in caminhos_fotos:

        upload_storage(
            "fotos",
            caminho_foto,
            os.path.basename(caminho_foto)
        )

    if os.path.exists(caminho_assinatura):

        upload_storage(
            "assinaturas",
            caminho_assinatura,
            os.path.basename(caminho_assinatura)
        )

    if os.path.exists(caminho_pdf):

        upload_storage(
            "pdfs",
            caminho_pdf,
            os.path.basename(caminho_pdf)
        )
    
    return RedirectResponse(
        url="/dashboard",
        status_code=302
    )

# =========================
# VISUALIZAR PDF
# =========================

@app.get("/pdf/{numero}")
def visualizar_pdf(numero: str):

    caminho = f"pdfs/{numero}.pdf"

    return FileResponse(
        caminho,
        media_type="application/pdf",
        filename=f"{numero}.pdf"
    )
