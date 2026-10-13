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
_LOGO_CID = "logo_senar"
_LOGO_ARQUIVO = "img/logo_senar_email.png"


def _ler_logo():
    """Bytes da logo do SENAR (versão pequena, própria para e-mail) ou None.

    A logo vai ANEXADA ao e-mail (imagem embutida, "cid:"), em vez de
    linkada pelo site: assim aparece sempre, sem depender de o site estar
    acessível pela internet nem de o leitor de e-mail baixar imagens externas.
    """
    import os

    try:
        caminho = os.path.join(current_app.static_folder, _LOGO_ARQUIVO)
        with open(caminho, "rb") as f:
            return f.read()
    except (OSError, RuntimeError):
        return None


def _montar_email(titulo, paragrafos, destaque=None, link_url=None, link_texto=None, selo=None,
                  icone=None, destaque_mono=False):
    """Monta o par (texto_simples, html) de um e-mail de aviso, com um
    layout único e consistente:

    - cabeçalho na cor da marca, com a logo, o título e um selo colorido
      opcional (ex.: "REVISOU A NOTA") pro leitor já saber do que se trata;
    - um ícone opcional (ex.: ✓) em um círculo, no topo do corpo;
    - parágrafos de texto corrido, em ordem;
    - um "destaque" opcional (ex.: motivo do recurso, senha provisória),
      numa caixa clara (em fonte monoespaçada com destaque_mono=True);
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

    fonte = "Segoe UI, Helvetica, Arial, sans-serif"

    icone_html = ""
    if icone:
        icone_html = f"""
                <div style="margin:0 0 18px;">
                    <span style="display:inline-block; width:48px; height:48px; line-height:48px;
                                 text-align:center; border-radius:50%; background:{_COR_SUCESSO_BG};
                                 color:{_COR_SUCESSO_TEXTO}; font-size:24px; font-weight:bold;">{esc(icone)}</span>
                </div>"""

    paragrafos_html = "".join(
        f'<p style="margin:0 0 14px; font-size:15px; line-height:1.6; color:{_COR_TEXTO};">{esc(p)}</p>'
        for p in paragrafos
    )

    destaque_html = ""
    if destaque:
        rotulo, conteudo = destaque
        if destaque_mono:
            estilo_conteudo = (
                f"margin:0; font-family:Consolas, 'Courier New', monospace; font-size:20px; "
                f"font-weight:bold; letter-spacing:0.06em; color:{_COR_TEXTO};"
            )
        else:
            estilo_conteudo = f"margin:0; font-size:14px; line-height:1.55; color:{_COR_TEXTO};"
        destaque_html = f"""
                <div style="margin:4px 0 20px; padding:14px 16px; background:{_COR_DESTAQUE_BG};
                            border-left:4px solid {_COR_DESTAQUE_TEXTO}; border-radius:6px;">
                    <p style="margin:0 0 6px; font-size:11px; font-weight:bold; letter-spacing:0.06em;
                              text-transform:uppercase; color:{_COR_DESTAQUE_TEXTO};">{esc(rotulo)}</p>
                    <p style="{estilo_conteudo}">{esc(conteudo)}</p>
                </div>"""

    botao_html = ""
    if link_url:
        botao_html = f"""
                <table role="presentation" cellpadding="0" cellspacing="0" style="margin:6px 0 4px;">
                    <tr>
                        <td align="center" bgcolor="{_COR_NAVY_700}" style="border-radius:8px; background:{_COR_NAVY_700};">
                            <a href="{html.escape(link_url)}"
                               style="display:inline-block; padding:13px 28px; color:#ffffff; font-size:15px;
                                      font-weight:bold; text-decoration:none; border-radius:8px;">{esc(link_texto or 'Acessar o sistema')}</a>
                        </td>
                    </tr>
                </table>"""

    selo_html = ""
    if selo:
        selo_texto, selo_bg, selo_texto_cor = selo
        selo_html = f"""
                <span style="display:inline-block; margin-top:10px; padding:4px 11px; background:{selo_bg};
                             color:{selo_texto_cor}; font-size:11px; font-weight:bold; letter-spacing:0.04em;
                             text-transform:uppercase; border-radius:20px;">{esc(selo_texto)}</span>"""

    # Logo colorida sobre um "cartão" branco (a original não tem versão para fundo escuro).
    logo_html = ""
    if _ler_logo():
        logo_html = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 18px;"><tr>'
            f'<td bgcolor="#ffffff" style="background:#ffffff; border-radius:10px; padding:8px 14px;">'
            f'<img src="cid:{_LOGO_CID}" alt="SENAR Ceará" width="120" '
            f'style="display:block; width:120px; height:auto; border:0;">'
            f'</td></tr></table>'
        )

    corpo_html = f"""\
<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0; padding:28px 12px; background:{_COR_FUNDO}; font-family:{fonte};">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px; margin:0 auto;">
        <tr>
            <td bgcolor="{_COR_NAVY_900}" style="background:{_COR_NAVY_900}; padding:24px 28px; border-radius:12px 12px 0 0;">
                {logo_html}
                <p style="margin:0 0 4px; font-size:11px; font-weight:bold; letter-spacing:0.08em;
                          text-transform:uppercase; color:#9fc2c3;">Avaliação de Desempenho</p>
                <h1 style="margin:0; font-size:22px; line-height:1.3; color:#ffffff;">{esc(titulo)}</h1>
                {selo_html}
            </td>
        </tr>
        <tr>
            <td bgcolor="#ffffff" style="background:#ffffff; border:1px solid {_COR_BORDA}; border-top:none;
                       border-radius:0 0 12px 12px; padding:28px;">
                {icone_html}
                {paragrafos_html}
                {destaque_html}
                {botao_html}
            </td>
        </tr>
        <tr>
            <td style="padding:16px 8px 0; text-align:center;">
                <p style="margin:0; font-size:12px; line-height:1.5; color:{_COR_TEXTO_MUTED};">
                    Mensagem automática do sistema de Avaliação de Desempenho.<br>
                    Não é necessário responder a este e-mail.
                </p>
            </td>
        </tr>
    </table>
</body>
</html>"""

    return texto, corpo_html


def _enviar_email(destinatarios, assunto, titulo, paragrafos, destaque=None, link_url=None, link_texto=None, selo=None,
                  icone=None, destaque_mono=False):
    """Envio de e-mail de baixo nível, usado tanto pros avisos da Comissão
    quanto pros avisos ao gestor/empregado. Manda em HTML com uma versão
    em texto simples como alternativa.

    Devolve True se o e-mail foi entregue ao servidor SMTP e False se não
    foi (e-mail não configurado, sem destinatário ou falha no envio).

    Se algo falhar, só registra no log da aplicação e devolve False — isso
    nunca deve quebrar a ação do empregado/gestor/comissão que disparou o
    aviso. Quem chama pode usar o resultado para avisar o usuário (e a
    rotina de lembretes só marca "enviado" quando deu certo).
    """
    usuario = current_app.config.get("MAIL_USERNAME")
    senha = current_app.config.get("MAIL_APP_PASSWORD")
    if not usuario or not senha:
        current_app.logger.warning(
            "Aviso por e-mail não enviado (assunto: %s): MAIL_USERNAME/MAIL_APP_PASSWORD "
            "não configurados no ambiente.",
            assunto,
        )
        return False

    destinatarios = [d.strip() for d in destinatarios if d and d.strip()]
    if not destinatarios:
        current_app.logger.warning(
            "Aviso por e-mail não enviado (assunto: %s): nenhum destinatário com e-mail cadastrado.",
            assunto,
        )
        return False

    texto, corpo_html = _montar_email(
        titulo, paragrafos, destaque, link_url, link_texto, selo, icone=icone, destaque_mono=destaque_mono
    )

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = usuario
    msg["To"] = ", ".join(destinatarios)
    msg.set_content(texto)
    msg.add_alternative(corpo_html, subtype="html")
    logo = _ler_logo()
    if logo:
        # imagem embutida no corpo HTML, referenciada por cid:logo_senar
        msg.get_payload()[1].add_related(logo, "image", "png", cid=f"<{_LOGO_CID}>", disposition="inline")

    servidor = current_app.config.get("MAIL_SERVER", "smtp.gmail.com")
    porta = current_app.config.get("MAIL_PORT", 465)

    # O envio é feito na hora (sem thread em segundo plano). No Vercel a
    # função é encerrada assim que a resposta é devolvida, então um envio
    # "em segundo plano" era interrompido antes de terminar e o e-mail
    # simplesmente não saía. O timeout evita a página ficar travada caso o
    # Gmail demore a responder.
    try:
        contexto = ssl.create_default_context()
        with smtplib.SMTP_SSL(servidor, porta, context=contexto, timeout=20) as smtp:
            smtp.login(usuario, senha)
            smtp.send_message(msg)
        return True
    except Exception:
        current_app.logger.exception("Falha ao enviar e-mail de aviso (assunto: %s).", assunto)
        return False


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

    return _enviar_email(
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

    return _enviar_email(
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
    """Devolutiva marcada para o funcionário: aviso só com a data. O e-mail
    não fala em recurso/recorrer — isso o funcionário vê e faz só dentro do
    sistema. (`data_limite` continua no parâmetro por compatibilidade com
    quem chama, mas não é mostrado aqui.)"""
    return _enviar_email(
        _email_funcionario(funcionario),
        "[Avaliação de Desempenho] Data de devolutiva marcada",
        titulo="Devolutiva marcada",
        paragrafos=[
            f"A data de devolutiva da sua avaliação foi marcada para "
            f"{data_devolutiva.strftime('%d/%m/%Y')}.",
        ],
        link_url=_link_minha_area(),
        link_texto="Acessar minha área",
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


# ---------------------------------------------------------------------------
# Senha: redefinição, aviso de troca e senha provisória
# ---------------------------------------------------------------------------
def avisar_redefinicao_senha(funcionario, link, validade_minutos):
    """Link para o colaborador criar uma senha nova ("esqueci minha senha")."""
    return _enviar_email(
        _email_funcionario(funcionario),
        "[Avaliação de Desempenho] Redefinição de senha",
        titulo="Redefinição de senha",
        paragrafos=[
            f"Olá, {funcionario.nome}. Recebemos um pedido para criar uma nova senha de acesso.",
            f"Use o botão abaixo para escolher a nova senha. O link vale por {validade_minutos} minutos "
            f"e só pode ser usado uma vez.",
            "Não foi você quem pediu? Ignore este e-mail: sua senha continua a mesma.",
        ],
        link_url=link,
        link_texto="Criar nova senha",
    )


def avisar_senha_alterada(funcionario):
    """Confirma a troca de senha, para a pessoa perceber se não foi ela."""
    return _enviar_email(
        _email_funcionario(funcionario),
        "[Avaliação de Desempenho] Sua senha foi alterada",
        titulo="Sua senha foi alterada",
        paragrafos=[
            f"Olá, {funcionario.nome}. A senha de acesso ao sistema acabou de ser alterada.",
            "Não reconhece essa alteração? Avise o RH imediatamente.",
        ],
        icone="\u2713",
        link_url=_link_minha_area(),
        link_texto="Acessar o sistema",
    )


def avisar_senha_provisoria(funcionario, senha):
    """Envia a senha provisória (aleatória) direto para o colaborador."""
    from flask import url_for

    try:
        link = url_for("main.login", _external=True)
    except RuntimeError:
        link = ""
    return _enviar_email(
        _email_funcionario(funcionario),
        "[Avaliação de Desempenho] Seu acesso ao sistema",
        titulo="Seu acesso ao sistema",
        paragrafos=[
            f"Olá, {funcionario.nome}. Seu acesso ao sistema de Avaliação de Desempenho foi criado.",
            f"Entre com o e-mail {funcionario.email} e a senha provisória abaixo. "
            f"No primeiro acesso você vai escolher uma senha só sua.",
        ],
        destaque=("Senha provisória", senha),
        destaque_mono=True,
        link_url=link,
        link_texto="Entrar no sistema",
    )
