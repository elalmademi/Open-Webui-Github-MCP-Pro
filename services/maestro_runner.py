"""
Maestro Runner - Ejecución de flujos Maestro (YAML) para testing móvil declarativo.
"""
import asyncio
import logging
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import get_settings
from services.device_registry import Device

logger = logging.getLogger(__name__)


@dataclass
class MaestroStepResult:
    step_id: str
    action: str
    selector: Optional[str] = None
    success: bool = True
    output: str = ""
    error: Optional[str] = None
    screenshot_b64: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: float = 0.0


@dataclass
class MaestroFlowResult:
    flow_id: str
    flow_name: str
    device_id: str
    steps: List[MaestroStepResult] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    success: bool = True
    error: Optional[str] = None
    artifacts: Dict[str, str] = field(default_factory=dict)  # screenshots, video, logs


class MaestroRunner:
    """
    Runner de flujos Maestro con:
    - Ejecución de YAML flows via `maestro` CLI
    - Generación de flows desde plantillas
    - Captura de screenshots, video, logs
    - Parsing de output estructurado
    - Soporte guided step-by-step
    """

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._maestro_bin = "maestro"  # Asumimos en PATH
        self._active_flows: Dict[str, MaestroFlowResult] = {}

    async def initialize(self) -> None:
        """Verifica que Maestro CLI está disponible."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self._maestro_bin, "version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                version = stdout.decode().strip()
                logger.info(f"Maestro CLI disponible: {version}")
            else:
                logger.warning("Maestro CLI no encontrado o error de versión")
        except FileNotFoundError:
            logger.warning("Maestro CLI no instalado. Instalar con: curl -Ls https://get.maestro.mobile.dev | bash")
        except Exception as e:
            logger.warning(f"Error verificando Maestro: {e}")

    # ─── Flow Execution ───

    async def run_flow(
        self,
        device: Device,
        flow_yaml: str,
        flow_name: str = "custom_flow",
        app_id: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        capture_video: bool = False,
        timeout: int = 300,
    ) -> MaestroFlowResult:
        """
        Ejecuta un flujo Maestro completo.
        Args:
            device: Dispositivo objetivo
            flow_yaml: Contenido YAML del flujo
            flow_name: Nombre identificativo
            app_id: Package name / bundle ID (opcional, para launch)
            env_vars: Variables de entorno adicionales
            capture_video: Grabar video de la ejecución
            timeout: Timeout en segundos
        Returns:
            MaestroFlowResult con resultados paso a paso
        """
        flow_id = f"maestro_{uuid.uuid4().hex[:12]}"
        result = MaestroFlowResult(
            flow_id=flow_id,
            flow_name=flow_name,
            device_id=device.id,
        )
        self._active_flows[flow_id] = result

        # Escribir flow a archivo temporal
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            flow_file = Path(f.name)
            f.write(flow_yaml)

        try:
            # Construir comando maestro
            cmd = [self._maestro_bin, "test", str(flow_file)]

            # Device selection
            if device.properties.udid:
                cmd.extend(["-d", device.properties.udid])

            # App ID
            if app_id:
                cmd.extend(["--app-id", app_id])

            # Format output
            cmd.extend(["--format", "json"])

            # Video
            if capture_video:
                video_path = f"/tmp/maestro_{flow_id}.mp4"
                cmd.extend(["--video", video_path])
                result.artifacts["video"] = video_path

            # Env vars
            env = {**os.environ}
            if env_vars:
                env.update(env_vars)
            if device.platform.value == "android" and device.properties.udid:
                env["ANDROID_SERIAL"] = device.properties.udid

            logger.info(f"Ejecutando Maestro flow: {flow_name} en {device.name}")
            start = datetime.now()

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                result.success = False
                result.error = f"Timeout después de {timeout}s"
                result.completed_at = datetime.now()
                return result

            result.completed_at = datetime.now()

            # Parsear output JSON
            if stdout:
                await self._parse_maestro_output(stdout.decode(), result)

            if proc.returncode != 0:
                result.success = False
                result.error = stderr.decode()[:500] if stderr else f"Exit code {proc.returncode}"
                logger.warning(f"Maestro flow falló: {result.error}")
            else:
                logger.info(f"Maestro flow completado exitosamente: {flow_name}")

        except FileNotFoundError:
            result.success = False
            result.error = "Maestro CLI no encontrado en PATH"
        except Exception as e:
            result.success = False
            result.error = str(e)
            logger.exception(f"Error ejecutando Maestro flow: {e}")
        finally:
            # Cleanup temp file
            try:
                flow_file.unlink()
            except Exception:
                pass

        return result

    async def _parse_maestro_output(self, output: str, result: MaestroFlowResult) -> None:
        """Parsea output JSON de Maestro (streaming JSON lines)."""
        import json
        for line in output.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                await self._process_maestro_event(event, result)
            except json.JSONDecodeError:
                # Línea no JSON (logs, etc.)
                pass

    async def _process_maestro_event(self, event: Dict, result: MaestroFlowResult) -> None:
        """Procesa evento individual de Maestro."""
        event_type = event.get("type", "")

        if event_type == "stepStart":
            step_id = event.get("stepId", "")
            action = event.get("action", "")
            selector = event.get("selector")
            # Crear step result inicial
            step_result = MaestroStepResult(
                step_id=step_id,
                action=action,
                selector=selector,
            )
            result.steps.append(step_result)

        elif event_type == "stepPass":
            step_id = event.get("stepId", "")
            duration = event.get("duration", 0)
            # Actualizar último step
            if result.steps:
                result.steps[-1].success = True
                result.steps[-1].duration_ms = duration
                result.steps[-1].output = "Step passed"

        elif event_type == "stepFail":
            step_id = event.get("stepId", "")
            error = event.get("error", "Unknown error")
            duration = event.get("duration", 0)
            if result.steps:
                result.steps[-1].success = False
                result.steps[-1].error = error
                result.steps[-1].duration_ms = duration
            result.success = False

        elif event_type == "screenshot":
            # Screenshot capturado
            b64 = event.get("data", "")
            if result.steps:
                result.steps[-1].screenshot_b64 = b64
            result.artifacts[f"screenshot_{len(result.steps)}"] = b64

        elif event_type == "log":
            # Log message
            pass

    # ─── Guided Step-by-Step ───

    async def run_guided_step(
        self,
        device: Device,
        action: str,
        selector: Optional[str] = None,
        params: Optional[Dict] = None,
        app_id: Optional[str] = None,
    ) -> MaestroStepResult:
        """
        Ejecuta UN paso guiado (para validación humano-en-el-loop).
        Genera YAML dinámico para el step y lo ejecuta.
        """
        # Generar YAML para step único
        step_yaml = self._generate_step_yaml(action, selector, params)

        flow_name = f"guided_{action}_{uuid.uuid4().hex[:6]}"
        result = await self.run_flow(
            device=device,
            flow_yaml=step_yaml,
            flow_name=flow_name,
            app_id=app_id,
            capture_video=False,
            timeout=60,
        )

        if result.steps:
            return result.steps[0]

        return MaestroStepResult(
            step_id="error",
            action=action,
            success=False,
            error=result.error or "No steps executed",
        )

    def _generate_step_yaml(self, action: str, selector: Optional[str], params: Optional[Dict]) -> str:
        """Genera YAML Maestro para un step individual."""
        step = {
            "action": action,
        }

        if selector:
            step["selector"] = selector

        if params:
            for k, v in params.items():
                step[k] = v

        flow = {
            "appId": params.get("appId") if params else None,
            "steps": [step],
        }

        import yaml
        # Filtrar None
        flow = {k: v for k, v in flow.items() if v is not None}
        return yaml.dump(flow, sort_keys=False, allow_unicode=True)

    # ─── Flow Templates ───

    def get_flow_template(self, template_name: str) -> str:
        """Retorna plantilla YAML predefinida."""
        templates = {
            "login": """
appId: ${APP_ID}
steps:
  - launchApp
  - tapOn:
      id: "login_button"
  - inputText:
      id: "email_field"
      text: "${EMAIL}"
  - inputText:
      id: "password_field"
      text: "${PASSWORD}"
  - tapOn:
      id: "submit_button"
  - assertVisible:
      id: "home_screen"
""",
            "checkout": """
appId: ${APP_ID}
steps:
  - launchApp
  - tapOn:
      text: "Products"
  - scrollUntilVisible:
      text: "Add to Cart"
  - tapOn:
      text: "Add to Cart"
  - tapOn:
      id: "cart_icon"
  - tapOn:
      text: "Checkout"
  - inputText:
      id: "email"
      text: "${EMAIL}"
  - inputText:
      id: "address"
      text: "${ADDRESS}"
  - tapOn:
      text: "Place Order"
  - assertVisible:
      text: "Order Confirmed"
""",
            "onboarding": """
appId: ${APP_ID}
steps:
  - launchApp
  - swipe:
      direction: "left"
      repeat: 3
  - tapOn:
      text: "Get Started"
  - assertVisible:
      id: "home_screen"
""",
        }
        return templates.get(template_name, "")

    def render_template(self, template_name: str, variables: Dict[str, str]) -> str:
        """Rellena plantilla con variables."""
        template = self.get_flow_template(template_name)
        for k, v in variables.items():
            template = template.replace(f"${{{k}}}", v)
        return template

    # ─── Status ───

    def get_flow_status(self, flow_id: str) -> Optional[MaestroFlowResult]:
        return self._active_flows.get(flow_id)

    def list_active_flows(self) -> List[MaestroFlowResult]:
        return list(self._active_flows.values())


# Import os al final para evitar circular import issues
import os