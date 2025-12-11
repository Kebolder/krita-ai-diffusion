import shutil

from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import NamedTuple
from PyQt5.QtCore import QObject, pyqtSignal

from . import __version__, eventloop
from .network import RequestManager
from .properties import ObservableProperties, Property
from .platform_tools import ZipFile
from .util import client_logger as log


class UpdateState(Enum):
    unknown = 1
    checking = 2
    available = 3
    latest = 4
    downloading = 5
    installing = 6
    restart_required = 7
    failed_check = 8
    failed_update = 9


class UpdatePackage(NamedTuple):
    version: str
    url: str


class AutoUpdate(QObject, ObservableProperties):
    # This fork checks for updates only from the GitHub
    # releases of this repository.
    github_repo = "Kebolder/krita-ai-diffusion"

    state = Property(UpdateState.unknown)
    latest_version = Property("")
    error = Property("")

    state_changed = pyqtSignal(UpdateState)
    latest_version_changed = pyqtSignal(str)
    error_changed = pyqtSignal(str)

    def __init__(
        self,
        plugin_dir: Path | None = None,
        current_version: str | None = None,
        api_url: str | None = None,  # kept for backwards-compatible signature, ignored
    ):
        super().__init__()
        self.plugin_dir = plugin_dir or Path(__file__).parent.parent
        self.current_version = current_version or __version__
        self._package: UpdatePackage | None = None
        self._temp_dir: TemporaryDirectory | None = None
        self._request_manager: RequestManager | None = None

    def check(self):
        return eventloop.run(
            self._handle_errors(
                self._check, UpdateState.failed_check, "Failed to check for new plugin version"
            )
        )

    async def _check(self):
        if self.state is UpdateState.restart_required:
            return

        self.state = UpdateState.checking
        await self._check_github()

    async def _check_github(self):
        # Default and only update path: latest GitHub Release of this fork.
        api_url = f"https://api.github.com/repos/{self.github_repo}/releases/latest"
        log.info(f"Checking for latest plugin version on GitHub: {api_url}")
        result = await self._net.get(api_url, timeout=10)

        tag = result.get("tag_name") or result.get("name")
        if not tag:
            log.error(f"Invalid GitHub release information: {result}")
            self.state = UpdateState.failed_check
            self.error = "Failed to retrieve plugin update information from GitHub"
            return

        latest = str(tag).lstrip("v")
        self.latest_version = latest

        if latest == self.current_version:
            log.info("Plugin is up to date (GitHub)!")
            self.state = UpdateState.latest
            return

        assets = result.get("assets") or []
        zip_asset = next((a for a in assets if str(a.get("name", "")).endswith(".zip")), None)
        if not zip_asset:
            log.error(f"No ZIP asset found in latest GitHub release: {result}")
            self.state = UpdateState.failed_check
            self.error = "Latest GitHub release does not contain a ZIP package"
            return

        url = zip_asset.get("browser_download_url")
        if not url:
            log.error(f"Invalid ZIP asset in latest GitHub release: {zip_asset}")
            self.state = UpdateState.failed_check
            self.error = "GitHub release ZIP asset is missing download URL"
            return

        log.info(f"New plugin version available on GitHub: {latest} ({url})")
        self._package = UpdatePackage(version=latest, url=url)
        self.state = UpdateState.available

    def run(self):
        return eventloop.run(
            self._handle_errors(self._run, UpdateState.failed_update, "Failed to update plugin")
        )

    async def _run(self):
        assert self.latest_version and self._package

        self._temp_dir = TemporaryDirectory()
        archive_path = Path(self._temp_dir.name) / f"krita_ai_diffusion-{self.latest_version}.zip"
        log.info(f"Downloading plugin update {self._package.url}")
        self.state = UpdateState.downloading
        archive_data = await self._net.download(self._package.url)

        archive_path.write_bytes(archive_data)
        source_dir = Path(self._temp_dir.name) / f"krita_ai_diffusion-{self.latest_version}"
        log.info(f"Extracting plugin archive into {source_dir}")
        self.state = UpdateState.installing
        with ZipFile(archive_path) as zip_file:
            zip_file.extractall(source_dir)

        log.info(f"Installing new plugin version to {self.plugin_dir}")
        shutil.copytree(source_dir, self.plugin_dir, dirs_exist_ok=True)
        self.current_version = self.latest_version
        self.state = UpdateState.restart_required

    @property
    def is_available(self):
        return self.latest_version is not None and self.latest_version != self.current_version

    @property
    def _net(self):
        if self._request_manager is None:
            self._request_manager = RequestManager()
        return self._request_manager

    async def _handle_errors(self, func, error_state: UpdateState, message: str):
        try:
            return await func()
        except Exception as e:
            log.exception(e)
            self.error = f"{message}: {e}"
            self.state = error_state
            return None
