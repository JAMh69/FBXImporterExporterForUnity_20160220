// Espejo de src/scan2rvt/model.py (modelo.json). Unidades: metros, coordenadas locales.
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Scan2Rvt.Revit;

public sealed class Encargo
{
    [JsonPropertyName("modelo")] public string Modelo { get; set; } = "";
    [JsonPropertyName("salida")] public string Salida { get; set; } = "";
    [JsonPropertyName("plantilla")] public string Plantilla { get; set; } = "";
    [JsonPropertyName("estado")] public string Estado { get; set; } = "";
    [JsonPropertyName("registro")] public string Registro { get; set; } = "";
}

public sealed class Modelo
{
    [JsonPropertyName("version")] public int Version { get; set; }
    [JsonPropertyName("offset")] public List<double> Offset { get; set; } = new();
    [JsonPropertyName("epsg")] public string Epsg { get; set; } = "";
    [JsonPropertyName("niveles")] public List<Nivel> Niveles { get; set; } = new();
    [JsonPropertyName("forjados")] public List<Forjado> Forjados { get; set; } = new();
    [JsonPropertyName("terreno")] public Terreno? Terreno { get; set; }
}

public sealed class Nivel
{
    [JsonPropertyName("id")] public string Id { get; set; } = "";
    [JsonPropertyName("nombre")] public string Nombre { get; set; } = "";
    [JsonPropertyName("cota")] public double Cota { get; set; }
}

public sealed class Forjado
{
    [JsonPropertyName("id")] public string Id { get; set; } = "";
    [JsonPropertyName("nivel_id")] public string NivelId { get; set; } = "";
    [JsonPropertyName("cota_superior")] public double CotaSuperior { get; set; }
    [JsonPropertyName("espesor")] public double Espesor { get; set; }
    [JsonPropertyName("contorno")] public List<List<double>> Contorno { get; set; } = new();
    [JsonPropertyName("huecos")] public List<List<List<double>>> Huecos { get; set; } = new();
    [JsonPropertyName("espesor_medido")] public bool EspesorMedido { get; set; } = true;
}

public sealed class Terreno
{
    [JsonPropertyName("puntos")] public List<List<double>> Puntos { get; set; } = new();
}
