"""Zonas de arrastrar y soltar."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


def rutas_de_evento(event) -> list[Path]:
    md = event.mimeData()
    if not md.hasUrls():
        return []
    return [Path(u.toLocalFile()) for u in md.urls() if u.isLocalFile()]


class ZonaSoltar(QFrame):
    """Lista de archivos/carpetas que acepta arrastrar y soltar.

    ``extensiones``: extensiones admitidas (en minúsculas). Las carpetas se
    aceptan siempre si ``carpetas`` es True (se buscan nubes dentro al procesar).
    """

    cambiado = Signal()

    def __init__(self, titulo: str, subtitulo: str, extensiones: tuple[str, ...], carpetas: bool = True,
                 unico: bool = False, parent=None):
        super().__init__(parent)
        self.extensiones = extensiones
        self.carpetas = carpetas
        self.unico = unico
        self.setAcceptDrops(True)
        self.setObjectName("zona")
        self.setProperty("activa", False)

        t = QLabel(f"<b>{titulo}</b>")
        s = QLabel(subtitulo)
        s.setObjectName("sub")
        s.setWordWrap(True)
        self.lista = QListWidget()
        self.lista.setSelectionMode(QListWidget.ExtendedSelection)
        self.lista.setMinimumHeight(90)
        self.vacia = QLabel("⤓  Arrastra aquí")
        self.vacia.setAlignment(Qt.AlignCenter)
        self.vacia.setObjectName("vacia")

        anadir = QPushButton("Añadir…")
        anadir.clicked.connect(self._dialogo)
        quitar = QPushButton("Quitar")
        quitar.clicked.connect(self._quitar)
        botones = QHBoxLayout()
        botones.addWidget(anadir)
        botones.addWidget(quitar)
        botones.addStretch()

        lay = QVBoxLayout(self)
        lay.addWidget(t)
        lay.addWidget(s)
        lay.addWidget(self.vacia)
        lay.addWidget(self.lista)
        lay.addLayout(botones)
        self._refrescar()

    # --- datos ---------------------------------------------------------------
    def rutas(self) -> list[str]:
        return [self.lista.item(i).data(Qt.UserRole) for i in range(self.lista.count())]

    def admite(self, p: Path) -> bool:
        if p.is_dir():
            return self.carpetas
        return p.suffix.lower() in self.extensiones

    def anadir(self, rutas: list[Path]) -> int:
        n = 0
        actuales = set(self.rutas())
        for p in rutas:
            if not self.admite(p) or str(p) in actuales:
                continue
            if self.unico:
                self.lista.clear()
                actuales.clear()
            item = QListWidgetItem(("📁 " if p.is_dir() else "") + p.name)
            item.setToolTip(str(p))
            item.setData(Qt.UserRole, str(p))
            self.lista.addItem(item)
            actuales.add(str(p))
            n += 1
        self._refrescar()
        if n:
            self.cambiado.emit()
        return n

    def limpiar(self):
        self.lista.clear()
        self._refrescar()
        self.cambiado.emit()

    # --- interacción ---------------------------------------------------------
    def _refrescar(self):
        hay = self.lista.count() > 0
        self.lista.setVisible(hay)
        self.vacia.setVisible(not hay)

    def _quitar(self):
        for it in self.lista.selectedItems():
            self.lista.takeItem(self.lista.row(it))
        self._refrescar()
        self.cambiado.emit()

    def _dialogo(self):
        filtro = "Admitidos (" + " ".join(f"*{e}" for e in self.extensiones) + ")"
        archivos, _ = QFileDialog.getOpenFileNames(self, "Añadir", "", filtro)
        self.anadir([Path(a) for a in archivos])

    def _marcar(self, activa: bool):
        self.setProperty("activa", activa)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if any(self.admite(p) for p in rutas_de_evento(e)):
            e.acceptProposedAction()
            self._marcar(True)
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._marcar(False)

    def dropEvent(self, e):
        self._marcar(False)
        if self.anadir(rutas_de_evento(e)):
            e.acceptProposedAction()
