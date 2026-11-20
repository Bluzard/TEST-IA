# Lanza el preentrenamiento en español (BitNet) sin que Windows se suspenda.
# Reanudable: si se corta, vuelve a ejecutarlo y continúa desde el último punto de control.
#   powershell -ExecutionPolicy Bypass -File .\lanzar_preentreno.ps1 [-Minutos 180]
param([int]$Minutos = 180, [string]$Salida = "modelos\nucleo_es_bitnet.pt")

Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"
Add-Type -Namespace Win32 -Name Energia -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
[Win32.Energia]::SetThreadExecutionState(0x80000001) | Out-Null
try {
    & .\.venv\Scripts\python.exe -u preentrenar.py --bitnet --lote 64 --minutos $Minutos --guardar 1000 --salida $Salida 2>&1 |
        Tee-Object -FilePath resultados\preentreno_bitnet.log -Append
}
finally { [Win32.Energia]::SetThreadExecutionState(0x80000000) | Out-Null }
