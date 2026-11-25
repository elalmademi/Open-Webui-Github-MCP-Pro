"""
Appium Manager - Gestión de sesiones Appium (WebDriver) para automatización móvil.
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.options.ios import XCUITestOptions
from selenium.webdriver.remote.webdriver import WebDriver

from config.settings import get_settings
from services.device_registry import Device, DevicePlatform

logger = logging.getLogger(__name__)


@dataclass
class AppiumSession:
    session_id: str
    device_id: str
    driver: Optional[WebDriver] = None
    capabilities: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    status: str = "active"  # active, detached, terminated


class AppiumManager:
    """
    Gestor de sesiones Appium con:
    - Pool de drivers reutilizables
    - Capabilities builder por plataforma
    - Session lifecycle (create, attach, detach, terminate)
    - Health checks y cleanup automático
    - Soporte cloud (BrowserStack, Sauce Labs) via capabilities
    """

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._sessions: Dict[str, AppiumSession] = {}
        self._appium_url = f"http://{self.settings.appium_host}:{self.settings.appium_port}"
        self._cleanup_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Verifica conectividad con Appium server."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._appium_url}/status")
                if resp.status_code == 200:
                    logger.info(f"Appium server conectado: {self._appium_url}")
                else:
                    logger.warning(f"Appium server respondió {resp.status_code}")
        except Exception as e:
            logger.warning(f"Appium server no accesible en {self._appium_url}: {e}")

        self._cleanup_task = asyncio.create_task(self._cleanup_stale_sessions())

    async def shutdown(self) -> None:
        """Termina todas las sesiones y detiene tareas."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Terminar todas las sesiones
        for session in list(self._sessions.values()):
            await self.terminate_session(session.session_id)

    # ─── Capabilities Builder ───

    def _build_android_caps(self, device: Device, app_path: str, **extra) -> UiAutomator2Options:
        """Construye capabilities para Android (UiAutomator2)."""
        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.device_name = device.properties.model
        options.udid = device.properties.udid
        options.platform_version = device.properties.os_version
        options.app = app_path
        options.automation_name = "UiAutomator2"
        options.no_reset = True
        options.full_reset = False
        options.auto_grant_permissions = True
        options.auto_accept_alerts = True
        options.new_command_timeout = 300

        # Extra capabilities
        for k, v in extra.items():
            if k.startswith("appium:"):
                setattr(options, k.replace("appium:", ""), v)

        return options

    def _build_ios_caps(self, device: Device, app_path: str, **extra) -> XCUITestOptions:
        """Construye capabilities para iOS (XCUITest)."""
        options = XCUITestOptions()
        options.platform_name = "iOS"
        options.device_name = device.properties.model
        options.udid = device.properties.udid
        options.platform_version = device.properties.os_version
        options.app = app_path
        options.automation_name = "XCUITest"
        options.no_reset = True
        options.full_reset = False
        options.auto_accept_alerts = True
        options.new_command_timeout = 300

        # Para iOS real device: requerir WebDriverAgent
        # options.webdriver_agent_url = "..."

        for k, v in extra.items():
            if k.startswith("appium:"):
                setattr(options, k.replace("appium:", ""), v)

        return options

    def _build_cloud_caps(self, device: Device, app_url: str, provider: str, **extra) -> Dict[str, Any]:
        """Construye capabilities para proveedores cloud."""
        caps = {
            "platformName": device.platform.value.capitalize(),
            "appium:deviceName": device.name,
            "appium:platformVersion": device.properties.os_version,
            "appium:app": app_url,
            "appium:automationName": "UiAutomator2" if device.platform == DevicePlatform.ANDROID else "XCUITest",
        }

        # Provider-specific
        if provider == "browserstack":
            caps["bstack:options"] = {
                "deviceName": device.name,
                "osVersion": device.properties.os_version,
                "projectName": "MCP Mobile Testing",
                "buildName": f"build-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                "sessionName": f"session-{uuid.uuid4().hex[:8]}",
            }
        elif provider == "saucelabs":
            caps["sauce:options"] = {
                "deviceName": device.name,
                "platformVersion": device.properties.os_version,
                "build": f"MCP-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                "name": f"session-{uuid.uuid4().hex[:8]}",
            }

        caps.update(extra)
        return caps

    # ─── Session Management ───

    async def create_session(
        self,
        device: Device,
        app_path: str,
        cloud_provider: Optional[str] = None,
        app_url: Optional[str] = None,
        **extra_caps,
    ) -> AppiumSession:
        """Crea nueva sesión Appium."""
        session_id = f"appium_{uuid.uuid4().hex[:12]}"

        # Determinar capabilities
        if cloud_provider and app_url:
            caps_dict = self._build_cloud_caps(device, app_url, cloud_provider, **extra_caps)
            # Para cloud, usar Remote WebDriver directo
            driver = webdriver.Remote(
                command_executor=self._appium_url,
                desired_capabilities=caps_dict,
            )
            caps = caps_dict
        else:
            # Local
            if device.platform == DevicePlatform.ANDROID:
                options = self._build_android_caps(device, app_path, **extra_caps)
            else:
                options = self._build_ios_caps(device, app_path, **extra_caps)

            driver = webdriver.Remote(
                command_executor=self._appium_url,
                options=options,
            )
            caps = options.to_capabilities()

        session = AppiumSession(
            session_id=session_id,
            device_id=device.id,
            driver=driver,
            capabilities=caps,
        )

        self._sessions[session_id] = session
        logger.info(f"Sesión Appium creada: {session_id} para dispositivo {device.id}")

        return session

    async def attach_session(self, session_id: str, device_id: str) -> Optional[AppiumSession]:
        """Adjunta a sesión existente (no implementado completamente en Appium Python)."""
        # Appium Python client no soporta attach nativo fácilmente
        # Requeriría session_id remoto y endpoint
        logger.warning("Attach session no implementado completamente")
        return None

    def get_session(self, session_id: str) -> Optional[AppiumSession]:
        return self._sessions.get(session_id)

    def get_driver(self, session_id: str) -> Optional[WebDriver]:
        session = self._sessions.get(session_id)
        return session.driver if session else None

    async def terminate_session(self, session_id: str) -> bool:
        """Termina sesión y cierra driver."""
        session = self._sessions.pop(session_id, None)
        if not session:
            return False

        if session.driver:
            try:
                session.driver.quit()
            except Exception as e:
                logger.warning(f"Error cerrando driver {session_id}: {e}")

        session.status = "terminated"
        logger.info(f"Sesión Appium terminada: {session_id}")
        return True

    async def detach_session(self, session_id: str) -> bool:
        """Desconecta sin terminar (mantiene sesión en Appium server)."""
        session = self._sessions.pop(session_id, None)
        if not session:
            return False

        session.status = "detached"
        session.driver = None  # No quit, solo desconectamos referencia local
        logger.info(f"Sesión Appium desprendida: {session_id}")
        return True

    # ─── Session Operations (delegados al driver) ───

    async def execute_script(self, session_id: str, script: str, *args) -> Any:
        """Ejecuta script en el driver."""
        driver = self.get_driver(session_id)
        if not driver:
            raise ValueError(f"Sesión no encontrada: {session_id}")
        return driver.execute_script(script, *args)

    async def get_screenshot(self, session_id: str) -> str:
        """Captura screenshot base64."""
        driver = self.get_driver(session_id)
        if not driver:
            raise ValueError(f"Sesión no encontrada: {session_id}")
        return driver.get_screenshot_as_base64()

    async def get_page_source(self, session_id: str) -> str:
        """Obtiene page source (XML)."""
        driver = self.get_driver(session_id)
        if not driver:
            raise ValueError(f"Sesión no encontrada: {session_id}")
        return driver.page_source

    async def get_logs(self, session_id: str, log_type: str = "logcat") -> List[Dict]:
        """Obtiene logs (logcat, syslog, crashlog)."""
        driver = self.get_driver(session_id)
        if not driver:
            raise ValueError(f"Sesión no encontrada: {session_id}")
        try:
            logs = driver.get_log(log_type)
            return [{"level": l["level"], "message": l["message"], "timestamp": l["timestamp"]} for l in logs]
        except Exception:
            return []

    # ─── Cleanup ───

    async def _cleanup_stale_sessions(self) -> None:
        """Limpia sesiones inactivas > 30 min."""
        while True:
            try:
                await asyncio.sleep(300)  # Cada 5 min
                now = datetime.now()
                stale = [
                    sid for sid, s in self._sessions.items()
                    if (now - s.last_activity).total_seconds() > 1800
                ]
                for sid in stale:
                    logger.info(f"Limpiando sesión inactiva: {sid}")
                    await self.terminate_session(sid)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error en cleanup de sesiones: {e}")