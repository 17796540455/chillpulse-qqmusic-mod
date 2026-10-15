' ===========================================================================
'  bridge_launch.vbs -- the one entry point that makes the mod work.
'
'  1. make sure the patched data.win is in place (Steam restores it on verify)
'  2. start the QQ Music bridge silently if it is not running
'  3. launch the game
'
'  Usage A - as a Steam launch option (works when starting from the library):
'     right-click ChillPulse -> Properties -> Launch Options, paste:
'       C:\Windows\System32\wscript.exe "E:\ChillPulseQQMod\bridge_launch.vbs" %command%
'
'     NOTE: Steam resolves the FIRST token as an executable path and does NOT
'     search PATH, so a bare "wscript.exe" fails with
'     "Failed to start game (missing executable)".  The full path is required.
'
'  Usage B - no arguments (desktop shortcut): starts the game via Steam itself.
'
'  No window is ever shown: the bridge runs under pyw.exe and this script runs
'  under wscript.exe.  ASCII only on purpose - the VBScript host reads .vbs as
'  ANSI, so non-ASCII comments corrupt the parser.
'
'  This folder is deliberately OUTSIDE the Steam library so that verifying or
'  reinstalling the game cannot delete it.
' ===========================================================================
Option Explicit

Dim sh, fso, base, pyw, bridge, guard, gameDir
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

base    = fso.GetParentFolderName(WScript.ScriptFullName) & "\"
bridge  = base & "qqbridge.py"
guard   = base & "mod_guard.py"
pyw     = "C:\Windows\pyw.exe"
gameDir = "E:\steam\steam\steamapps\common\ChillPulse"

' game_dir.txt next to this script overrides the game folder
Dim dirFile
dirFile = base & "game_dir.txt"
If fso.FileExists(dirFile) Then
    Dim ts, custom
    Set ts = fso.OpenTextFile(dirFile, 1)
    custom = Trim(ts.ReadLine())
    ts.Close
    If Len(custom) > 0 Then gameDir = Replace(custom, """", "")
End If

If Not fso.FileExists(bridge) Then
    MsgBox "bridge not found: " & bridge, 16, "QQ Music bridge"
    WScript.Quit 1
End If
If Not fso.FileExists(pyw) Then pyw = "pythonw.exe"

' ---- 0) clear a stale "game is running" record in Steam -------------------
'      When the game exits, Steam occasionally never finishes the stop:  the
'      library keeps showing Stop, the Play button stays disabled and the save
'      cannot sync, even though nothing is running.  Only a Steam restart gets
'      out of it, so do that automatically before launching.
Dim unstick
unstick = base & "steam_unstick.py"
If fso.FileExists(unstick) Then
    sh.Run """" & pyw & """ """ & unstick & """", 0, True
End If

' ---- 1) repair data.win if Steam restored the vanilla one ------------------
'      mod_guard only ever writes when it recognises the exact vanilla build,
'      so a game update is left alone.  Wait for it: the game must not start
'      before the file is back in place.
If fso.FileExists(guard) Then
    sh.Run """" & pyw & """ """ & guard & """", 0, True
End If

' ---- 2) start the bridge (if one is already running the new process simply
'         fails to bind the port and exits - harmless)
Dim bridgeArgs
bridgeArgs = " -3 """ & bridge & """" & _
             " --port 38612 --game-dir """ & gameDir & """" & _
             " --cache-mb 1024 --quality 128"
sh.Run """" & pyw & """" & bridgeArgs, 0, False

' give it a moment to come up
WScript.Sleep 1200

' ---- 3) launch the game ---------------------------------------------------
Dim cmd, i
If WScript.Arguments.Count > 0 Then
    ' Steam expanded %command% into our arguments: run it verbatim and wait,
    ' so Steam keeps tracking the real game process.
    cmd = ""
    For i = 0 To WScript.Arguments.Count - 1
        If i > 0 Then cmd = cmd & " "
        cmd = cmd & """" & WScript.Arguments(i) & """"
    Next
    sh.Run cmd, 1, True
Else
    ' No arguments: let Steam start it, exactly like pressing Play in the library.
    sh.Run "steam://rungameid/2826180", 1, False
End If
