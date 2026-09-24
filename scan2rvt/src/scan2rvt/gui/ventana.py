"""Ventana principal de Scan2RVT."""

from __future__ import annotations

import json
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, config, paths, pipeline, revit_bridge
from ..io.reader import EXTENSIONES
from .zonas import ZonaSoltar, rutas_de_evento

ESTILO = """
QWidget { font-size: 10pt; }
QLabel#titulo { font-size: 16pt; font-weight: 600; }
QLabel#sub, QLabel#mut { color: palette(mid); }
QFrame#zona { border: 2px dashed palette(mid); border-radius: 10px; padding: 6px; }
QFrame#zona[activa="true"] { border: 2px solid palette(highlight); background: palette(alternate-base); }
QLabel#vacia { color: palette(mid); font-size: 12pt; padding: 18px; }
QPushButton#principal { font-weight: 600; padding: 8px 22px; }
"""

SALIDAS_UI = [
    ("rvt", "Revit (.rvt)"),
    ("ifc", "IFC 4"),
    ("obj", "OBJ"),
    ("glb", "glTF (.glb)"),
    ("stl", "STL"),
    ("las", "Nube limpia (.laz)"),
]


def _ui_file() -> Path:
    return paths.config_dir() / "ultima_sesion.json"


class Trabajador(QObject):
    progreso = Signal(str, float)
    terminado = Signal(object)
    fallo = Signal(str)

    def __init__(self, trabajo: pipeline.Trabajo, ajustes: config.Settings):
        super().__init__()
        self.trabajo = trabajo
        self.ajustes = ajustes
        self.cancelar = False

    def ejecutar(self):
        try:
            r = pipeline.ejecutar(self.trabajo, self.ajustes, progreso=self.progreso.emit,
                                  cancelado=lambda: self.cancelar)
            self.terminado.emit(r)
        except pipeline.Cancelado:
            self.fallo.emit("Proceso cancelado.")
        except Exception as e:  # noqa: BLE001 - se muestra al usuario y se guarda en logs
            detalle = traceback.format_exc()
            try:
                log = paths.logs_dir() / f"error_{datetime.now():%Y%m%d_%H%M%S}.txt"
                log.write_text(detalle, encoding="utf-8")
                self.fallo.emit(f"{e}\n\nDetalle guardado en {log}")
            except OSError:
                self.fallo.emit(f"{e}\n\n{detalle}")


class CampoRuta(QLineEdit):
    """Campo de texto que acepta soltar un archivo."""

    def __init__(self, extensiones: tuple[str, ...], parent=None):
        super().__init__(parent)
        self.extensiones = extensiones
        self.setAcceptDrops(True)
        self.setPlaceholderText("Arrastra aquí el archivo")

    def dragEnterEvent(self, e):
        if any(p.suffix.lower() in self.extensiones for p in rutas_de_evento(e)):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for p in rutas_de_evento(e):
            if p.suffix.lower() in self.extensiones:
                self.setText(str(p))
                e.acceptProposedAction()
                return


class DialogoAjustes(QDialog):
    def __init__(self, ajustes: config.Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajustes")
        self.ajustes = ajustes
        self.revit = CampoRuta((".exe",))
        self.revit.setText(ajustes.revit_exe)
        self.version = QLineEdit(ajustes.revit_version)
        self.plantilla = CampoRuta((".rte",))
        self.plantilla.setText(ajustes.plantilla_rte)
        self.epsg = QLineEdit(ajustes.epsg)
        self.epsg.setPlaceholderText("p. ej. 25830 (ETRS89 / UTM 30N)")
        self.voxel = QDoubleSpinBox(decimals=3, minimum=0.005, maximum=0.2, singleStep=0.005)
        self.voxel.setValue(ajustes.voxel_m)
        self.malla = QDoubleSpinBox(decimals=2, minimum=0.1, maximum=10, singleStep=0.25)
        self.malla.setValue(ajustes.terreno.malla_m)

        f = QFormLayout()
        f.addRow("Revit.exe", self.revit)
        f.addRow("Versión de Revit", self.version)
        f.addRow("Plantilla por defecto (.rte)", self.plantilla)
        f.addRow("EPSG por defecto", self.epsg)
        f.addRow("Submuestreo (m)", self.voxel)
        f.addRow("Paso de la malla del terreno (m)", self.malla)

        inst = QPushButton("Reinstalar complemento de Revit")
        inst.clicked.connect(self._instalar)
        desinst = QPushButton("Desinstalar complemento")
        desinst.clicked.connect(self._desinstalar)
        fila = QHBoxLayout()
        fila.addWidget(inst)
        fila.addWidget(desinst)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._aceptar)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addLayout(fila)
        lay.addWidget(bb)
        self.resize(640, 0)

    def _aceptar(self):
        a = self.ajustes
        a.revit_exe = self.revit.text().strip()
        a.revit_version = self.version.text().strip() or "2026"
        a.plantilla_rte = self.plantilla.text().strip()
        a.epsg = self.epsg.text().strip()
        a.voxel_m = self.voxel.value()
        a.terreno.malla_m = self.malla.value()
        config.save(a)
        self.accept()

    def _instalar(self):
        try:
            r = revit_bridge.instalar_complemento(self.version.text().strip() or "2026")
            QMessageBox.information(self, "Complemento", f"Instalado:\n{r}")
        except revit_bridge.RevitNoDisponible as e:
            QMessageBox.warning(self, "Complemento", str(e))

    def _desinstalar(self):
        ok = revit_bridge.desinstalar_complemento(self.version.text().strip() or "2026")
        QMessageBox.information(self, "Complemento", "Desinstalado." if ok else "No estaba instalado.")


class Ventana(QMainWindow):
    def __init__(self):
        super().__init__()
        paths.ensure_dirs()
        self.ajustes = config.load()
        self.resultado: pipeline.Resultado | None = None
        self._hilo: QThread | None = None
        self._trabajador: Trabajador | None = None

        self.setWindowTitle(f"Scan2RVT {__version__}")
        self.setAcceptDrops(True)
        self.setStyleSheet(ESTILO)

        titulo = QLabel("Scan2RVT")
        titulo.setObjectName("titulo")
        sub = QLabel("Nube de puntos → Revit, IFC y modelos 3D")
        sub.setObjectName("mut")

        self.nombre = QLineEdit()
        self.nombre.setPlaceholderText("Nombre de la obra (será la carpeta en proyectos\\)")
        self.carpeta_lbl = QLabel()
        self.carpeta_lbl.setObjectName("mut")
        self.nombre.textChanged.connect(self._actualizar_carpeta)

        nubes = tuple(EXTENSIONES) + (".rcp", ".rcs")
        self.z_esc = ZonaSoltar("Escáner", "BLK360: .e57, .las, .laz, .ply, .pts… o carpetas enteras", nubes)
        self.z_dron = ZonaSoltar("Dron", "Matrice 4E (DJI Terra): .las, .laz… o carpetas enteras", nubes)
        self.z_rte = ZonaSoltar("Plantilla de Revit", "Opcional: .rte con vuestros tipos de suelo", (".rte",),
                                carpetas=False, unico=True)
        if self.ajustes.plantilla_rte:
            self.z_rte.anadir([Path(self.ajustes.plantilla_rte)])
        zonas = QGridLayout()
        zonas.addWidget(self.z_esc, 0, 0)
        zonas.addWidget(self.z_dron, 0, 1)
        zonas.addWidget(self.z_rte, 0, 2)
        zonas.setColumnStretch(0, 3)
        zonas.setColumnStretch(1, 3)
        zonas.setColumnStretch(2, 2)

        caja = QGroupBox("Qué generar")
        cl = QHBoxLayout(caja)
        self.checks: dict[str, QCheckBox] = {}
        for clave, texto in SALIDAS_UI:
            c = QCheckBox(texto)
            c.setChecked(clave in ("rvt", "ifc", "glb"))
            self.checks[clave] = c
            cl.addWidget(c)
        cl.addStretch()

        opciones = QHBoxLayout()
        self.alineadas = QCheckBox("Escáner y dron ya están alineados (mismas coordenadas)")
        self.alineadas.setChecked(True)
        self.epsg = QLineEdit(self.ajustes.epsg)
        self.epsg.setPlaceholderText("EPSG (opcional)")
        self.epsg.setMaximumWidth(140)
        opciones.addWidget(self.alineadas)
        opciones.addStretch()
        opciones.addWidget(QLabel("Sistema de coordenadas EPSG:"))
        opciones.addWidget(self.epsg)

        self.b_procesar = QPushButton("Procesar")
        self.b_procesar.setObjectName("principal")
        self.b_procesar.clicked.connect(self.procesar)
        self.b_cancelar = QPushButton("Cancelar")
        self.b_cancelar.setEnabled(False)
        self.b_cancelar.clicked.connect(self._cancelar)
        self.b_demo = QPushButton("Probar con la demo")
        self.b_demo.clicked.connect(lambda: self.procesar(demo=True))
        self.b_ajustes = QPushButton("Ajustes…")
        self.b_ajustes.clicked.connect(self._ajustes)
        self.b_carpeta = QPushButton("Abrir carpeta de resultados")
        self.b_carpeta.setEnabled(False)
        self.b_carpeta.clicked.connect(self._abrir_carpeta)
        self.b_informe = QPushButton("Ver informe")
        self.b_informe.setEnabled(False)
        self.b_informe.clicked.connect(self._abrir_informe)
        acciones = QHBoxLayout()
        for b in (self.b_procesar, self.b_cancelar, self.b_demo):
            acciones.addWidget(b)
        acciones.addStretch()
        for b in (self.b_carpeta, self.b_informe, self.b_ajustes):
            acciones.addWidget(b)

        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        self.estado = QLabel("Listo.")
        self.registro = QPlainTextEdit()
        self.registro.setReadOnly(True)
        self.registro.setMaximumBlockCount(5000)

        cab = QHBoxLayout()
        tv = QVBoxLayout()
        tv.addWidget(titulo)
        tv.addWidget(sub)
        cab.addLayout(tv)
        cab.addStretch()

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addLayout(cab)
        lay.addWidget(self.nombre)
        lay.addWidget(self.carpeta_lbl)
        lay.addLayout(zonas, 3)
        lay.addWidget(caja)
        lay.addLayout(opciones)
        lay.addLayout(acciones)
        lay.addWidget(self.barra)
        lay.addWidget(self.estado)
        lay.addWidget(self.registro, 2)
        self.setCentralWidget(central)
        self.resize(1100, 760)
        self._cargar_sesion()
        self._actualizar_carpeta()

    # --- sesión --------------------------------------------------------------
    def _cargar_sesion(self):
        try:
            d = json.loads(_ui_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.nombre.setText(d.get("nombre", ""))
        self.z_esc.anadir([Path(p) for p in d.get("escaner", []) if Path(p).exists()])
        self.z_dron.anadir([Path(p) for p in d.get("dron", []) if Path(p).exists()])
        for k, v in d.get("salidas", {}).items():
            if k in self.checks:
                self.checks[k].setChecked(bool(v))
        self.alineadas.setChecked(d.get("alineadas", True))

    def _guardar_sesion(self):
        d = {
            "nombre": self.nombre.text(),
            "escaner": self.z_esc.rutas(),
            "dron": self.z_dron.rutas(),
            "salidas": {k: c.isChecked() for k, c in self.checks.items()},
            "alineadas": self.alineadas.isChecked(),
        }
        try:
            _ui_file().write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _actualizar_carpeta(self):
        nombre = self.nombre.text().strip() or "…"
        self.carpeta_lbl.setText(f"Se guardará en: {paths.projects_dir() / paths.safe_name(nombre)}")

    # --- arrastrar a la ventana ------------------------------------------------
    def dragEnterEvent(self, e):
        if rutas_de_evento(e):
            e.acceptProposedAction()

    def dropEvent(self, e):
        """Soltar fuera de las zonas: .rte a la plantilla; nubes, se pregunta si son de escáner o dron."""
        rutas = rutas_de_evento(e)
        rte = [p for p in rutas if p.suffix.lower() == ".rte"]
        resto = [p for p in rutas if p.suffix.lower() != ".rte"]
        if rte:
            self.z_rte.anadir(rte[:1])
        if resto:
            m = QMessageBox(self)
            m.setWindowTitle("¿De dónde son estas nubes?")
            m.setText(f"{len(resto)} elemento(s). ¿Son del escáner o del dron?")
            b_esc = m.addButton("Escáner", QMessageBox.AcceptRole)
            b_dron = m.addButton("Dron", QMessageBox.AcceptRole)
            m.addButton("Cancelar", QMessageBox.RejectRole)
            m.exec()
            if m.clickedButton() is b_esc:
                self.z_esc.anadir(resto)
            elif m.clickedButton() is b_dron:
                self.z_dron.anadir(resto)
        e.acceptProposedAction()

    # --- proceso ---------------------------------------------------------------
    def _log(self, texto: str):
        self.registro.appendPlainText(f"{datetime.now():%H:%M:%S}  {texto}")

    def _trabajo(self, demo: bool) -> pipeline.Trabajo | None:
        nombre = self.nombre.text().strip() or ("Demo" if demo else "")
        if not nombre:
            QMessageBox.warning(self, "Falta el nombre", "Escribe el nombre de la obra.")
            return None
        if not demo and not (self.z_esc.rutas() or self.z_dron.rutas()):
            QMessageBox.warning(self, "Sin nubes", "Arrastra al menos una nube del escáner o del dron.")
            return None
        salidas = [k for k, c in self.checks.items() if c.isChecked()]
        if not salidas:
            QMessageBox.warning(self, "Nada que generar", "Marca al menos un formato de salida.")
            return None
        rte = self.z_rte.rutas()
        return pipeline.Trabajo(
            nombre=nombre,
            escaner=self.z_esc.rutas(),
            dron=self.z_dron.rutas(),
            salidas=salidas,
            plantilla_rte=rte[0] if rte else "",
            epsg=self.epsg.text().strip(),
            alineadas=self.alineadas.isChecked(),
            demo=demo,
        )

    def procesar(self, demo: bool = False):
        if self._hilo is not None:
            return
        trabajo = self._trabajo(demo)
        if trabajo is None:
            return
        self._guardar_sesion()
        self.registro.clear()
        self._log(f"Obra «{trabajo.nombre}»" + (" (demo)" if demo else ""))
        self._ocupado(True)

        self._hilo = QThread()
        self._trabajador = Trabajador(trabajo, self.ajustes)
        self._trabajador.moveToThread(self._hilo)
        self._hilo.started.connect(self._trabajador.ejecutar)
        self._trabajador.progreso.connect(self._al_progreso)
        self._trabajador.terminado.connect(self._al_terminar)
        self._trabajador.fallo.connect(self._al_fallar)
        self._hilo.start()

    def _ocupado(self, si: bool):
        self.b_procesar.setEnabled(not si)
        self.b_demo.setEnabled(not si)
        self.b_cancelar.setEnabled(si)
        for z in (self.z_esc, self.z_dron, self.z_rte):
            z.setEnabled(not si)

    def _fin_hilo(self):
        if self._hilo:
            self._hilo.quit()
            self._hilo.wait()
        self._hilo = None
        self._trabajador = None
        self._ocupado(False)

    def _al_progreso(self, msg: str, pct: float):
        self.barra.setValue(int(pct * 1000))
        self.estado.setText(msg)
        self._log(msg)

    def _al_terminar(self, r: pipeline.Resultado):
        self.resultado = r
        self._fin_hilo()
        self._log("—— Avisos ——")
        for a in r.avisos:
            self._log("• " + a)
        self._log("—— Archivos ——")
        for a in r.archivos:
            self._log("• " + str(a))
        self.estado.setText(f"Terminado: {len(r.archivos)} archivos en {r.carpeta}")
        self.b_carpeta.setEnabled(True)
        self.b_informe.setEnabled(r.informe is not None)

    def _al_fallar(self, msg: str):
        self._fin_hilo()
        self.barra.setValue(0)
        self.estado.setText("Error.")
        self._log("ERROR: " + msg)
        QMessageBox.critical(self, "Error", msg)

    def _cancelar(self):
        if self._trabajador:
            self._trabajador.cancelar = True
            self.estado.setText("Cancelando…")

    def _abrir_carpeta(self):
        if self.resultado:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.resultado.carpeta / "resultados")))

    def _abrir_informe(self):
        if self.resultado and self.resultado.informe:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.resultado.informe)))

    def _ajustes(self):
        d = DialogoAjustes(self.ajustes, self)
        if d.exec():
            self.epsg.setText(self.ajustes.epsg or self.epsg.text())

    def closeEvent(self, e):
        if self._hilo is not None:
            if QMessageBox.question(self, "Salir", "Hay un proceso en marcha. ¿Cancelarlo y salir?") != QMessageBox.Yes:
                e.ignore()
                return
            self._cancelar()
            self._fin_hilo()
        self._guardar_sesion()
        e.accept()


def lanzar() -> int:
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Scan2RVT")
    v = Ventana()
    v.show()
    return app.exec()


__all__ = ["Ventana", "lanzar", "Qt"]
