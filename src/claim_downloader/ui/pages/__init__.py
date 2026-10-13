"""화면별 페이지. 업무 화면은 ui/tasks.py 의 'module:Class' 로 app.py 가 늦게 불러온다."""
from .claim import ClaimPage
from .download import DownloadPage
from .home import HomePage
from .minutes import MinutesPage
from .pending import CardPage
from .settings import SettingsPage
from .updates import UpdatesPage

__all__ = ["HomePage", "DownloadPage", "MinutesPage", "ClaimPage", "CardPage", "SettingsPage", "UpdatesPage"]
