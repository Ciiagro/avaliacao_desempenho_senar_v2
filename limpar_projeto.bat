@echo off
REM ------------------------------------------------------------
REM Limpeza do projeto: apaga copias duplicadas e arquivos antigos
REM que o sistema NAO usa. Rode UMA vez, na pasta do projeto
REM (a mesma pasta onde ficam run.py e wsgi.py).
REM
REM Apaga:
REM   app\app\            copia antiga de main.py e recursos.py
REM   templates\          template antigo (o sistema usa app\templates\)
REM   python\             trechos de codigo soltos (*_snippet.py)
REM   025_devolutiva_por_funcionario.sql   duplicado de sql\025_...
REM
REM NAO mexe em: banco de dados, .env, venv, sql\, app\ (codigo real).
REM ------------------------------------------------------------
if not exist run.py (
    echo Rode este arquivo dentro da pasta do projeto, onde fica o run.py.
    pause
    exit /b 1
)
echo Vai apagar: app\app, templates, python e 025_devolutiva_por_funcionario.sql
set /p OK=Digite S para continuar: 
if /i not "%OK%"=="S" (
    echo Cancelado.
    pause
    exit /b 0
)
if exist app\app rmdir /s /q app\app
if exist templates rmdir /s /q templates
if exist python rmdir /s /q python
if exist 025_devolutiva_por_funcionario.sql del /q 025_devolutiva_por_funcionario.sql
echo.
echo Pronto. Teste o sistema (python run.py) antes de enviar para o Vercel.
pause
