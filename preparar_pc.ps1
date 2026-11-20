# Prepara y lanza el experimento en el PC con Windows + NVIDIA (RTX 5060 Ti).
#
# Uso (PowerShell, dentro de la carpeta TEST-IA):
#   powershell -ExecutionPolicy Bypass -File .\preparar_pc.ps1              # solo instala y verifica
#   powershell -ExecutionPolicy Bypass -File .\preparar_pc.ps1 -Entrenar    # además lanza la comparación larga
#   powershell -ExecutionPolicy Bypass -File .\preparar_pc.ps1 -Entrenar -Pasos 20000 -Semillas "0 1 2 3 4"

param(
    [switch]$Entrenar,
    [int]$Pasos = 10000,
    [string]$Semillas = "0 1 2",
    [string]$Variantes = "normal bitnet chico bucle",
    [string]$Sufijo = "pc"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Paso($texto) { Write-Host "`n==> $texto" -ForegroundColor Cyan }

# 1. Python: PyTorch para CUDA soporta 3.10 a 3.13
Paso "Buscando Python 3.10-3.13"
$python = $null
foreach ($v in "3.12", "3.13", "3.11", "3.10") {
    try { & py "-$v" --version *> $null; if ($LASTEXITCODE -eq 0) { $python = @("py", "-$v"); break } } catch {}
}
if (-not $python) {
    Write-Host "No encontré Python 3.10-3.13. Instala Python 3.12 desde https://www.python.org/downloads/ (marca 'Add to PATH') y vuelve a ejecutar." -ForegroundColor Red
    exit 1
}
& $python[0] $python[1] --version

# 2. Entorno virtual
$venvPy = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Paso "Creando entorno virtual .venv"
    & $python[0] $python[1] -m venv .venv
}

# 3. PyTorch con CUDA 12.8 (necesario para las RTX serie 50)
$ErrorActionPreference = "Continue"   # los avisos de Python por stderr no deben cortar el script
$tieneCuda = & $venvPy -c "import torch,sys; sys.stdout.write(str(torch.cuda.is_available()))" 2>$null
if ($tieneCuda -ne "True") {
    Paso "Instalando PyTorch con CUDA 12.8 (descarga de ~3 GB, puede tardar)"
    & $venvPy -m pip install --upgrade pip
    & $venvPy -m pip install torch --index-url https://download.pytorch.org/whl/cu128
    & $venvPy -m pip install numpy
    if ($LASTEXITCODE -ne 0) { Write-Host "Falló la instalación de PyTorch." -ForegroundColor Red; exit 1 }
}

# 4. Verificar la tarjeta
Paso "Verificando la GPU"
& $venvPy -c @"
import torch
assert torch.cuda.is_available(), 'PyTorch no ve la GPU: revisa el driver de NVIDIA (versión 570 o superior).'
p = torch.cuda.get_device_properties(0)
print(f'GPU: {p.name} | VRAM: {p.total_memory / 1e9:.1f} GB | PyTorch {torch.__version__} | CUDA {torch.version.cuda}')
x = torch.randn(2048, 2048, device='cuda'); torch.cuda.synchronize()
print('Prueba de cálculo en GPU: OK', float((x @ x).abs().mean()) > 0)
"@
if ($LASTEXITCODE -ne 0) { exit 1 }

# 5. Datos (si no existen)
if (-not (Test-Path ".\datos\evaluacion.jsonl")) {
    Paso "Generando datos"
    & $venvPy datos.py
}

if (-not $Entrenar) {
    Write-Host "`nListo. Para entrenar: powershell -ExecutionPolicy Bypass -File .\preparar_pc.ps1 -Entrenar" -ForegroundColor Green
    exit 0
}

# 6. Evitar que Windows se suspenda SOLO mientras corre (no cambia la configuración del sistema)
Add-Type -Namespace Win32 -Name Energia -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
[Win32.Energia]::SetThreadExecutionState(0x80000001) | Out-Null   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED

try {
    New-Item -ItemType Directory -Force -Path resultados | Out-Null
    $log = "resultados\comparar_$Sufijo.log"
    Paso "Entrenando ($Variantes | semillas $Semillas | $Pasos pasos). Registro: $log"
    $argsCmp = @("-u", "comparar.py", "--pasos", "$Pasos", "--sufijo", $Sufijo, "--semillas") + $Semillas.Split(" ") + @("--variantes") + $Variantes.Split(" ")
    & $venvPy @argsCmp 2>&1 | Tee-Object -FilePath $log
    Write-Host "`nResultado en resultados\comparacion_$Sufijo.md" -ForegroundColor Green
}
finally {
    [Win32.Energia]::SetThreadExecutionState(0x80000000) | Out-Null  # vuelve a permitir suspensión
}
