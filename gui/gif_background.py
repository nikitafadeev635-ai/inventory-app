from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPainter, QMovie, QColor
import os


class GifBackgroundWidget(QWidget):
    """
    Базовый виджет, который рисует анимированную гифку на фоне.
    Все дочерние элементы (таблицы, кнопки) размещаются поверх неё.
    """

    def __init__(self, gif_path: str, overlay_alpha: int = 180, parent=None):
        super().__init__(parent)
        self._current_pixmap = None
        self._overlay_alpha = overlay_alpha
        self._movie = None

        if gif_path and os.path.isfile(gif_path):
            self._movie = QMovie(gif_path)
            if self._movie.isValid():
                # Ресайзим гифку под размер виджета
                self._movie.setScaledSize(QSize(self.width(), self.height()))
                # При каждом новом кадре — перерисовываем
                self._movie.frameChanged.connect(self._on_frame_changed)
                self._movie.start()
                print(f"[GifBackground] ✓ Анимация загружена: {gif_path}")
            else:
                print(f"[GifBackground] ✗ Файл не является валидной гифкой: {gif_path}")
                self._movie = None
        else:
            if gif_path:
                print(f"[GifBackground] ⚠ Файл не найден: {gif_path}. Будет обычный фон.")

    def _on_frame_changed(self, _frame_number: int):
        """Обновляем QPixmap и запрашиваем перерисовку."""
        if self._movie:
            self._current_pixmap = self._movie.currentPixmap()
            self.update()

    def resizeEvent(self, event):
        """При изменении размера окна — масштабируем гифку."""
        super().resizeEvent(event)
        if self._movie:
            self._movie.setScaledSize(QSize(self.width(), self.height()))

    def paintEvent(self, event):
        """Рисуем гифку + полупрозрачный затемняющий слой."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 1. Фон по умолчанию (если гифка не загрузилась)
        painter.fillRect(self.rect(), QColor("#0f172a"))

        # 2. Кадр гифки (если есть)
        if self._current_pixmap and not self._current_pixmap.isNull():
            painter.drawPixmap(self.rect(), self._current_pixmap)

        # 3. Затемняющий оверлей — чтобы контент был читаемым
        overlay = QColor(15, 23, 42, self._overlay_alpha)  # тёмно-синий полупрозрачный
        painter.fillRect(self.rect(), overlay)

        painter.end()