' Silent background launcher - delegates to scripts\start_server.ps1

Option Explicit

Dim fso, shell, root, ps1, cmd, logPath, logFile

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = root & "\scripts\start_server.ps1"
logPath = root & "\logs"
logFile = logPath & "\autostart.log"

Sub WriteLog(msg)
  On Error Resume Next
  If Not fso.FolderExists(logPath) Then fso.CreateFolder logPath
  Dim ts
  Set ts = fso.OpenTextFile(logFile, 8, True, -1)
  ts.WriteLine Now & " " & msg
  ts.Close
End Sub

WriteLog "launch_silent.vbs started"

If Not fso.FileExists(ps1) Then
  WriteLog "ERROR: start_server.ps1 missing: " & ps1
  WScript.Quit 1
End If

shell.CurrentDirectory = root
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """"
WriteLog "Run: " & cmd
shell.Run cmd, 0, True
WriteLog "powershell exited"
