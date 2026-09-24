using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Architecture;

namespace Scan2Rvt.Revit;

/// <summary>Crea el proyecto de Revit a partir de modelo.json y lo guarda.</summary>
internal sealed class Constructor
{
    private readonly Application _app;
    private readonly Registro _log;

    public Constructor(Application app, Registro log)
    {
        _app = app;
        _log = log;
    }

    private static double M(double metros) => UnitUtils.ConvertToInternalUnits(metros, UnitTypeId.Meters);

    public void Ejecutar(Encargo encargo)
    {
        var modelo = JsonSerializer.Deserialize<Modelo>(File.ReadAllText(encargo.Modelo))
                     ?? throw new InvalidDataException("modelo.json vacío");
        _log.Escribir($"Modelo: {modelo.Niveles.Count} niveles, {modelo.Forjados.Count} forjados, terreno: {(modelo.Terreno != null)}");

        var doc = NuevoDocumento(encargo.Plantilla);
        try
        {
            using (var t = new Transaction(doc, "Scan2RVT"))
            {
                t.Start();
                var opciones = t.GetFailureHandlingOptions();
                opciones.SetFailuresPreprocessor(new IgnorarAvisos());
                t.SetFailureHandlingOptions(opciones);

                Coordenadas(doc, modelo);
                var niveles = Niveles(doc, modelo);
                Forjados(doc, modelo, niveles);
                Terreno(doc, modelo, niveles);
                t.Commit();
            }

            var guardar = new SaveAsOptions { OverwriteExistingFile = true };
            doc.SaveAs(encargo.Salida, guardar);
            _log.Escribir($"Guardado: {encargo.Salida}");
        }
        finally
        {
            doc.Close(false);
        }
    }

    private Document NuevoDocumento(string plantilla)
    {
        if (!string.IsNullOrEmpty(plantilla) && File.Exists(plantilla))
        {
            _log.Escribir($"Plantilla: {plantilla}");
            return _app.NewProjectDocument(plantilla);
        }
        var defecto = _app.DefaultProjectTemplate;
        if (!string.IsNullOrEmpty(defecto) && File.Exists(defecto))
        {
            _log.Escribir($"Plantilla por defecto de Revit: {defecto}");
            return _app.NewProjectDocument(defecto);
        }
        _log.Escribir("Sin plantilla: proyecto métrico vacío.");
        return _app.NewProjectDocument(UnitSystem.Metric);
    }

    /// <summary>Coordenadas compartidas: el origen interno equivale a (offset) en coordenadas reales.</summary>
    private void Coordenadas(Document doc, Modelo modelo)
    {
        if (modelo.Offset.Count < 3) return;
        var pos = new ProjectPosition(M(modelo.Offset[0]), M(modelo.Offset[1]), M(modelo.Offset[2]), 0.0);
        doc.ActiveProjectLocation.SetProjectPosition(XYZ.Zero, pos);
        _log.Escribir($"Coordenadas compartidas: E {modelo.Offset[0]:F3}, N {modelo.Offset[1]:F3}, Z {modelo.Offset[2]:F3}");
    }

    private Dictionary<string, Level> Niveles(Document doc, Modelo modelo)
    {
        var existentes = new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>()
            .OrderBy(l => l.Elevation).ToList();
        // Nombres temporales para que no choquen al renombrar.
        for (int i = 0; i < existentes.Count; i++) existentes[i].Name = $"__scan2rvt_{i}";

        var tipoPlanta = new FilteredElementCollector(doc).OfClass(typeof(ViewFamilyType)).Cast<ViewFamilyType>()
            .FirstOrDefault(v => v.ViewFamily == ViewFamily.FloorPlan);

        var resultado = new Dictionary<string, Level>();
        for (int i = 0; i < modelo.Niveles.Count; i++)
        {
            var n = modelo.Niveles[i];
            Level nivel;
            if (i < existentes.Count)
            {
                nivel = existentes[i];
                nivel.Elevation = M(n.Cota);
            }
            else
            {
                nivel = Level.Create(doc, M(n.Cota));
                if (tipoPlanta != null) ViewPlan.Create(doc, tipoPlanta.Id, nivel.Id);
            }
            nivel.Name = n.Nombre;
            resultado[n.Id] = nivel;
        }

        // Niveles de la plantilla que sobran.
        for (int i = modelo.Niveles.Count; i < existentes.Count; i++)
        {
            try { doc.Delete(existentes[i].Id); }
            catch (Exception ex) { _log.Escribir($"No se pudo borrar un nivel de la plantilla: {ex.Message}"); }
        }
        _log.Escribir($"Niveles: {resultado.Count}");
        return resultado;
    }

    private void Forjados(Document doc, Modelo modelo, Dictionary<string, Level> niveles)
    {
        var tipos = new FilteredElementCollector(doc).OfClass(typeof(FloorType)).Cast<FloorType>()
            .Where(t => !t.IsFoundationSlab && t.GetCompoundStructure() != null).ToList();
        if (tipos.Count == 0) throw new InvalidOperationException("La plantilla no tiene tipos de suelo.");

        foreach (var f in modelo.Forjados)
        {
            if (!niveles.TryGetValue(f.NivelId, out var nivel)) continue;
            try
            {
                var tipo = TipoSuelo(doc, tipos, f.Espesor);
                var perfil = new List<CurveLoop> { Anillo(f.Contorno) };
                perfil.AddRange(f.Huecos.Select(Anillo));
                var suelo = Floor.Create(doc, perfil, tipo.Id, nivel.Id);
                var desfase = M(f.CotaSuperior) - nivel.Elevation;
                suelo.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)?.Set(desfase);
                suelo.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)?.Set(
                    f.EspesorMedido ? $"Scan2RVT {f.Id}: espesor medido" : $"Scan2RVT {f.Id}: espesor SUPUESTO, revisar");
            }
            catch (Exception ex)
            {
                _log.Escribir($"Forjado {f.Id} no creado: {ex.Message}");
            }
        }
    }

    /// <summary>Tipo de suelo con el espesor pedido (±1 mm); si no existe, se duplica el más parecido.</summary>
    private FloorType TipoSuelo(Document doc, List<FloorType> tipos, double espesorM)
    {
        var objetivo = M(espesorM);
        var tol = M(0.001);
        var mejor = tipos.OrderBy(t => Math.Abs(t.GetCompoundStructure().GetWidth() - objetivo)).First();
        if (Math.Abs(mejor.GetCompoundStructure().GetWidth() - objetivo) <= tol) return mejor;

        var nombre = $"Scan2RVT {Math.Round(espesorM * 1000):0} mm";
        var existente = tipos.FirstOrDefault(t => t.Name == nombre);
        if (existente != null) return existente;

        var nuevo = (FloorType)mejor.Duplicate(nombre);
        var cs = nuevo.GetCompoundStructure();
        var capas = cs.GetLayers();
        // Se ajusta la capa más gruesa (normalmente la estructural).
        int k = Enumerable.Range(0, capas.Count).OrderByDescending(i => capas[i].Width).First();
        var resto = cs.GetWidth() - capas[k].Width;
        var ancho = objetivo - resto;
        if (ancho <= tol)
        {
            // El espesor pedido es menor que las demás capas: se deja una sola capa.
            k = 0;
            var capa = new CompoundStructureLayer(objetivo, capas[k].Function, capas[k].MaterialId);
            cs.SetLayers(new List<CompoundStructureLayer> { capa });
            cs.StructuralMaterialIndex = 0;
        }
        else
        {
            cs.SetLayerWidth(k, ancho);
        }
        nuevo.SetCompoundStructure(cs);
        tipos.Add(nuevo);
        _log.Escribir($"Tipo de suelo creado: {nombre}");
        return nuevo;
    }

    private CurveLoop Anillo(List<List<double>> puntos)
    {
        var bucle = new CurveLoop();
        var pts = puntos.Select(p => new XYZ(M(p[0]), M(p[1]), 0)).ToList();
        var minimo = _app.ShortCurveTolerance;
        var limpios = new List<XYZ>();
        foreach (var p in pts)
            if (limpios.Count == 0 || limpios[^1].DistanceTo(p) > minimo) limpios.Add(p);
        if (limpios.Count > 2 && limpios[^1].DistanceTo(limpios[0]) <= minimo) limpios.RemoveAt(limpios.Count - 1);
        for (int i = 0; i < limpios.Count; i++)
            bucle.Append(Line.CreateBound(limpios[i], limpios[(i + 1) % limpios.Count]));
        return bucle;
    }

    private void Terreno(Document doc, Modelo modelo, Dictionary<string, Level> niveles)
    {
        if (modelo.Terreno == null || modelo.Terreno.Puntos.Count < 3) return;
        var tipo = new FilteredElementCollector(doc).OfClass(typeof(ToposolidType)).FirstElementId();
        if (tipo == ElementId.InvalidElementId)
        {
            _log.Escribir("La plantilla no tiene tipos de Toposolid: terreno no creado.");
            return;
        }
        var nivel = niveles.Values.OrderBy(l => l.Elevation).FirstOrDefault()
                    ?? new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>().OrderBy(l => l.Elevation).First();
        var puntos = modelo.Terreno.Puntos.Select(p => new XYZ(M(p[0]), M(p[1]), M(p[2]))).ToList();
        Toposolid.Create(doc, puntos, tipo, nivel.Id);
        _log.Escribir($"Terreno: {puntos.Count} puntos");
    }
}

/// <summary>Borra los avisos (no los errores) para que la transacción no pida confirmación.</summary>
internal sealed class IgnorarAvisos : IFailuresPreprocessor
{
    public FailureProcessingResult PreprocessFailures(FailuresAccessor fa)
    {
        foreach (var f in fa.GetFailureMessages())
            if (f.GetSeverity() == FailureSeverity.Warning) fa.DeleteWarning(f);
        return FailureProcessingResult.Continue;
    }
}
