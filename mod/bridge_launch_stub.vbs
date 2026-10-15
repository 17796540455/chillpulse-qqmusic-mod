' ===========================================================================
'  Forwarder stub.
'
'  The mod was moved out of the Steam library to E:\ChillPulseQQMod so that
'  verifying / reinstalling / updating the game cannot delete it.  Only the
'  patched data.win and the ogg cache have to stay inside the game folder.
'
'  This stub keeps an existing Steam launch option that still points at the
'  old path working.  A fresh setup should point straight at
'      E:\ChillPulseQQMod\bridge_launch.vbs
' ===========================================================================
Option Explicit

Dim sh, cmd, i, target
Set sh = CreateObject("WScript.Shell")
target = "E:\ChillPulseQQMod\bridge_launch.vbs"

cmd = """C:\Windows\System32\wscript.exe"" """ & target & """"
For i = 0 To WScript.Arguments.Count - 1
    cmd = cmd & " """ & WScript.Arguments(i) & """"
Next

sh.Run cmd, 0, True
