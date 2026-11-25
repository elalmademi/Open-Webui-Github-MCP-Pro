"""
Device Registry - Gestión de pool de dispositivos (local ADB + cloud providers).
Persistencia en Redis con TTL, reservas atómicas, health checks.
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set

import redis.asyncio as redis

from config.settings import get_settings

logger = logging.getLogger(__name__)


class DeviceStatus(str, Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    BUSY = "busy"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"


class DeviceProvider(str, Enum):
    LOCAL = "local"
    BROWSERSTACK = "browserstack"
    SAUCELABS = "saucelabs"
    LAMBDATEST = "lambdatest"
    FIREBASE = "firebase"
    DIGITALAI = "digitalai"


class DevicePlatform(str, Enum):
    ANDROID = "android"
    IOS = "ios"


@dataclass(frozen=True)
class DeviceProperties:
    """Propiedades inmutables del dispositivo."""
    model: str
    os_version: str
    is_real: bool
    is_emulator: bool = False
    udid: Optional[str] = None
    screen_resolution: Optional[str] = None
    abi: Optional[str] = None
    carrier: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class Device:
    """Dispositivo en el registry."""
    id: str
    provider: DeviceProvider
    platform: DevicePlatform
    name: str
    properties: DeviceProperties
    status: DeviceStatus = DeviceStatus.AVAILABLE
    reserved_by: Optional[str] = None  # session_id
    reserved_until: Optional[datetime] = None
    cost_per_minute: float = 0.0
    last_seen: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider.value,
            "platform": self.platform.value,
            "name": self.name,
            "properties": {
                "model": self.properties.model,
                "os_version": self.properties.os_version,
                "is_real": self.properties.is_real,
                "is_emulator": self.properties.is_emulator,
                "udid": self.properties.udid,
                "screen_resolution": self.properties.screen_resolution,
                "abi": self.properties.abi,
                "carrier": self.properties.carrier,
                "tags": self.properties.tags,
            },
            "status": self.status.value,
            "reserved_by": self.reserved_by,
            "reserved_until": self.reserved_until.isoformat() if self.reserved_until else None,
            "cost_per_minute": self.cost_per_minute,
            "last_seen": self.last_seen.isoformat(),
            "metadata": self.metadata,
        }


class DeviceRegistry:
    """
    Registry de dispositivos con:
    - Descubrimiento local (ADB, iOS Simulator)
    - Integración cloud (BrowserStack, Sauce Labs, etc.) vía API
    - Reservas atómicas con TTL en Redis
    - Health checks periódicos
    - Limpieza automática de reservas expiradas
    """

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._redis: Optional[redis.Redis] = None
        self._local_devices: Dict[str, Device] = {}
        self._cloud_devices: Dict[str, Device] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._discovery_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Inicializa Redis y descubre dispositivos locales."""
        self._redis = redis.Redis(
            host=self.settings.redis_host,
            port=self.settings.redis_port,
            db=self.settings.redis_db,
            password=self.settings.redis_password,
            decode_responses=True,
        )
        try:
            await self._redis.ping()
            logger.info("Redis conectado para Device Registry")
        except Exception as e:
            logger.warning(f"Redis no disponible para Device Registry: {e}")
            self._redis = None

        # Descubrir dispositivos locales
        await self._discover_local_devices()

        # Iniciar tareas de background
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_reservations())
        self._discovery_task = asyncio.create_task(self._periodic_discovery())

    async def shutdown(self) -> None:
        """Detiene tareas y libera recursos."""
        for task in [self._cleanup_task, self._discovery_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._redis:
            await self._redis.close()

    # ─── Local Discovery ───

    async def _discover_local_devices(self) -> None:
        """Descubre dispositivos Android (ADB) e iOS (simulator) locales."""
        # Android via ADB
        await self._discover_android_adb()

        # iOS Simulator (solo macOS)
        await self._discover_ios_simulator()

    async def _discover_android_adb(self) -> None:
        """Ejecuta `adb devices -l` y parsea output."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "adb", "devices", "-l",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(f"adb devices falló: {stderr.decode()}")
                return

            output = stdout.decode("utf-8", errors="replace")
            lines = output.strip().split("\n")[1:]  # Skip header

            for line in lines:
                line = line.strip()
                if not line or "device" not in line:
                    continue

                parts = line.split()
                device_id = parts[0]

                # Obtener propiedades
                props = await self._get_android_props(device_id)
                model = props.get("ro.product.model", device_id)
                os_version = props.get("ro.build.version.release", "unknown")
                is_emulator = "emulator" in device_id or props.get("ro.product.brand") == "google_sdk"

                properties = DeviceProperties(
                    model=model,
                    os_version=os_version,
                    is_real=not is_emulator,
                    is_emulator=is_emulator,
                    udid=device_id,
                    abi=props.get("ro.product.cpu.abi"),
                    tags=["local", "adb"] + (["emulator"] if is_emulator else ["real-device"]),
                )

                device = Device(
                    id=f"local:android:{device_id}",
                    provider=DeviceProvider.LOCAL,
                    platform=DevicePlatform.ANDROID,
                    name=model,
                    properties=properties,
                    status=DeviceStatus.AVAILABLE,
                    cost_per_minute=0.0,
                )

                self._local_devices[device.id] = device
                logger.info(f"Dispositivo Android local descubierto: {device.name} ({device_id})")

        except FileNotFoundError:
            logger.debug("ADB no instalado, saltando descubrimiento Android local")
        except Exception as e:
            logger.warning(f"Error descubriendo dispositivos Android: {e}")

    async def _get_android_props(self, device_id: str) -> Dict[str, str]:
        """Obtiene propiedades del dispositivo via `adb shell getprop`."""
        props = {}
        try:
            proc = await asyncio.create_subprocess_exec(
                "adb", "-s", device_id, "shell", "getprop",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                for line in stdout.decode("utf-8", errors="replace").split("\n"):
                    if ": " in line:
                        k, v = line.split(": ", 1)
                        props[k.strip("[]")] = v.strip("[]")
        except Exception:
            pass
        return props

    async def _discover_ios_simulator(self) -> None:
        """Descubre simuladores iOS via `xcrun simctl list devices json` (solo macOS)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "xcrun", "simctl", "list", "devices", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return

            import json
            data = json.loads(stdout.decode("utf-8"))
            devices = data.get("devices", {})

            for runtime, sims in devices.items():
                os_version = runtime.replace("com.apple.CoreSimulator.SimRuntime.iOS-", "").replace("-", ".")
                for sim in sims:
                    if sim.get("state") != "Booted" and sim.get("state") != "Shutdown":
                        continue

                    udid = sim.get("udid")
                    name = sim.get("name", "Unknown")
                    is_emulator = True  # Simuladores son emuladores

                    properties = DeviceProperties(
                        model=name,
                        os_version=os_version,
                        is_real=False,
                        is_emulator=True,
                        udid=udid,
                        tags=["local", "ios-simulator", "emulator"],
                    )

                    device = Device(
                        id=f"local:ios:{udid}",
                        provider=DeviceProvider.LOCAL,
                        platform=DevicePlatform.IOS,
                        name=name,
                        properties=properties,
                        status=DeviceStatus.AVAILABLE,
                        cost_per_minute=0.0,
                    )

                    self._local_devices[device.id] = device
                    logger.info(f"iOS Simulator descubierto: {name} ({udid})")

        except FileNotFoundError:
            logger.debug("xcrun no disponible (no macOS), saltando iOS Simulator")
        except Exception as e:
            logger.debug(f"Error descubriendo iOS Simulator: {e}")

    # ─── Cloud Providers (Stub - implementar según APIs) ───

    async def discover_cloud_devices(self, provider: DeviceProvider) -> List[Device]:
        """Descubre dispositivos en proveedor cloud (implementar por proveedor)."""
        # TODO: Implementar llamadas a APIs de BrowserStack, Sauce Labs, etc.
        # Por ahora retorna lista vacía
        logger.info(f"Descubrimiento cloud para {provider.value} no implementado aún")
        return []

    # ─── Public API ───

    async def list_devices(
        self,
        platform: Optional[DevicePlatform] = None,
        provider: Optional[DeviceProvider] = None,
        status: Optional[DeviceStatus] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Device]:
        """Lista dispositivos con filtros."""
        all_devices = list(self._local_devices.values()) + list(self._cloud_devices.values())

        # Refrescar estado desde Redis para reservas
        if self._redis:
            for device in all_devices:
                await self._refresh_device_status(device)

        filtered = all_devices
        if platform:
            filtered = [d for d in filtered if d.platform == platform]
        if provider:
            filtered = [d for d in filtered if d.provider == provider]
        if status:
            filtered = [d for d in filtered if d.status == status]
        if tags:
            filtered = [d for d in filtered if all(t in d.properties.tags for t in tags)]

        return filtered

    async def get_device(self, device_id: str) -> Optional[Device]:
        """Obtiene dispositivo por ID."""
        device = self._local_devices.get(device_id) or self._cloud_devices.get(device_id)
        if device and self._redis:
            await self._refresh_device_status(device)
        return device

    async def reserve_device(
        self,
        device_id: str,
        session_id: str,
        ttl_minutes: int = 30,
    ) -> Device:
        """Reserva dispositivo atómicamente (Lua script en Redis)."""
        device = await self.get_device(device_id)
        if not device:
            raise ValueError(f"Dispositivo no encontrado: {device_id}")

        if device.status == DeviceStatus.RESERVED:
            if device.reserved_by == session_id:
                # Renovar reserva propia
                pass
            else:
                raise ValueError(f"Dispositivo ya reservado por {device.reserved_by}")

        if device.status in [DeviceStatus.BUSY, DeviceStatus.OFFLINE, DeviceStatus.MAINTENANCE]:
            raise ValueError(f"Dispositivo no disponible: {device.status.value}")

        # Validar TTL
        max_ttl = self.settings.max_device_reservation_minutes
        if ttl_minutes > max_ttl:
            ttl_minutes = max_ttl

        # Reserva atómica en Redis
        reserve_key = f"device:reserved:{device_id}"
        reservation_data = {
            "device_id": device_id,
            "session_id": session_id,
            "reserved_at": datetime.now().isoformat(),
            "reserved_until": (datetime.now() + timedelta(minutes=ttl_minutes)).isoformat(),
            "ttl_minutes": ttl_minutes,
        }

        if self._redis:
            # Lua script para reserva atómica
            lua_script = """
            local key = KEYS[1]
            local data = ARGV[1]
            local ttl = tonumber(ARGV[2])
            local existing = redis.call('GET', key)
            if existing then
                return {err = 'already_reserved'}
            end
            redis.call('SETEX', key, ttl, data)
            return {ok = 'reserved'}
            """
            script = self._redis.register_script(lua_script)
            result = await script(keys=[reserve_key], args=[json.dumps(reservation_data), ttl_minutes * 60])

            if isinstance(result, dict) and result.get("err") == "already_reserved":
                existing = await self._redis.get(reserve_key)
                raise ValueError(f"Dispositivo ya reservado: {existing}")

        # Actualizar objeto local
        device.status = DeviceStatus.RESERVED
        device.reserved_by = session_id
        device.reserved_until = datetime.now() + timedelta(minutes=ttl_minutes)

        logger.info(f"Dispositivo reservado: {device_id} por sesión {session_id} ({ttl_minutes} min)")
        return device

    async def release_device(self, device_id: str, session_id: str) -> bool:
        """Libera reserva de dispositivo."""
        device = await self.get_device(device_id)
        if not device:
            return False

        if device.reserved_by != session_id:
            logger.warning(f"Intento de liberar dispositivo {device_id} por sesión no propietaria {session_id}")
            return False

        reserve_key = f"device:reserved:{device_id}"
        if self._redis:
            # Solo borrar si es nuestra reserva
            lua_script = """
            local key = KEYS[1]
            local session = ARGV[1]
            local data = redis.call('GET', key)
            if data then
                local parsed = cjson.decode(data)
                if parsed.session_id == session then
                    redis.call('DEL', key)
                    return 1
                end
            end
            return 0
            """
            script = self._redis.register_script(lua_script)
            await script(keys=[reserve_key], args=[session_id])

        device.status = DeviceStatus.AVAILABLE
        device.reserved_by = None
        device.reserved_until = None

        logger.info(f"Dispositivo liberado: {device_id}")
        return True

    async def _refresh_device_status(self, device: Device) -> None:
        """Refresca estado del dispositivo desde Redis."""
        if not self._redis:
            return

        reserve_key = f"device:reserved:{device.id}"
        reserved = await self._redis.get(reserve_key)
        if reserved:
            import json
            data = json.loads(reserved)
            device.status = DeviceStatus.RESERVED
            device.reserved_by = data.get("session_id")
            if data.get("reserved_until"):
                device.reserved_until = datetime.fromisoformat(data["reserved_until"])
        elif device.status == DeviceStatus.RESERVED:
            # Reserva expirada
            device.status = DeviceStatus.AVAILABLE
            device.reserved_by = None
            device.reserved_until = None

    # ─── Background Tasks ───

    async def _cleanup_expired_reservations(self) -> None:
        """Limpia reservas expiradas periódicamente."""
        while True:
            try:
                await asyncio.sleep(60)  # Cada minuto
                if not self._redis:
                    continue

                # Buscar claves de reserva
                pattern = "device:reserved:*"
                async for key in self._redis.scan_iter(match=pattern):
                    data = await self._redis.get(key)
                    if data:
                        import json
                        parsed = json.loads(data)
                        reserved_until = parsed.get("reserved_until")
                        if reserved_until:
                            until = datetime.fromisoformat(reserved_until)
                            if datetime.now() > until:
                                # Reserva expirada, limpiar
                                device_id = key.replace("device:reserved:", "")
                                device = await self.get_device(device_id)
                                if device:
                                    device.status = DeviceStatus.AVAILABLE
                                    device.reserved_by = None
                                    device.reserved_until = None
                                await self._redis.delete(key)
                                logger.info(f"Reserva expirada limpiada: {device_id}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error en cleanup de reservas: {e}")

    async def _periodic_discovery(self) -> None:
        """Redescubre dispositivos locales periódicamente."""
        while True:
            try:
                await asyncio.sleep(300)  # Cada 5 minutos
                await self._discover_local_devices()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error en descubrimiento periódico: {e}")