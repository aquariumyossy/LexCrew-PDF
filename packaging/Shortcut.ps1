param(
    [Parameter(Mandatory = $true)][string]$AppRoot,
    [string]$LinkPath,
    [switch]$Read
)

$ErrorActionPreference = "Stop"

if (-not ("LexCrew.ShortcutStore" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

namespace LexCrew {
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    public struct ShortcutPropertyKey {
        public Guid FormatId;
        public uint PropertyId;
    }

    [StructLayout(LayoutKind.Explicit, Size = 24)]
    public struct ShortcutPropVariant {
        [FieldOffset(0)] public ushort VariantType;
        [FieldOffset(8)] public IntPtr Pointer;
    }

    [ComImport]
    [Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IShortcutPropertyStore {
        void GetCount(out uint count);
        void GetAt(uint index, out ShortcutPropertyKey key);
        void GetValue(ref ShortcutPropertyKey key, out ShortcutPropVariant value);
        void SetValue(ref ShortcutPropertyKey key, ref ShortcutPropVariant value);
        void Commit();
    }

    [ComImport]
    [Guid("0000010b-0000-0000-C000-000000000046")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IShortcutPersistFile {
        void GetClassID(out Guid classId);
        [PreserveSig] int IsDirty();
        void Load([MarshalAs(UnmanagedType.LPWStr)] string fileName, uint mode);
        void Save([MarshalAs(UnmanagedType.LPWStr)] string fileName, bool remember);
        void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string fileName);
        void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string fileName);
    }

    [ComImport]
    [Guid("00021401-0000-0000-C000-000000000046")]
    public class ShortcutShellLink {
    }

    public static class ShortcutStore {
        [DllImport("ole32.dll")]
        static extern int PropVariantClear(ref ShortcutPropVariant value);

        [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
        static extern int SHGetPropertyStoreFromParsingName(
            string path,
            IntPtr bindContext,
            uint flags,
            ref Guid interfaceId,
            [MarshalAs(UnmanagedType.Interface)] out IShortcutPropertyStore store);

        static ShortcutPropertyKey AppIdKey() {
            var key = new ShortcutPropertyKey();
            key.FormatId = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
            key.PropertyId = 5;
            return key;
        }

        static IShortcutPropertyStore Open(string path) {
            var interfaceId = typeof(IShortcutPropertyStore).GUID;
            IShortcutPropertyStore store;
            int hr = SHGetPropertyStoreFromParsingName(path, IntPtr.Zero, 2, ref interfaceId, out store);
            if (hr != 0) {
                throw new System.ComponentModel.Win32Exception(hr);
            }
            return store;
        }

        public static void SetAppId(string path, string appId) {
            var store = Open(path);
            var key = AppIdKey();
            var value = new ShortcutPropVariant();
            value.VariantType = 31;
            value.Pointer = Marshal.StringToCoTaskMemUni(appId);
            try {
                store.SetValue(ref key, ref value);
                store.Commit();
            } finally {
                PropVariantClear(ref value);
                Marshal.ReleaseComObject(store);
            }
        }

        public static string GetAppId(string path) {
            var store = Open(path);
            var key = AppIdKey();
            ShortcutPropVariant value;
            store.GetValue(ref key, out value);
            try {
                if (value.Pointer == IntPtr.Zero) {
                    return "";
                }
                return Marshal.PtrToStringUni(value.Pointer);
            } finally {
                PropVariantClear(ref value);
                Marshal.ReleaseComObject(store);
            }
        }
    }
}
"@
}

function Get-LexCrewShortcutId {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [LexCrew.ShortcutStore]::GetAppId($Path)
}

if ($Read) {
    Write-Output (Get-LexCrewShortcutId -Path $LinkPath)
    return
}

$root = (Resolve-Path -LiteralPath $AppRoot).Path
Get-ChildItem -LiteralPath $root -Recurse -File | Unblock-File

if (-not $LinkPath) {
    $shell = New-Object -ComObject WScript.Shell
    $LinkPath = Join-Path $shell.SpecialFolders("Desktop") "LexCrew-PDF.lnk"
}

$pythonw = Join-Path $root "runtime\pythonw.exe"
$icon = Join-Path $root "LexCrew-PDF.ico"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($LinkPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "-m lexcrew_pdf"
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = "$icon,0"
$shortcut.WindowStyle = 1
$shortcut.Description = "LexCrew-PDF"
$shortcut.Save()
[void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut)
[LexCrew.ShortcutStore]::SetAppId($LinkPath, "LexCrew.PDF")
[void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
[GC]::Collect()
[GC]::WaitForPendingFinalizers()
