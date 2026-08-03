"""
Envio de e-mail para os membros da Comissão de Recursos, avisando sempre
que chega algo novo esperando uma ação deles (recurso aberto, gestor
respondeu, empregado aceitou/recorreu etc).

Usa uma conta do Gmail via SMTP. Não depende de nenhuma biblioteca extra
(só smtplib, que já vem no Python).
"""

import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app

from .models import MembroComissao


def _emails_comissao():
    """E-mails dos membros da Comissão que têm e-mail cadastrado."""
    membros = MembroComissao.query.all()
    emails = []
    for m in membros:
        if m.funcionario and m.funcionario.email:
            email = m.funcionario.email.strip()
            if email:
                emails.append(email)
    return emails


def enviar_email_comissao(assunto, corpo):
    """Manda um e-mail avisando a Comissão que há algo novo pra ela ver.

    Se o e-mail não estiver configurado (variáveis de ambiente
    MAIL_USERNAME / MAIL_APP_PASSWORD) ou o envio falhar por qualquer
    motivo, só registra um aviso no log da aplicação e segue em frente —
    isso nunca deve quebrar a ação do empregado/gestor/comissão que
    disparou o aviso.
    """
    usuario = current_app.config.get("MAIL_USERNAME")
    senha = current_app.config.get("MAIL_APP_PASSWORD")
    if not usuario or not senha:
        current_app.logger.warning(
            "Aviso por e-mail à Comissão não enviado: MAIL_USERNAME/MAIL_APP_PASSWORD "
            "não configurados no ambiente."
        )
        return

    destinatarios = _emails_comissao()
    if not destinatarios:
        current_app.logger.warning(
            "Aviso por e-mail à Comissão não enviado: nenhum membro da Comissão "
            "tem e-mail cadastrado."
        )
        return

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = usuario
    msg["To"] = ", ".join(destinatarios)
    msg.set_content(corpo)

    servidor = current_app.config.get("MAIL_SERVER", "smtp.gmail.com")
    porta = current_app.config.get("MAIL_PORT", 465)

    try:
        contexto = ssl.create_default_context()
        with smtplib.SMTP_SSL(servidor, porta, context=contexto) as smtp:
            smtp.login(usuario, senha)
            smtp.send_message(msg)
    except Exception:
        # Problema de e-mail nunca deve derrubar a ação que o usuário
        # estava fazendo (abrir recurso, responder etc) — só registra.
        current_app.logger.exception(
            "Falha ao enviar e-mail de aviso para a Comissão de Recursos."
        )


def avisar_comissao_novo_recurso(recurso):
    """Recurso recém-aberto pelo empregado, aguardando a 1ª análise da Comissão."""
    link = _link_comissao()
    corpo = (
        f"{recurso.avaliado.nome} abriu um recurso sobre o resultado da avaliação "
        f"de desempenho (Exercício {recurso.ciclo.exercicio}).\n\n"
        f"Resultado contestado: {recurso.resultado_final_em_texto or '-'}\n\n"
        f"Motivo:\n{recurso.motivo}\n\n"
        f"Acesse a área da Comissão para analisar e encaminhar ao gestor:\n{link}"
    )
    enviar_email_comissao(
        f"[Avaliação de Desempenho] Novo recurso — {recurso.avaliado.nome}", corpo
    )


def avisar_comissao_gestor_respondeu(recurso, decisao, justificativa):
    link = _link_comissao()
    decisao_texto = "revisou a nota" if decisao == "revisou" else "manteve a nota"
    corpo = (
        f"O gestor respondeu ao recurso de {recurso.avaliado.nome} "
        f"(Exercício {recurso.ciclo.exercicio}) e {decisao_texto}.\n\n"
        f"Justificativa do gestor:\n{justificativa}\n\n"
        f"Acesse a área da Comissão para revisar antes de repassar ao empregado:\n{link}"
    )
    enviar_email_comissao(
        f"[Avaliação de Desempenho] Gestor respondeu recurso — {recurso.avaliado.nome}", corpo
    )


def avisar_comissao_empregado_aceitou(recurso):
    link = _link_comissao()
    corpo = (
        f"{recurso.avaliado.nome} aceitou a resposta do gestor sobre o recurso "
        f"(Exercício {recurso.ciclo.exercicio}) e não quer recorrer.\n\n"
        f"Acesse a área da Comissão para confirmar o encerramento:\n{link}"
    )
    enviar_email_comissao(
        f"[Avaliação de Desempenho] Empregado aceitou resposta — {recurso.avaliado.nome}", corpo
    )


def avisar_comissao_empregado_recorreu(recurso):
    link = _link_comissao()
    corpo = (
        f"{recurso.avaliado.nome} não concordou com a resposta do gestor sobre o recurso "
        f"(Exercício {recurso.ciclo.exercicio}) e pediu para recorrer à presidência.\n\n"
        f"Acesse a área da Comissão para encaminhar à presidência:\n{link}"
    )
    enviar_email_comissao(
        f"[Avaliação de Desempenho] Empregado recorreu — {recurso.avaliado.nome}", corpo
    )


def _link_comissao():
    from flask import url_for

    try:
        return url_for("recursos.recurso_comissao_area", _external=True)
    except RuntimeError:
        # fora de um contexto de requisição (ex: script/rotina manual)
        return ""
