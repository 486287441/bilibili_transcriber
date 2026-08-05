using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;

[assembly: AssemblyTitle("Bilibili Transcriber")]
[assembly: AssemblyDescription("Bilibili Transcriber - login startup launcher")]
[assembly: AssemblyProduct("Bilibili Transcriber")]

internal static class BilibiliTranscriberLauncher
{
    private static int Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string launcher = Path.Combine(root, "launch_silent.vbs");
        if (!File.Exists(launcher))
        {
            return 1;
        }

        Process.Start(new ProcessStartInfo
        {
            FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", "wscript.exe"),
            Arguments = "//B \"" + launcher + "\"",
            WorkingDirectory = root,
            UseShellExecute = false,
            CreateNoWindow = true,
        });
        return 0;
    }
}
