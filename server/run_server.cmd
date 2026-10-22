@echo off
rem Start the PC-side server detached from any console or agent session.
rem
rem Set TV_PY to the interpreter the Windows firewall permits. The firewall rule
rem is per program path, so a renamed copy of Python (e.g. pysrv.exe) is the
rem usual choice; plain "python" is the default.
setlocal
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
set "PY=%TV_PY%"
if "%PY%"=="" set "PY=python"
"%PY%" server.py >> "logs\server.task.out" 2>> "logs\server.task.err"
