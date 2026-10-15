Option Explicit
Dim shell, files, project, launcher, result
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
project = files.GetParentFolderName(files.GetParentFolderName(WScript.ScriptFullName))
launcher = files.BuildPath(project, "scripts\start_tris_ai.ps1")
shell.CurrentDirectory = project
result = shell.Run("powershell.exe -NoProfile -ExecutionPolicy Bypass -File " & Chr(34) & launcher & Chr(34), 0, True)
If result <> 0 Then
    MsgBox "Ai building / Tris AI could not start. Check the newest workspace log in:" & vbCrLf & files.BuildPath(project, "data") & vbCrLf & "You can also run start_tris_ai.bat to see the startup error.", vbExclamation, "Ai building"
End If
