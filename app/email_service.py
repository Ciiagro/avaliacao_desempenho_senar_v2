"""
Envio de e-mail avisando as partes envolvidas num recurso sempre que
chega algo novo esperando ação delas, ou quando a situação do recurso
delas muda (recurso aberto, gestor respondeu, comissão repassou,
recurso encerrado etc).

Os e-mails são enviados em HTML (com um texto simples como alternativa,
pra clientes de e-mail antigos/sem HTML) usando um layout único, com a
mesma identidade visual do sistema — assim fica mais fácil de bater o
olho e entender rápido o que aconteceu.

Usa uma conta do Gmail via SMTP. Não depende de nenhuma biblioteca extra
(só smtplib, que já vem no Python).
"""

import html
import smtplib
import ssl
import threading
from email.message import EmailMessage

from flask import current_app

# Mesmas cores usadas no style.css do sistema, pra manter a identidade visual.
_COR_NAVY_900 = "#002f30"
_COR_NAVY_700 = "#0d5859"
_COR_TEXTO = "#1c2536"
_COR_TEXTO_MUTED = "#626c7e"
_COR_BORDA = "#e2e6ee"
_COR_FUNDO = "#f3f5f8"
_COR_DESTAQUE_BG = "#fbf1dc"
_COR_DESTAQUE_TEXTO = "#93691f"
_COR_SUCESSO_BG = "#e5f5ea"
_COR_SUCESSO_TEXTO = "#1f8a4c"
_COR_NEUTRO_BG = "#eef0f4"
_COR_NEUTRO_TEXTO = "#6b7385"


def _emails_comissao():
    """Pra onde vão os avisos da Comissão.

    A Comissão usa uma caixa de e-mail compartilhada (a mesma conta que
    envia os avisos, MAIL_USERNAME) em vez do e-mail pessoal de cada
    membro cadastrado — assim qualquer um que tenha acesso a essa caixa
    vê o aviso, sem depender de manter a lista de membros sempre em dia
    com e-mail pessoal certo.
    """
    email = (current_app.config.get("MAIL_USERNAME") or "").strip()
    return [email] if email else []


def _email_funcionario(funcionario):
    if funcionario and funcionario.email and funcionario.email.strip():
        return [funcionario.email.strip()]
    return []


# ---------------------------------------------------------------------------
# Montagem do e-mail (HTML + texto simples) a partir de um conteúdo comum
# ---------------------------------------------------------------------------
def _montar_email(titulo, paragrafos, destaque=None, link_url=None, link_texto=None, selo=None):
    """Monta o par (texto_simples, html) de um e-mail de aviso, com um
    layout único e consistente:

    - título no cabeçalho (cor de marca), com um selo colorido opcional
      ao lado (ex.: "REVISOU A NOTA" / "MANTEVE A NOTA"), pro leitor bater
      o olho e já saber do que se trata antes de ler o texto;
    - parágrafos de texto corrido, em ordem;
    - um "destaque" opcional (ex.: motivo do recurso, justificativa),
      mostrado numa caixa clara, separado do resto do texto;
    - um botão de ação opcional, linkando pra área do sistema onde a
      pessoa precisa agir.
    """
    paragrafos = [p for p in paragrafos if p]

    # ---- texto simples (fallback) ----
    partes_txt = [titulo]
    if selo:
        partes_txt[0] = f"{titulo} [{selo[0]}]"
    partes_txt.append("")
    for p in paragrafos:
        partes_txt.append(p)
        partes_txt.append("")
    if destaque:
        rotulo, conteudo = destaque
        partes_txt.append(f"{rotulo}:")
        partes_txt.append(conteudo)
        partes_txt.append("")
    if link_url:
        partes_txt.append(f"{link_texto or 'Acessar'}: {link_url}")
    texto = "\n".join(partes_txt).strip()

    # ---- HTML ----
    def esc(s):
        return html.escape(str(s)).replace("\n", "<br>")

    paragrafos_html = "".join(
        f'<p style="margin:0 0 10px; font-size:13px; line-height:1.5; color:{_COR_TEXTO};">{esc(p)}</p>'
        for p in paragrafos
    )

    destaque_html = ""
    if destaque:
        rotulo, conteudo = destaque
        destaque_html = f"""
        <div style="margin:0 0 12px; padding:10px 12px; background:{_COR_DESTAQUE_BG};
                    border-left:3px solid {_COR_DESTAQUE_TEXTO}; border-radius:5px;">
            <p style="margin:0 0 3px; font-size:10px; font-weight:bold; letter-spacing:0.04em;
                      text-transform:uppercase; color:{_COR_DESTAQUE_TEXTO};">{esc(rotulo)}</p>
            <p style="margin:0; font-size:13px; line-height:1.45; color:{_COR_TEXTO};">{esc(conteudo)}</p>
        </div>"""

    botao_html = ""
    if link_url:
        botao_html = f"""
        <a href="{html.escape(link_url)}"
           style="display:inline-block; margin-top:4px; padding:8px 16px; background:{_COR_NAVY_700};
                  color:#ffffff; font-size:13px; font-weight:bold; text-decoration:none;
                  border-radius:6px;">{esc(link_texto or 'Acessar o sistema')}</a>"""

    selo_html = ""
    if selo:
        selo_texto, selo_bg, selo_texto_cor = selo
        selo_html = f"""
                <span style="display:inline-block; margin-top:6px; padding:3px 9px; background:{selo_bg};
                             color:{selo_texto_cor}; font-size:10px; font-weight:bold; letter-spacing:0.03em;
                             text-transform:uppercase; border-radius:20px;">{esc(selo_texto)}</span>"""

    corpo_html = f"""\
<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"></head>
<body style="margin:0; padding:20px 12px; background:{_COR_FUNDO}; font-family:Arial, Helvetica, sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px; margin:0 auto;">
        <tr>
            <td style="background:{_COR_NAVY_900}; padding:12px 18px; border-radius:8px 8px 0 0;">
                <p style="margin:0 0 2px; font-size:10px; font-weight:bold; letter-spacing:0.05em;
                          text-transform:uppercase; color:rgba(255,255,255,0.6);">Avaliação de Desempenho</p>
                <h1 style="margin:0; font-size:15px; color:#ffffff;">{esc(titulo)}</h1>
                {selo_html}
            </td>
        </tr>
        <tr>
            <td style="background:#ffffff; border:1px solid {_COR_BORDA}; border-top:none;
                       border-radius:0 0 8px 8px; padding:18px;">
                {paragrafos_html}
                {destaque_html}
                {botao_html}
            </td>
        </tr>
        <tr>
            <td style="padding:12px 6px 0; text-align:center;">
                <p style="margin:0; font-size:10px; color:{_COR_TEXTO_MUTED};">
                    Mensagem automática do sistema de Avaliação de Desempenho.
                </p>
            </td>
        </tr>
    </table>
</body>
</html>"""

    return texto, corpo_html


def _enviar_email(destinatarios, assunto, titulo, paragrafos, destaque=None, link_url=None, link_texto=None, selo=None):
    """Envio de e-mail de baixo nível, usado tanto pros avisos da Comissão
    quanto pros avisos ao gestor/empregado. Manda em HTML com uma versão
    em texto simples como alternativa.

    Se o e-mail não estiver configurado (variáveis de ambiente
    MAIL_USERNAME / MAIL_APP_PASSWORD), não houver destinatário, ou o
    envio falhar por qualquer motivo, só registra um aviso no log da
    aplicação e segue em frente — isso nunca deve quebrar a ação do
    empregado/gestor/comissão que disparou o aviso.
    """
    usuario = current_app.config.get("MAIL_USERNAME")
    senha = current_app.config.get("MAIL_APP_PASSWORD")
    if not usuario or not senha:
        current_app.logger.warning(
            "Aviso por e-mail não enviado (assunto: %s): MAIL_USERNAME/MAIL_APP_PASSWORD "
            "não configurados no ambiente.",
            assunto,
        )
        return

    destinatarios = [d.strip() for d in destinatarios if d and d.strip()]
    if not destinatarios:
        current_app.logger.warning(
            "Aviso por e-mail não enviado (assunto: %s): nenhum destinatário com e-mail cadastrado.",
            assunto,
        )
        return

    texto, corpo_html = _montar_email(titulo, paragrafos, destaque, link_url, link_texto, selo)

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = usuario
    msg["To"] = ", ".join(destinatarios)
    msg.set_content(texto)
    msg.add_alternative(corpo_html, subtype="html")

    servidor = current_app.config.get("MAIL_SERVER", "smtp.gmail.com")
    porta = current_app.config.get("MAIL_PORT", 465)

    # A conexão SMTP (handshake TLS + login + envio) pode levar vários
    # segundos, e isso deixava quem abre/responde um recurso esperando
    # a página carregar até o Gmail terminar de responder. Como o e-mail
    # é só um aviso (não afeta o que foi salvo no banco), a gente manda
    # de verdade numa thread em segundo plano e libera a resposta pro
    # usuário na hora — quem clicou não fica esperando o e-mail sair.
    app = current_app._get_current_object()

    def _enviar_em_segundo_plano():
        try:
            contexto = ssl.create_default_context()
            with smtplib.SMTP_SSL(servidor, porta, context=contexto) as smtp:
                smtp.login(usuario, senha)
                smtp.send_message(msg)
        except Exception:
            with app.app_context():
                app.logger.exception(
                    "Falha ao enviar e-mail de aviso (assunto: %s).", assunto
                )

    threading.Thread(target=_enviar_em_segundo_plano, daemon=True).start()


# ---------------------------------------------------------------------------
# Avisos por evento
# ---------------------------------------------------------------------------
def avisar_comissao_novo_recurso(recurso):
    """Recurso recém-aberto pelo empregado, aguardando a 1ª análise da Comissão."""
    _enviar_email(
        _emails_comissao(),
        f"[Avaliação de Desempenho] Novo recurso — {recurso.avaliado.nome}",
        titulo=f"Novo recurso — {recurso.avaliado.nome}",
        paragrafos=[
            f"{recurso.avaliado.nome} abriu um recurso sobre o resultado da avaliação de "
            f"desempenho (Exercício {recurso.ciclo.exercicio}).",
            f"Resultado contestado: {recurso.resultado_final_em_texto or '-'}",
        ],
        destaque=("Motivo do recurso", recurso.motivo),
        link_url=_link_comissao(),
        link_texto="Analisar e encaminhar ao gestor",
    )


def avisar_comissao_gestor_respondeu(recurso, decisao, justificativa):
    decisao_texto = "revisou a nota" if decisao == "revisou" else "manteve a nota"
    if decisao == "revisou":
        selo = ("Revisou a nota", _COR_SUCESSO_BG, _COR_SUCESSO_TEXTO)
    else:
        selo = ("Manteve a nota", _COR_NEUTRO_BG, _COR_NEUTRO_TEXTO)
    _enviar_email(
        _emails_comissao(),
        f"[Avaliação de Desempenho] Gestor respondeu recurso — {recurso.avaliado.nome}",
        titulo=f"Gestor respondeu — {recurso.avaliado.nome}",
        paragrafos=[
            f"O gestor respondeu ao recurso de {recurso.avaliado.nome} "
            f"(Exercício {recurso.ciclo.exercicio}) e {decisao_texto}.",
        ],
        destaque=("Justificativa do gestor", justificativa),
        link_url=_link_comissao(),
        link_texto="Revisar antes de repassar ao empregado",
        selo=selo,
    )


def avisar_comissao_empregado_aceitou(recurso):
    _enviar_email(
        _emails_comissao(),
        f"[Avaliação de Desempenho] Empregado aceitou resposta — {recurso.avaliado.nome}",
        titulo=f"Empregado aceitou a resposta — {recurso.avaliado.nome}",
        paragrafos=[
            f"{recurso.avaliado.nome} aceitou a resposta do gestor sobre o recurso "
            f"(Exercício {recurso.ciclo.exercicio}) e não quer recorrer.",
        ],
        link_url=_link_comissao(),
        link_texto="Confirmar o encerramento",
    )


def avisar_comissao_empregado_recorreu(recurso):
    _enviar_email(
        _emails_comissao(),
        f"[Avaliação de Desempenho] Empregado recorreu — {recurso.avaliado.nome}",
        titulo=f"Empregado recorreu à presidência — {recurso.avaliado.nome}",
        paragrafos=[
            f"{recurso.avaliado.nome} não concordou com a resposta do gestor sobre o recurso "
            f"(Exercício {recurso.ciclo.exercicio}) e pediu para recorrer à presidência.",
        ],
        link_url=_link_comissao(),
        link_texto="Encaminhar à presidência",
    )


def avisar_gestor_recurso_encaminhado(recurso, comentario):
    """A Comissão encaminhou o recurso pro gestor responder."""
    from .models import VinculoAvaliacao

    vinculo = VinculoAvaliacao.query.filter_by(
        ciclo_id=recurso.ciclo_id, avaliado_id=recurso.avaliado_id
    ).first()
    gestor = vinculo.avaliador if vinculo else None

    _enviar_email(
        _email_funcionario(gestor),
        f"[Avaliação de Desempenho] Recurso pra você responder — {recurso.avaliado.nome}",
        titulo=f"Recurso pra você responder — {recurso.avaliado.nome}",
        paragrafos=[
            f"{recurso.avaliado.nome} abriu um recurso sobre o resultado da avaliação de "
            f"desempenho (Exercício {recurso.ciclo.exercicio}) e a Comissão pede que você reavalie.",
        ],
        destaque=("Mensagem da Comissão", comentario) if comentario else None,
        link_url=_link_gestor(),
        link_texto="Responder ao recurso",
    )


def avisar_empregado_resposta_disponivel(recurso, comentario):
    """A Comissão repassou a resposta do gestor pro empregado decidir."""
    _enviar_email(
        _email_funcionario(recurso.avaliado),
        f"[Avaliação de Desempenho] Resposta ao seu recurso — {recurso.ciclo.exercicio}",
        titulo="Chegou uma resposta ao seu recurso",
        paragrafos=[
            f"Chegou uma resposta ao seu recurso sobre o resultado da avaliação de "
            f"desempenho (Exercício {recurso.ciclo.exercicio}).",
            "Acesse o sistema para visualizar a resposta completa e confirmar o recebimento.",
        ],
        destaque=("Comentário da Comissão", comentario) if comentario else None,
    )


def avisar_empregado_recurso_encerrado(recurso, resumo):
    """O recurso do empregado foi encerrado (aceite dele mesmo, ou decisão
    final da presidência/Comissão)."""
    _enviar_email(
        _email_funcionario(recurso.avaliado),
        f"[Avaliação de Desempenho] Recurso encerrado — {recurso.ciclo.exercicio}",
        titulo="Seu recurso foi encerrado",
        paragrafos=[
            f"Seu recurso sobre o resultado da avaliação de desempenho "
            f"(Exercício {recurso.ciclo.exercicio}) foi encerrado.",
        ],
        destaque=("Decisão", resumo) if resumo else None,
        link_url=_link_empregado(),
        link_texto="Ver detalhes",
    )


def avisar_prazo_avaliacao(funcionario, tipo, dias_restantes, prazo):
    """Lembrete de prazo (5 dias / 2 dias / no dia) pra quem ainda não
    concluiu a autoavaliação ou a avaliação do gestor de alguém."""
    nome_tipo = "autoavaliação" if tipo == "auto" else "avaliação do(s) empregado(s) sob sua gestão"

    if dias_restantes == 0:
        assunto_prazo = "encerra hoje"
        frase_prazo = f"o prazo para concluir sua {nome_tipo} encerra hoje, {prazo.strftime('%d/%m/%Y')}."
    else:
        assunto_prazo = f"faltam {dias_restantes} dias"
        frase_prazo = (
            f"faltam {dias_restantes} dia(s) para o prazo de conclusão da sua "
            f"{nome_tipo}, que encerra em {prazo.strftime('%d/%m/%Y')}."
        )

    _enviar_email(
        _email_funcionario(funcionario),
        f"[Avaliação de Desempenho] Prazo — {assunto_prazo} ({nome_tipo})",
        titulo="Lembrete de prazo",
        paragrafos=[
            f"Olá, {funcionario.nome}.",
            frase_prazo,
            "Depois do prazo, o sistema não permite mais preencher ou alterar a avaliação.",
        ],
        link_url=_link_minha_area(),
        link_texto="Acessar minha área",
    )


def avisar_prazo_ciencia_resultado(funcionario, dias_restantes, prazo):
    """Lembrete pra quem ainda NÃO deu ciência do resultado final — mesmo
    que a pessoa não pretenda recorrer, ela precisa confirmar que viu a
    nota antes do prazo. Esse documento assinado é o que protege a
    empresa numa reclamação futura, então esse lembrete vale tanto quanto
    os de prazo de avaliação."""
    if dias_restantes == 0:
        assunto_prazo = "encerra hoje"
        frase_prazo = f"o prazo para dar ciência do seu resultado final encerra hoje, {prazo.strftime('%d/%m/%Y')}."
    else:
        assunto_prazo = f"faltam {dias_restantes} dias"
        frase_prazo = (
            f"faltam {dias_restantes} dia(s) para o prazo de dar ciência do seu resultado final, "
            f"que encerra em {prazo.strftime('%d/%m/%Y')}."
        )

    _enviar_email(
        _email_funcionario(funcionario),
        f"[Avaliação de Desempenho] Prazo — {assunto_prazo} (ciência do resultado final)",
        titulo="Lembrete de prazo",
        paragrafos=[
            f"Olá, {funcionario.nome}.",
            "Seu resultado final da avaliação de desempenho já foi liberado e ainda está "
            "aguardando sua ciência.",
            frase_prazo,
            "Mesmo que você concorde com o resultado e não vá recorrer, é obrigatório confirmar "
            "que você tomou conhecimento — isso é o que fica registrado como comprovante.",
        ],
        link_url=_link_minha_area(),
        link_texto="Ver meu resultado",
    )


def avisar_empregado_devolutiva_marcada(funcionario, data_devolutiva, data_limite):
    """Devolutiva marcada para o funcionário: aviso com a data e o prazo
    que ele tem para concordar ou recorrer."""
    dias = (data_limite - data_devolutiva).days
    _enviar_email(
        _email_funcionario(funcionario),
        "[Avaliação de Desempenho] Data de devolutiva marcada",
        titulo="Devolutiva marcada",
        paragrafos=[
            f"A data de devolutiva da sua avaliação foi marcada para "
            f"{data_devolutiva.strftime('%d/%m/%Y')}.",
            f"Você terá até {data_limite.strftime('%d/%m/%Y')} ({dias} dias) para "
            f"concordar com a resposta ou recorrer.",
        ],
        link_url=_link_empregado(),
        link_texto="Acessar meus recursos",
    )


def _link_minha_area():
    from flask import url_for

    try:
        return url_for("main.minha_area", _external=True)
    except RuntimeError:
        return ""


def _link_comissao():
    from flask import url_for

    try:
        return url_for("recursos.recurso_comissao_area", _external=True)
    except RuntimeError:
        # fora de um contexto de requisição (ex: script/rotina manual)
        return ""


def _link_gestor():
    from flask import url_for

    try:
        return url_for("recursos.recurso_gestor_area", _external=True)
    except RuntimeError:
        return ""


def _link_empregado():
    from flask import url_for

    try:
        return url_for("recursos.recurso_area", _external=True)
    except RuntimeError:
        return ""
