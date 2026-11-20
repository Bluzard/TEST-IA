@echo off
rem Compila motor.cpp -> motor.dll con MSVC (Visual Studio 2019 Build Tools). AVX2 + OpenMP.
setlocal
set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" (
  echo No encontre vcvars64.bat; ajusta la ruta en compilar_motor.bat
  exit /b 1
)
call "%VCVARS%" >nul
cd /d "%~dp0"
cl /nologo /O2 /GL /arch:AVX2 /openmp /EHsc /LD motor.cpp /Fe:motor.dll
if errorlevel 1 exit /b 1
del motor.obj motor.lib motor.exp 2>nul
echo OK: motor.dll
