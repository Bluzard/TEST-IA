# Configuración principal + ablaciones del experto de código (secuencial, ~30 min en la RTX 5060 Ti).
#   powershell -ExecutionPolicy Bypass -File .\correr_ablaciones.ps1
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"
Add-Type -Namespace Win32 -Name Energia -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
[Win32.Energia]::SetThreadExecutionState(0x80000001) | Out-Null
$py = ".\.venv\Scripts\python.exe"
$corridas = @(
    @("base",       @("--r", "0")),
    @("r8_todas",   @("--r", "8", "--pen_extra", "1.1")),
    @("r4",         @("--r", "4")),
    @("r16",        @("--r", "16")),
    @("atencion",   @("--r", "8", "--objetivos", "qkv", "proy")),
    @("r8_semilla1", @("--r", "8", "--semilla", "1"))
)
try {
    foreach ($c in $corridas) {
        if (Test-Path "resultados\experto_$($c[0]).json") { continue }   # reanudable
        & $py -u entrenar_lora.py --nombre $c[0] @($c[1]) 2>&1 | Tee-Object -FilePath "resultados\experto_$($c[0]).log"
    }
} finally { [Win32.Energia]::SetThreadExecutionState(0x80000000) | Out-Null }
