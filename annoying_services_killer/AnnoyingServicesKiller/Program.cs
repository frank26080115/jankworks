using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Management;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.ServiceProcess;
using System.Threading;
using System.Windows.Forms;

namespace AnnoyingServicesKiller
{
    internal static class Program
    {
        // 🧲 Global mutex for singleton enforcement
        private static Mutex? _singleInstanceMutex;

        [STAThread]
        private static void Main()
        {
            // 🛡️ Ensure elevated (re-launch self with admin if not already elevated)
            if (!IsAdministrator())
            {
                try
                {
                    var exe = Process.GetCurrentProcess().MainModule!.FileName!;
                    var psi = new ProcessStartInfo(exe)
                    {
                        UseShellExecute = true,
                        Verb = "runas", // triggers UAC elevation
                        Arguments = string.Join(" ", Environment.GetCommandLineArgs().Skip(1).Select(QuoteArg))
                    };
                    Process.Start(psi);
                }
                catch
                {
                    MessageBox.Show("Elevation was required but declined. Exiting.", "AnnoyingServicesKiller", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
                return;
            }

            // 🔒 Try to be a singleton using a global mutex
            bool createdNew;
            _singleInstanceMutex = new Mutex(initiallyOwned: true, name: @"Global\AnnoyingServicesKiller_Singleton", createdNew: out createdNew);
            if (!createdNew)
            {
                // Optional: also detect duplicate by process list (belt + suspenders)
                var me = Process.GetCurrentProcess();
                var count = Process.GetProcessesByName(me.ProcessName).Count(p => p.MainModule?.FileName?.Equals(me.MainModule?.FileName, StringComparison.OrdinalIgnoreCase) == true);
                if (count > 1)
                {
                    // Already running, bail
                    return;
                }
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new TrayContext());
        }

        private static bool IsAdministrator()
        {
            using var identity = WindowsIdentity.GetCurrent();
            var principal = new WindowsPrincipal(identity);
            return principal.IsInRole(WindowsBuiltInRole.Administrator);
        }

        private static string QuoteArg(string a)
            => a.Contains(' ') || a.Contains('"') ? "\"" + a.Replace("\"", "\\\"") + "\"" : a;
    }

    /// <summary>
    /// 🪟 Tray-only context with a 5-minute patrol timer.
    /// </summary>
    internal sealed class TrayContext : ApplicationContext
    {
        private readonly NotifyIcon _tray;
        private readonly System.Windows.Forms.Timer _timer;

        // 📝 Configure your “never allowed” lists here:
        // Services are controlled by service name (not display name)
        private static readonly string[] ServiceNamesToKillAndDisable =
        {
            // 🧟 Office Click-to-Run
            "ClickToRunSvc",
            // add more service names as needed...
        };

        // Processes are by executable name (without path)
        private static readonly string[] ProcessNamesToKill =
        {
            "OfficeClickToRun",           // OfficeClickToRun.exe
            // add more process names, e.g., "SomeUpdater", "TelemetryAgent"
        };

        // Paths can be file or directory; directories are deleted recursively file-by-file best-effort
        private static readonly string[] PathsToDelete =
        {
            // Common Click-to-Run footprints (adjust to your install)
            // These may vary by machine/Office channel and language packs
            @"C:\Program Files\Common Files\Microsoft Shared\ClickToRun",
            @"C:\Program Files\Microsoft Office\root\Client",
            @"C:\ProgramData\Microsoft\ClickToRun",
            // add any other folders/files you want removed
        };

        public TrayContext()
        {
            // 🧭 Create tray icon + menu
            _tray = new NotifyIcon
            {
                Icon = System.Drawing.SystemIcons.Shield,   // Simple built-in icon
                Visible = true,
                Text = "AnnoyingServicesKiller — patrolling every 5 min"
            };

            var ctxMenu = new ContextMenuStrip();
            var exitItem = new ToolStripMenuItem("Exit");
            exitItem.Click += (_, __) => Exit();
            ctxMenu.Items.Add(exitItem);
            _tray.ContextMenuStrip = ctxMenu;

            // Run immediately on startup
            Patrol("startup");

            // ⏱️ Every 5 minutes thereafter
            _timer = new System.Windows.Forms.Timer { Interval = (int)TimeSpan.FromMinutes(5).TotalMilliseconds };
            _timer.Tick += (_, __) => Patrol("interval");
            _timer.Start();
        }

        private void Exit()
        {
            _timer.Stop();
            _tray.Visible = false;
            _tray.Dispose();
            Application.Exit();
        }

        private void Patrol(string reason)
        {
            try
            {
                // 🧹 Step 1: Stop + disable services
                foreach (var svcName in ServiceNamesToKillAndDisable.Distinct(StringComparer.OrdinalIgnoreCase))
                {
                    TryStopService(svcName, TimeSpan.FromSeconds(20));
                    TryDisableService(svcName);
                }

                // 🔫 Step 2: Kill processes
                foreach (var proc in ProcessNamesToKill.Distinct(StringComparer.OrdinalIgnoreCase))
                {
                    TryKillAllProcesses(proc);
                }

                // 🗑️ Step 3: Delete paths (files first, then folders)
                foreach (var path in PathsToDelete.Distinct(StringComparer.OrdinalIgnoreCase))
                {
                    TryDeletePathBestEffort(path);
                }

                // 📣 (Optional) brief balloon for first run or debugging
                // _tray.ShowBalloonTip(2000, "AnnoyingServicesKiller", $"Patrol complete ({reason})", ToolTipIcon.Info);
            }
            catch (Exception ex)
            {
                // Quietly log to Debug; app remains invisible
                Debug.WriteLine($"[AnnoyingServicesKiller] Patrol error: {ex}");
            }
        }

        // 🧯 SERVICES

        private static void TryStopService(string serviceName, TimeSpan wait)
        {
            try
            {
                using var sc = new ServiceController(serviceName);
                if (sc.Status == ServiceControllerStatus.Running || sc.Status == ServiceControllerStatus.StartPending)
                {
                    sc.Stop();
                    sc.WaitForStatus(ServiceControllerStatus.Stopped, wait);
                }
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[Service] Stop failed ({serviceName}): {ex.Message}");
                // Fallback: try sc.exe stop
                TryRunHidden("sc.exe", $"stop \"{serviceName}\"", TimeSpan.FromSeconds(10));
            }
        }

        private static void TryDisableService(string serviceName)
        {
            // Preferred: WMI set StartMode = Disabled
            try
            {
                using var mc = new ManagementObject($"Win32_Service.Name='{serviceName}'");
                var inParams = mc.GetMethodParameters("ChangeStartMode");
                inParams["StartMode"] = "Disabled";
                var outParams = mc.InvokeMethod("ChangeStartMode", inParams, null);
                Debug.WriteLine($"[Service] Disable via WMI ({serviceName}) => Return: {outParams?["ReturnValue"]}");
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[Service] Disable via WMI failed ({serviceName}): {ex.Message}");
                // Fallback: sc.exe config
                TryRunHidden("sc.exe", $"config \"{serviceName}\" start= disabled", TimeSpan.FromSeconds(10));
            }
        }

        // 🔪 PROCESSES

        private static void TryKillAllProcesses(string processNameNoExt)
        {
            try
            {
                var me = Process.GetCurrentProcess();
                foreach (var p in Process.GetProcessesByName(processNameNoExt))
                {
                    // Don’t kill ourselves by name collision
                    if (SafeEqualsPaths(p.MainModule?.FileName, me.MainModule?.FileName))
                        continue;

                    try
                    {
                        p.Kill(entireProcessTree: true);
                        p.WaitForExit(8000);
                    }
                    catch (Exception ex)
                    {
                        Debug.WriteLine($"[Process] Kill failed ({p.ProcessName}:{p.Id}): {ex.Message}");
                    }
                }
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[Process] Enumeration failed ({processNameNoExt}): {ex.Message}");
            }
        }

        private static bool SafeEqualsPaths(string? a, string? b)
            => a != null && b != null && string.Equals(Path.GetFullPath(a), Path.GetFullPath(b), StringComparison.OrdinalIgnoreCase);

        // 🗑️ DELETION (best-effort, file-by-file)

        private static void TryDeletePathBestEffort(string path)
        {
            try
            {
                if (File.Exists(path))
                {
                    TryDeleteFile(path);
                    return;
                }

                if (Directory.Exists(path))
                {
                    TryDeleteDirectoryRecursive(path);
                }
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[Delete] Error on '{path}': {ex.Message}");
            }
        }

        private static void TryDeleteFile(string file)
        {
            try
            {
                ClearReadOnly(file);
                File.Delete(file);
            }
            catch (IOException)
            {
                // Try remove attributes then attempt again
                try
                {
                    ClearReadOnly(file);
                    File.Delete(file);
                }
                catch (Exception ex)
                {
                    Debug.WriteLine($"[Delete] File failed '{file}': {ex.Message}");
                }
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[Delete] File failed '{file}': {ex.Message}");
            }
        }

        private static void TryDeleteDirectoryRecursive(string dir)
        {
            // Delete children first (files -> subdirs), then the directory
            try
            {
                foreach (var f in SafeEnumFiles(dir))
                {
                    TryDeleteFile(f);
                }

                foreach (var d in SafeEnumDirectories(dir))
                {
                    TryDeleteDirectoryRecursive(d);
                }

                // Attempt to delete directory itself
                try
                {
                    ClearReadOnly(dir);
                    Directory.Delete(dir, recursive: false);
                }
                catch (Exception ex)
                {
                    Debug.WriteLine($"[Delete] Directory failed '{dir}': {ex.Message}");
                }
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[Delete] Recursive failed '{dir}': {ex.Message}");
            }
        }

        private static IEnumerable<string> SafeEnumFiles(string dir)
        {
            try { return Directory.EnumerateFiles(dir); }
            catch (Exception ex) { Debug.WriteLine($"[Enum] Files failed '{dir}': {ex.Message}"); return Enumerable.Empty<string>(); }
        }

        private static IEnumerable<string> SafeEnumDirectories(string dir)
        {
            try { return Directory.EnumerateDirectories(dir); }
            catch (Exception ex) { Debug.WriteLine($"[Enum] Dirs failed '{dir}': {ex.Message}"); return Enumerable.Empty<string>(); }
        }

        private static void ClearReadOnly(string path)
        {
            try
            {
                var attrs = File.GetAttributes(path);
                if ((attrs & FileAttributes.ReadOnly) != 0)
                {
                    attrs &= ~FileAttributes.ReadOnly;
                    File.SetAttributes(path, attrs);
                }
            }
            catch { /* best-effort */ }
        }

        // 🧰 UTIL

        private static void TryRunHidden(string fileName, string arguments, TimeSpan timeout)
        {
            try
            {
                using var p = new Process
                {
                    StartInfo = new ProcessStartInfo
                    {
                        FileName = fileName,
                        Arguments = arguments,
                        CreateNoWindow = true,
                        WindowStyle = ProcessWindowStyle.Hidden,
                        UseShellExecute = false,
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                    }
                };
                p.Start();
                if (!p.WaitForExit((int)timeout.TotalMilliseconds))
                {
                    try { p.Kill(); } catch { /* ignore */ }
                }
                Debug.WriteLine($"[Exec] {fileName} {arguments} => {p.ExitCode}");
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[Exec] Failed '{fileName} {arguments}': {ex.Message}");
            }
        }
    }
}
