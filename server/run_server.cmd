@echo off
rem Start the PC-side server detached from any console or agent session.
rem
rem Set TV_PY to the interpreter the Windows firewall permits. The firewall rule
rem is per program path, so a renamed copy of Python (e.g. pysrv.exe) is the
rem usual choice; plain "python" is the default.
rem
rem -u keeps stdout/stderr unbuffered: without it the task log lags by minutes
rem and looks like the server is hung. The log is appended (>>) on purpose so a
rem restart never erases the previous run; delete it by hand if it grows.
setlocal
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
set "PY=%TV_PY%"
if "%PY%"=="" set "PY=python"
where "%PY%" >nul 2>nul
if errorlevel 1 (
  echo [run_server] interpreter not found: "%PY%"
  echo [run_server] set TV_PY to a full path the firewall permits, e.g. pysrv.exe
  exit /b 1
)
netstat -ano | findstr /r /c:":80 .*LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo [run_server] something is already listening on :80 - stop it first
  echo [run_server] ^(a second instance just tracebacks into the log^)
  exit /b 1
)
"%PY%" -u server.py >> "logs\server.task.out" 2>> "logs\server.task.err"
