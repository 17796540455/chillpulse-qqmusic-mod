// ============================================================================
//  ChillPulse QQ Music mod - UndertaleModTool patch script
//
//  Run with:
//    UndertaleModCli.exe load <data.win> -s apply_mod.csx -o <data_patched.win>
//
//  Set QQM_ROOT to the workspace root (defaults to the current directory).
//
//  The mod is injected as *methods on obj_controller* rather than as a new
//  script asset: the GameMaker runner only exposes script-asset functions
//  under names derived from the asset, so freshly created global functions
//  become `gml_Script_<fn>@<script>` and cannot be called by their plain
//  name.  Every caller lives in one of obj_controller's own events, so
//  instance-variable methods are both correct and naming-independent.
// ============================================================================

using System;
using System.IO;
using System.Linq;
using UndertaleModLib;
using UndertaleModLib.Compiler;
using UndertaleModLib.Models;

EnsureDataLoaded();

string root = Environment.GetEnvironmentVariable("QQM_ROOT");
if (string.IsNullOrEmpty(root))
{
    root = Directory.GetCurrentDirectory();
}
string methodsPath = Path.Combine(root, "mods", "patch", "qqm_methods.gml");
if (!File.Exists(methodsPath))
{
    throw new FileNotFoundException("Cannot find the mod GML source.", methodsPath);
}
string methods = File.ReadAllText(methodsPath);
Console.WriteLine("QQM: methods source " + methodsPath + " (" + methods.Length + " chars)");

UndertaleCode FindCode(string name)
{
    UndertaleCode c = Data.Code.FirstOrDefault(x => x.Name != null && x.Name.Content == name);
    if (c == null)
    {
        throw new Exception("QQM: required code entry not found: " + name);
    }
    return c;
}

var group = new CodeImportGroup(Data, null, Data.ToolInfo.DecompilerSettings)
{
    AutoCreateAssets = false,
    ThrowOnNoOpFindReplace = true,
    MainThreadAction = MainThreadAction
};

UndertaleCode cCreate = FindCode("gml_Object_obj_controller_Create_0");
UndertaleCode cStep = FindCode("gml_Object_obj_controller_Step_0");
UndertaleCode cDraw = FindCode("gml_Object_obj_controller_Draw_64");
UndertaleCode cOther = FindCode("gml_Object_obj_controller_Other_62");

// --- 1. method definitions first, then the state initialiser ----------------
group.QueuePrepend(cCreate, methods);
group.QueueAppend(cCreate, "qqm_init();");

// --- 2. hooks in the other controller events -------------------------------
group.QueueAppend(cStep, "qqm_step();");
group.QueueAppend(cDraw, "qqm_draw();");
group.QueueAppend(cOther, "qqm_async(async_load);");

// --- 3. let the QQ stream own the stock player while it is loaded ----------
//     (prev / next / play-pause handlers)
group.QueueFindReplace(cStep,
    "ms_click && array_length(music_names) > 0 && !page_customization",
    "ms_click && array_length(music_names) > 0 && !page_customization && qqm_sound == -1",
    false);

//     (the stock auto-advance must not fight the QQ stream)
group.QueueFindReplace(cStep,
    "if (audio_is_playing(current_music) == false && array_length(music_list) > 0)",
    "if (audio_is_playing(current_music) == false && array_length(music_list) > 0 && qqm_sound == -1)",
    false);

// --- 4. music panel: the QQ tab replaces the cassette list body ------------
group.QueueFindReplace(cDraw,
    "if (page_music_list == 1)",
    "if (page_music_list == 1 && qqm_open == 0)",
    false);

// --- 5. player bar shows the QQ track title while one is playing ----------
group.QueueFindReplace(cDraw,
    "draw_text_ext_transformed(60, mp_y + 2, music_names[current_music_index], 60, 1000, 0.3, 0.3, 0);",
    "draw_text_ext_transformed(60, mp_y + 2, qqm_bar_title(), 60, 1000, 0.3, 0.3, 0);",
    false);

Console.WriteLine("QQM: importing (compile + relink) ...");
group.Import();

Console.WriteLine("QQM: code entries now: " + Data.Code.Count + ", scripts: " + Data.Scripts.Count);
Console.WriteLine("QQM: patch applied successfully.");
