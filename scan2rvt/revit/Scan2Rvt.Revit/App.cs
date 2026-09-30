using System;
using System.IO;
using System.Text.Json;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;

namespace Scan2Rvt.Revit;

/// <summary>
/// Sólo actúa si Revit se abrió desde Scan2RVT (variable SCAN2RVT_JOB).
/// Con Revit abierto a mano no hace nada.
/// </summary>
public sealed class App : IExternalApplication
{
    private string? _encargo;
    private Registro? _log;

    public Result OnStartup(UIControlledApplication application)
    {
        _encargo = Environment.GetEnvironmentVariable("SCAN2RVT_JOB");
        if (string.IsNullOrWhiteSpace(_encargo) || !File.Exists(_encargo))
            return Result.Succeeded;

        application.Idling += AlEstarLibre;
        application.DialogBoxShowing += AlMostrarDialogo;
        return Result.Succeeded;
    }

    public Result OnShutdown(UIControlledApplication application) => Result.Succeeded;

    private void AlMostrarDialogo(object? sender, DialogBoxShowingEventArgs e)
    {
        // Revit trabaja desatendido: se aceptan los avisos para que no se quede esperando.
        _log?.Escribir($"Diálogo '{e.DialogId}' aceptado automáticamente.");
        e.OverrideResult(1);
    }

    private void AlEstarLibre(object? sender, IdlingEventArgs e)
    {
        if (sender is not UIApplication uiapp) return;
        uiapp.Idling -= AlEstarLibre;

        Encargo encargo;
        try
        {
            encargo = JsonSerializer.Deserialize<Encargo>(File.ReadAllText(_encargo!))
                      ?? throw new InvalidDataException("Encargo vacío");
        }
        catch (Exception ex)
        {
            File.WriteAllText(Path.ChangeExtension(_encargo!, ".error.txt"), ex.ToString());
            return;
        }

        _log = new Registro(encargo.Registro);
        var estado = new { estado = "ok", mensaje = "" };
        try
        {
            new Constructor(uiapp.Application, _log).Ejecutar(encargo);
        }
        catch (Exception ex)
        {
            _log.Escribir(ex.ToString());
            estado = new { estado = "error", mensaje = ex.Message };
        }
        File.WriteAllText(encargo.Estado, JsonSerializer.Serialize(estado));
        _log.Escribir("Fin. Cerrando Revit.");

        try
        {
            uiapp.PostCommand(RevitCommandId.LookupPostableCommandId(PostableCommand.ExitRevit));
        }
        catch (Exception ex)
        {
            // Si no se puede, Scan2RVT cierra el proceso.
            _log.Escribir("No se pudo cerrar Revit: " + ex.Message);
        }
    }
}

internal sealed class Registro
{
    private readonly string _ruta;

    public Registro(string ruta)
    {
        _ruta = ruta;
        if (!string.IsNullOrEmpty(_ruta)) File.WriteAllText(_ruta, "");
    }

    public void Escribir(string texto)
    {
        if (string.IsNullOrEmpty(_ruta)) return;
        File.AppendAllText(_ruta, $"{DateTime.Now:HH:mm:ss} {texto}{Environment.NewLine}");
    }
}
