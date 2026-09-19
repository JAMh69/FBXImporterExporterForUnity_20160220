<#
    AUTO3D - extractor de metadatos de vuelo DJI
    -------------------------------------------
    Recorre una carpeta y sus subcarpetas, lee el bloque XMP de cada foto y
    escribe un CSV con la geometria de todos los vuelos.

    No instala nada y no toca las fotos. Solo lee los primeros 128 KB de cada
    archivo, que es donde DJI escribe el XMP, asi que va rapido incluso con
    miles de imagenes de 20 MB.

    Uso:
        1. Cambia $raiz si tu carpeta es otra.
        2. Boton derecho sobre el archivo -> "Ejecutar con PowerShell".
           Si Windows lo bloquea, abre PowerShell y ejecuta antes:
               Set-ExecutionPolicy -Scope Process Bypass
        3. Mandame el CSV que deja en el Escritorio. Pesa unos pocos KB.
#>

param([string]$Raiz, [string]$Salida)

$raiz = if ($Raiz) { $Raiz } else { "E:\005 Territorio Mudejar" }

# Los resultados se dejan junto al propio script, es decir dentro de la carpeta
# del proyecto en E:, no en el Escritorio. Si el script se ejecuta desde un
# sitio donde no se puede escribir, se cae a la carpeta temporal del usuario.
$carpetaDatos = if ($Salida) { Split-Path -Parent $Salida } else { Join-Path $PSScriptRoot 'datos' }
try {
    if (-not (Test-Path -LiteralPath $carpetaDatos)) {
        New-Item -ItemType Directory -Path $carpetaDatos -Force | Out-Null
    }
} catch {
    $carpetaDatos = $env:TEMP
    Write-Host "No se puede escribir junto al script; se usara $carpetaDatos" -ForegroundColor Yellow
}
# El nombre lleva la carpeta de origen para distinguir campañas de un vistazo:
# auto3d_metadatos_005 Territorio Mudejar_20260919_1127.csv
$origen = Split-Path -Leaf $raiz.TrimEnd('\')
if (-not $origen -or $origen -match '^[A-Za-z]:$') { $origen = $raiz -replace '[:\\/]', '' }
# los caracteres que Windows no admite en un nombre de archivo se sustituyen
foreach ($c in [IO.Path]::GetInvalidFileNameChars()) { $origen = $origen.Replace($c, [char]'-') }
$origen = $origen.Trim()

$sello  = Get-Date -Format 'yyyyMMdd_HHmm'
$salida = if ($Salida) { $Salida } else { Join-Path $carpetaDatos "auto3d_metadatos_${origen}_$sello.csv" }

# si la ruta por defecto no existe, pedirla en vez de fallar
while (-not (Test-Path -LiteralPath $raiz)) {
    Write-Host "No existe la carpeta: $raiz" -ForegroundColor Yellow
    Write-Host "Arrastra aqui la carpeta con los vuelos y pulsa Intro (o escribe su ruta):"
    $raiz = (Read-Host).Trim().Trim('"')
    if (-not $raiz) { Write-Host "Cancelado." -ForegroundColor Red; exit 1 }
}

$campos = @(
    'DroneModel','ImageSource','GpsStatus','AltitudeType',
    'GpsLatitude','GpsLongitude','RelativeAltitude','AbsoluteAltitude',
    'GimbalPitchDegree','GimbalYawDegree','GimbalRollDegree',
    'FlightPitchDegree','FlightYawDegree','FlightRollDegree',
    'RtkFlag','RtkStdLon','RtkStdLat','RtkStdHgt',
    'SurveyingMode','CameraSerialNumber','DroneSerialNumber'
)

Write-Host "Buscando fotos en $raiz ..." -ForegroundColor Cyan
# -Include con -Recurse cuela archivos que no son fotos, asi que se filtra por
# extension de forma explicita
$fotos = Get-ChildItem -LiteralPath $raiz -Recurse -File -ErrorAction SilentlyContinue |
         Where-Object { $_.Extension -match '^\.(jpg|jpeg)$' }
Write-Host ("Encontradas {0} fotos." -f $fotos.Count) -ForegroundColor Cyan

$filas = New-Object System.Collections.Generic.List[object]
$leidas = 0
$sinXmp = 0

foreach ($foto in $fotos) {
    $leidas++
    if ($leidas % 200 -eq 0) { Write-Host ("  {0} / {1}" -f $leidas, $fotos.Count) }

    # leer solo la cabecera del archivo
    try {
        $flujo = [System.IO.File]::OpenRead($foto.FullName)
        $buffer = New-Object byte[] 131072
        $n = $flujo.Read($buffer, 0, $buffer.Length)
        $flujo.Close()
    } catch { continue }

    $texto = [Text.Encoding]::ASCII.GetString($buffer, 0, $n)
    $ini = $texto.IndexOf('<x:xmpmeta')
    $fin = $texto.IndexOf('</x:xmpmeta>')
    if ($ini -lt 0 -or $fin -lt 0) { $sinXmp++; continue }
    $xmp = $texto.Substring($ini, $fin - $ini + 12)

    $fila = [ordered]@{
        archivo  = $foto.Name
        carpeta  = $foto.Directory.FullName.Replace($raiz, '').TrimStart('\')
        fecha    = $foto.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
        mb       = [math]::Round($foto.Length / 1MB, 1)
    }
    foreach ($campo in $campos) {
        $valor = ''
        $m = [regex]::Match($xmp, ('drone-dji:{0}\s*=\s*"([^"]*)"' -f $campo))
        if (-not $m.Success) {
            $m = [regex]::Match($xmp, ('<drone-dji:{0}>([^<]*)</' -f $campo))
        }
        if ($m.Success) { $valor = $m.Groups[1].Value.Trim() }
        $fila[$campo] = $valor
    }
    $filas.Add([pscustomobject]$fila)
}

$filas | Export-Csv -LiteralPath $salida -NoTypeInformation -Encoding UTF8
Write-Host ""
Write-Host ("Listo: {0} fotos con XMP, {1} sin XMP." -f $filas.Count, $sinXmp) -ForegroundColor Green
Write-Host ("Archivo: {0}" -f $salida) -ForegroundColor Green
Write-Host ("Tamano:  {0} KB" -f [math]::Round((Get-Item $salida).Length / 1KB, 1)) -ForegroundColor Green
Read-Host "Pulsa Intro para salir"
