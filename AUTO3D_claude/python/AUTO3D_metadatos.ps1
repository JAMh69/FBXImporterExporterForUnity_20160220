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

$raiz   = "E:\005 Territorio Mudejar"
$salida = Join-Path ([Environment]::GetFolderPath('Desktop')) 'auto3d_metadatos.csv'

$campos = @(
    'DroneModel','ImageSource','GpsStatus','AltitudeType',
    'GpsLatitude','GpsLongitude','RelativeAltitude','AbsoluteAltitude',
    'GimbalPitchDegree','GimbalYawDegree','GimbalRollDegree',
    'FlightPitchDegree','FlightYawDegree','FlightRollDegree',
    'RtkFlag','RtkStdLon','RtkStdLat','RtkStdHgt',
    'SurveyingMode','CameraSerialNumber','DroneSerialNumber'
)

if (-not (Test-Path -LiteralPath $raiz)) {
    Write-Host "No existe la carpeta: $raiz" -ForegroundColor Red
    Read-Host "Pulsa Intro para salir"; exit 1
}

Write-Host "Buscando fotos en $raiz ..." -ForegroundColor Cyan
$fotos = Get-ChildItem -LiteralPath $raiz -Recurse -File -Include *.jpg,*.jpeg,*.JPG,*.JPEG -ErrorAction SilentlyContinue
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
