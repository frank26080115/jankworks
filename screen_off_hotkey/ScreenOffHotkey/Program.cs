// Program.cs
// Project: ScreenOffHotkey (.NET Framework 4.8)
// One-file WinForms tray app: single-instance, delayed turn-off monitor, quit,
// and hotkey sequence: CTRL+SHIFT+ALT+Q then CTRL+SHIFT+ALT+W within 2s => screen off (1s delay).

using System;
using System.Diagnostics;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace ScreenOffHotkey
{
    internal static class Program
    {
        private static Mutex _singleInstanceMutex;

        [STAThread]
        private static void Main()
        {
            // Fast path: bail if another process with same name is already running.
            try
            {
                string thisName = Process.GetCurrentProcess().ProcessName;
                if (Process.GetProcessesByName(thisName).Length > 1)
                {
                    return; // Another instance is running
                }
            }
            catch { }

            bool createdNew;
            _singleInstanceMutex = new Mutex(true, "ScreenOffHotkey_SingleInstance_Mutex", out createdNew);
            if (!createdNew)
            {
                return; // Another instance owns the mutex
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            try
            {
                using (TrayAppContext ctx = new TrayAppContext())
                {
                    Application.Run(ctx);
                }
            }
            finally
            {
                try { _singleInstanceMutex.ReleaseMutex(); } catch { }
                _singleInstanceMutex.Dispose();
            }
        }
    }

    internal sealed class TrayAppContext : ApplicationContext
    {
        private readonly NotifyIcon _tray;
        private readonly ContextMenuStrip _menu;
        private readonly HotkeyWindow _hotkeys;

        // Sequence state
        private DateTime _lastQTimeUtc = DateTime.MinValue;
        private readonly TimeSpan _comboWindow = TimeSpan.FromSeconds(2);

        public TrayAppContext()
        {
            // Build menu
            _menu = new ContextMenuStrip();

            ToolStripMenuItem turnOffItem = new ToolStripMenuItem(
                "Turn Off Screen (2s delay)", null,
                delegate { MonitorController.ScheduleTurnOff(2000); });

            ToolStripSeparator sep = new ToolStripSeparator();

            ToolStripMenuItem quitItem = new ToolStripMenuItem(
                "Quit", null,
                delegate { ExitThread(); });

            _menu.Items.Add(turnOffItem);
            _menu.Items.Add(sep);
            _menu.Items.Add(quitItem);

            // Tray icon
            _tray = new NotifyIcon();
            _tray.Icon = SystemIcons.Application;
            _tray.Visible = true;
            _tray.Text = "ScreenOffHotkey";
            _tray.ContextMenuStrip = _menu;
            _tray.DoubleClick += delegate { MonitorController.ScheduleTurnOff(2000); };

            // Hotkeys
            _hotkeys = new HotkeyWindow();
            _hotkeys.HotkeyPressed += OnHotkeyPressed;
            _hotkeys.RegisterComboHotkeys(); // CTRL+SHIFT+ALT+Q and +W
        }

        private void OnHotkeyPressed(int id)
        {
            if (id == HotkeyWindow.ID_Q)
            {
                _lastQTimeUtc = DateTime.UtcNow;
                // Optional feedback (uncomment if you want a heads-up):
                // _tray.ShowBalloonTip(1000, "Armed", "Press CTRL+SHIFT+ALT+W within 2 seconds to turn off screen.", ToolTipIcon.Info);
            }
            else if (id == HotkeyWindow.ID_W)
            {
                if (_lastQTimeUtc != DateTime.MinValue &&
                    (DateTime.UtcNow - _lastQTimeUtc) <= _comboWindow)
                {
                    _lastQTimeUtc = DateTime.MinValue; // reset after success
                    MonitorController.ScheduleTurnOff(1000); // 1s delay on success
                }
                else
                {
                    // If W arrived too late or without Q, ignore.
                    // _tray.ShowBalloonTip(700, "Too late", "Hotkey combo timed out.", ToolTipIcon.None);
                }
            }
        }

        protected override void ExitThreadCore()
        {
            try
            {
                _hotkeys.Dispose();
                _tray.Visible = false;
                _tray.Dispose();
                _menu.Dispose();
            }
            catch { }
            base.ExitThreadCore();
        }
    }

    /// <summary>
    /// Hidden message window that registers and receives global hotkeys.
    /// </summary>
    internal sealed class HotkeyWindow : NativeWindow, IDisposable
    {
        // Hotkey IDs (must be unique per window)
        public const int ID_Q = 0x1001;
        public const int ID_W = 0x1002;

        // Win32
        private const int WM_HOTKEY = 0x0312;
        private const uint MOD_ALT = 0x0001;
        private const uint MOD_CONTROL = 0x0002;
        private const uint MOD_SHIFT = 0x0004;
        // private const uint MOD_WIN = 0x0008;

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool UnregisterHotKey(IntPtr hWnd, int id);

        public event Action<int> HotkeyPressed;

        public HotkeyWindow()
        {
            CreateHandle(new CreateParams()); // create an invisible message-only window
        }

        public void RegisterComboHotkeys()
        {
            uint mods = MOD_CONTROL | MOD_SHIFT | MOD_ALT;

            // VK codes are the same as (uint)Keys.X
            bool okQ = RegisterHotKey(Handle, ID_Q, mods, (uint)Keys.Q);
            bool okW = RegisterHotKey(Handle, ID_W, mods, (uint)Keys.W);

            // If registration fails (e.g., already in use), we silently continue.
            // You could add a MessageBox or tray balloon here if desired.
        }

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == WM_HOTKEY)
            {
                int id = m.WParam.ToInt32();
                var handler = HotkeyPressed;
                if (handler != null)
                    handler(id);
            }
            base.WndProc(ref m);
        }

        public void Dispose()
        {
            try { UnregisterHotKey(Handle, ID_Q); } catch { }
            try { UnregisterHotKey(Handle, ID_W); } catch { }
            try { DestroyHandle(); } catch { }
        }
    }

    internal static class MonitorController
    {
        [DllImport("user32.dll", SetLastError = false)]
        private static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);

        private static readonly IntPtr HWND_BROADCAST = new IntPtr(0xFFFF);
        private const uint WM_SYSCOMMAND = 0x0112;
        private static readonly IntPtr SC_MONITORPOWER = new IntPtr(0xF170);
        // lParam values: -1 = on, 1 = low power, 2 = off

        public static void ScheduleTurnOff(int delayMs)
        {
            var t = new System.Windows.Forms.Timer();
            t.Interval = delayMs;
            t.Tick += (s, e) =>
            {
                try { TurnOffMonitors(); }
                finally
                {
                    t.Stop();
                    t.Dispose();
                }
            };
            t.Start();
        }

        public static void TurnOffMonitors()
        {
            try
            {
                SendMessage(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, new IntPtr(2));
            }
            catch { }
        }
    }
}
