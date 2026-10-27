' Launch run_server.cmd with no console window.
'
' Why: the server is a console program. Windows terminates a console program when
' its console goes away - and when the server runs from Task Scheduler, that console
' belongs to the scheduler and can vanish, which kills the server with no traceback
' and makes the TV page go blank a few seconds after it loads. wscript has no console
' to close, so the server survives.
'
' Register it as a scheduled task (see docs/SERVER-HOSTING.md):
'   schtasks /Create /TN "TV-LabServer" /TR "wscript.exe \"<path>\run_server.vbs\"" ^
'            /SC ONCE /ST 23:59 /F
' Note: /RL HIGHEST needs elevation and will fail without it.

Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)

Set sh = CreateObject("WScript.Shell")
sh.Run "cmd /c """ & here & "\run_server.cmd""", 0, False
