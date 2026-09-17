import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-mude-isso")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mude-esta-senha")
    COMISSAO_PASSWORD = os.environ.get("COMISSAO_PASSWORD", "mude-esta-senha-comissao")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    # No Vercel (serverless) cada request pode rodar numa função nova, então
    # o pool de conexões do SQLAlchemy não sobrevive de um request pro
    # outro mesmo assim — por isso usamos NullPool (sem pool local) e
    # deixamos o PgBouncer do Supabase (modo "Transaction Pooling", porta
    # 6543 na DATABASE_URL) cuidar do pooling de verdade do lado do banco.
    # pool_pre_ping/pool_recycle foram removidos porque só fazem sentido
    # quando existe uma conexão persistida pra testar/reciclar — com
    # NullPool não existe, então eram uma consulta extra (ping) desperdiçada
    # a cada request.
    from sqlalchemy.pool import NullPool

    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": NullPool,
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

    # Segredo que protege a rota /tarefas/verificar-prazos (lembretes de
    # prazo por e-mail), chamada 1x/dia pelo Vercel Cron. Sem essa variável
    # configurada, a rota fica desativada.
    CRON_SECRET = os.environ.get("CRON_SECRET")
