import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-mude-isso")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mude-esta-senha")
    COMISSAO_PASSWORD = os.environ.get("COMISSAO_PASSWORD", "mude-esta-senha-comissao")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,   # evita erro de conexão "caída" do Supabase
        "pool_recycle": 280,
    }
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # E-mail (Gmail) usado para avisar a Comissão de Recursos quando chega
    # algo novo pra ela ver. MAIL_APP_PASSWORD é uma "senha de app" gerada
    # em myaccount.google.com/apppasswords (não é a senha normal da conta,
    # que o Gmail não aceita mais para login por SMTP).
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 465))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_APP_PASSWORD = os.environ.get("MAIL_APP_PASSWORD")
