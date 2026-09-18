$ErrorActionPreference = 'Stop'
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class ConsoleSignal {
    [DllImport("kernel32.dll", SetLastError=true)] public static extern bool FreeConsole();
    [DllImport("kernel32.dll", SetLastError=true)] public static extern bool AttachConsole(uint pid);
    [DllImport("kernel32.dll", SetLastError=true)] public static extern bool SetConsoleCtrlHandler(IntPtr handler, bool ignore);
    [DllImport("kernel32.dll", SetLastError=true)] public static extern bool GenerateConsoleCtrlEvent(uint signal, uint group);
}
'@
$launcherProcess = Start-Process -FilePath $env:IBL_TEST_NODE -ArgumentList ('"' + $env:IBL_TEST_SCRIPT + '"') -WindowStyle Hidden -PassThru
try {
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while (!(Test-Path -LiteralPath $env:IBL_TEST_READY)) {
        if ([DateTime]::UtcNow -gt $deadline -or $launcherProcess.HasExited) { throw 'Launcher did not become ready.' }
        Start-Sleep -Milliseconds 50
    }
    $childInfo = Get-Content -LiteralPath $env:IBL_TEST_READY -Raw | ConvertFrom-Json
    [ConsoleSignal]::FreeConsole() | Out-Null
    if (![ConsoleSignal]::AttachConsole([uint32]$launcherProcess.Id)) { throw 'Cannot attach test console.' }
    [ConsoleSignal]::SetConsoleCtrlHandler([IntPtr]::Zero, $true) | Out-Null
    if (![ConsoleSignal]::GenerateConsoleCtrlEvent(0, 0)) { throw 'Cannot send Ctrl+C.' }
    if (!$launcherProcess.WaitForExit(10000)) { throw 'Launcher remained alive after Ctrl+C.' }
    if ($launcherProcess.ExitCode -eq 0) { throw 'Cancellation must return a nonzero exit code.' }
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    while (Get-Process -Id $childInfo.pid -ErrorAction SilentlyContinue) {
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Child remained alive after Ctrl+C.' }
        Start-Sleep -Milliseconds 50
    }
} finally {
    if (!$launcherProcess.HasExited) { $launcherProcess.Kill($true) }
    [ConsoleSignal]::FreeConsole() | Out-Null
}
