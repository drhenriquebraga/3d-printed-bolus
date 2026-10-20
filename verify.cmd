@echo off
setlocal
set "R=%~dp0"
cd /d "%R%"
set "LOG=%R%verify_log.txt"
set "PY="
if exist "%R%_python.txt" set /p PY=<"%R%_python.txt"
if defined PY if not exist "%PY%" set "PY="
if not defined PY (
  echo ERRO: crie o _python.txt com o caminho do python.exe do .venv da Suite.
  echo ERRO: _python.txt ausente> "%LOG%"
  pause
  exit /b 1
)
set "SUITE="
for /d %%D in ("%R%..\*") do if exist "%%D\tools\_componentes.py" set "SUITE=%%D"
if not defined SUITE (
  echo ERRO: nao achei a Suite ^(a pasta irma com tools\_componentes.py^).
  echo ERRO: Suite ausente> "%LOG%"
  pause
  exit /b 1
)
echo Rodando as baterias deste projeto... ^(a saida completa vai para o log^)
"%PY%" "%SUITE%\tools\_componentes.py" --verificar "%R%." > "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
findstr /B /C:"OK:" /C:"FALHOU:" /C:"===" /C:"  FALHOU" "%LOG%"
echo.
if "%RC%"=="0" (echo TUDO OK) else (echo FALHOU - veja %LOG%)
pause
exit /b %RC%
