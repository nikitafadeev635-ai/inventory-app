"""
Фоновый worker для проверки пароля сотрудника.
Предотвращает зависание UI при медленном ответе сервера.
"""
from PyQt6.QtCore import QThread, pyqtSignal


class VerifyPasswordWorker(QThread):
    """
    QThread для асинхронной проверки пароля.
    
    Signals:
        finished(dict): Результат проверки {"verified": bool, "error": str}
    """
    finished = pyqtSignal(dict)
    
    def __init__(self, client, faname: str, password: str):
        super().__init__()
        self.client = client
        self.faname = faname
        self.password = password
    
    def run(self):
        """Выполняется в отдельном потоке."""
        try:
            result = self.client.verify_password(self.faname, self.password)
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit({
                "verified": False,
                "error": f"Ошибка подключения: {e}"
            })