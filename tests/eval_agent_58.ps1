[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('referencia', 'candidato')][string]$Serie,
    [Parameter(Mandatory)]
    [ValidateSet('diagnostico', 'reserva', 'complementario')][string]$Bloque,
    [Parameter(Mandatory)][string]$Salida,
    [switch]$MostrarComando
)

$ErrorActionPreference = 'Stop'
$modelos = @('nemotron-3.5-bolt:e4b', 'qwen3.5:4b')
$casos = switch ($Bloque) {
    'diagnostico' { 1..8 | ForEach-Object { 'D{0:00}' -f $_ } }
    'reserva' { 5..8 | ForEach-Object { 'V{0:00}' -f $_ } }
    'complementario' { 1..4 | ForEach-Object { 'V{0:00}' -f $_ } }
}
$repositorio = (Get-Item -LiteralPath $PSScriptRoot).Parent.FullName
$carpeta = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Salida)
$prefijo = "$Serie-$Bloque"
$argumentos = @('-B', 'tests/eval_agent_baseline.py', '--mcp-discovery', '1', '--repeats', '3', '--jobs', '1', '--timeout', '90')
foreach ($modelo in $modelos) { $argumentos += @('--model', $modelo) }
foreach ($caso in $casos) { $argumentos += @('--case', $caso) }
if ($MostrarComando) {
    [pscustomobject]@{ Repositorio = $repositorio; Comando = "python $($argumentos -join ' ')";
                      Salida = $carpeta; Serie = $Serie; Bloque = $Bloque; Intentos = $casos.Count * $modelos.Count * 3 }
    return
}

$hostAnterior = $env:OLLAMA_HOST
Push-Location -LiteralPath $repositorio
try {
    $env:OLLAMA_HOST = 'http://localhost:11434'
    $revision = git rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo identificar la revisión.' }
    $cambios = git status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0 -or $cambios) { throw 'Confirma los cambios rastreados antes de medir esta revisión.' }
    $pythonVersion = python --version
    if ($LASTEXITCODE -ne 0) { throw 'Python no está disponible.' }
    $ollamaVersion = ollama --version
    if ($LASTEXITCODE -ne 0) { throw 'Ollama no está disponible.' }
    $inventario = ollama list
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo consultar Ollama local.' }
    $ids = [ordered]@{}
    foreach ($modelo in $modelos) {
        $patron = '^' + [regex]::Escape($modelo) + '\s+(\S+)'
        $fila = $inventario | Select-String -Pattern $patron | Select-Object -First 1
        if (-not $fila) { throw "Falta el modelo local $modelo. Registra la ausencia antes de continuar." }
        $ids[$modelo] = $fila.Matches[0].Groups[1].Value
    }
    $presupuesto = [ordered]@{}
    Get-ChildItem Env:STONEBOT_TURN_* | Sort-Object Name | Where-Object {
        $_.Name -match '^STONEBOT_TURN_(CHAT|TASK)_(REQUESTS|SECONDS|PROPOSALS|DISPATCHES|BATCH|PER_TOOL)$'
    } | ForEach-Object {
        $presupuesto[$_.Name] = if ($_.Value -cmatch '^[0-9]{1,4}$') { $_.Value } else { 'valor invalido' }
    }
    $manifiesto = [ordered]@{ revision = $revision; serie = $Serie; bloque = $Bloque; argumentos = $argumentos;
                            python = $pythonVersion; ollama = $ollamaVersion; modelos = $ids; presupuesto = $presupuesto }
    $json = $manifiesto | ConvertTo-Json -Depth 5
    New-Item -Type Directory -Path $carpeta -Force | Out-Null
    $registro = Join-Path $carpeta "$prefijo.json"
    $fragmentos = @(Get-ChildItem -LiteralPath $carpeta -File -Filter "$prefijo-*.jsonl" | Sort-Object Name)
    if (Test-Path -LiteralPath $registro) {
        if ((Get-Content -LiteralPath $registro -Raw).TrimEnd() -cne $json.TrimEnd()) {
            throw 'Cambió la revisión o la configuración. Usa otro directorio para conservar una serie comparable.'
        }
    } elseif ($fragmentos.Count) {
        throw 'Hay fragmentos sin manifiesto. Conserva esos registros y usa otro directorio.'
    } else {
        $json | Set-Content -LiteralPath $registro -Encoding utf8
    }
    foreach ($fragmento in $fragmentos) { $argumentos += @('--resume-from', $fragmento.FullName) }
    $id = [guid]::NewGuid().ToString('N').Substring(0, 8)
    $archivo = Join-Path $carpeta "$prefijo-$(Get-Date -Format 'yyyyMMdd-HHmmss')-$id.jsonl"
    Write-Host "Registro de resultados en $archivo"
    python @argumentos | ForEach-Object { $_ | Add-Content -LiteralPath $archivo -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) { throw 'El evaluador se interrumpió. Los registros emitidos siguen en los fragmentos.' }
} finally {
    $env:OLLAMA_HOST = $hostAnterior
    Pop-Location
}
