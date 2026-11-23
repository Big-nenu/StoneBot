param(
    [string]$Directorio = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
)

$ErrorActionPreference = 'Stop'
$python = & python -B -c "import sys; print(sys.executable)"
if ($LASTEXITCODE -ne 0 -or -not $python) {
    throw 'No se pudo localizar el entorno Python de StoneBot.'
}

$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
$app = Join-Path $PSScriptRoot 'app.py'
$icono = Join-Path $PSScriptRoot 'assets\stonebot-icon.ico'
foreach ($archivo in @($pythonw, $app, $icono)) {
    if (-not (Test-Path -LiteralPath $archivo -PathType Leaf)) {
        throw "Falta un archivo necesario: $archivo"
    }
}

$destino = Join-Path (Resolve-Path -LiteralPath $Directorio).Path 'StoneBot.lnk'
$argumentos = '-B "' + $app + '"'
$shell = New-Object -ComObject WScript.Shell
$acceso = $shell.CreateShortcut($destino)
if ((Test-Path -LiteralPath $destino) -and $acceso.Arguments -ne $argumentos) {
    throw "Ya existe un acceso distinto en $destino."
}

$acceso.TargetPath = $pythonw
$acceso.Arguments = $argumentos
$acceso.WorkingDirectory = $PSScriptRoot
$acceso.IconLocation = "$icono,0"
$acceso.Description = 'Abrir StoneBot'
$acceso.Save()
Write-Output $destino
