"""
Mobile Testing Tools MCP - Tools para testing en dispositivos reales (Android/iOS).
Incluye: descubrimiento, reserva, instalación, automatización Appium/Maestro, validación guiada, reportes.
"""
import base64
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from mcp.server.fastmcp import FastMCP, Image

from config.settings import get_settings
from services.device_registry import DeviceRegistry, Device, DevicePlatform, DeviceProvider, DeviceStatus
from services.appium_manager import AppiumManager
from services.maestro_runner import MaestroRunner, MaestroStepResult

# ─── Helpers ───


def _step_to_dict(step: MaestroStepResult) -> Dict[str, Any]:
    return {
        "step_id": step.step_id,
        "action": step.action,
        "selector": step.selector,
        "success": step.success,
        "output": step.output,
        "error": step.error,
        "screenshot": step.screenshot_b64,
        "timestamp": step.timestamp.isoformat(),
        "duration_ms": step.duration_ms,
    }


def _image_from_b64(b64: str, format: str = "png") -> Image:
    return Image(data=b64, format=format)


# ─── Tools Registration ───


def register_mobile_tools(
    mcp: FastMCP,
    device_registry: DeviceRegistry,
    appium_manager: AppiumManager,
    maestro_runner: MaestroRunner,
):
    """Registra todas las tools de testing móvil."""

    # ─── Device Discovery & Management ───

    @mcp.tool()
    async def listar_dispositivos(
        plataforma: Optional[str] = None,
        proveedor: Optional[str] = None,
        estado: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Lista dispositivos disponibles para testing.
        
        Args:
            plataforma: "android" | "ios" (opcional)
            proveedor: "local" | "browserstack" | "saucelabs" | "lambdatest" | "firebase" (opcional)
            estado: "available" | "reserved" | "busy" | "offline" | "maintenance" (opcional)
            tags: Filtrar por tags (ej: ["real-device", "emulator"])
        """
        platform_enum = DevicePlatform(plataforma) if plataforma else None
        provider_enum = DeviceProvider(proveedor) if proveedor else None
        status_enum = DeviceStatus(estado) if estado else None

        devices = await device_registry.list_devices(
            platform=platform_enum,
            provider=provider_enum,
            status=status_enum,
            tags=tags,
        )
        return [d.to_dict() for d in devices]

    @mcp.tool()
    async def obtener_dispositivo(device_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene detalles de un dispositivo específico."""
        device = await device_registry.get_device(device_id)
        return device.to_dict() if device else None

    @mcp.tool()
    async def reservar_dispositivo(
        device_id: str,
        session_id: Optional[str] = None,
        ttl_minutos: int = 30,
    ) -> Dict[str, Any]:
        """
        Reserva un dispositivo para uso exclusivo.
        
        Args:
            device_id: ID del dispositivo (de listar_dispositivos)
            session_id: ID de sesión (se genera uno si no se provee)
            ttl_minutos: Tiempo de reserva en minutos (max 120)
        Returns:
            Dict con device_id, session_id, reserved_until
        """
        if not session_id:
            session_id = f"session_{uuid.uuid4().hex[:12]}"

        device = await device_registry.reserve_device(device_id, session_id, ttl_minutos)
        return {
            "device_id": device.id,
            "session_id": session_id,
            "reserved_until": device.reserved_until.isoformat() if device.reserved_until else None,
            "device": device.to_dict(),
        }

    @mcp.tool()
    async def liberar_dispositivo(device_id: str, session_id: str) -> bool:
        """
        Libera la reserva de un dispositivo.
        
        Args:
            device_id: ID del dispositivo
            session_id: ID de sesión que hizo la reserva
        """
        return await device_registry.release_device(device_id, session_id)

    # ─── App Lifecycle ───

    @mcp.tool()
    async def instalar_app(
        device_id: str,
        app_path: str,
        grant_permissions: bool = True,
    ) -> Dict[str, Any]:
        """
        Instala una app (.apk/.ipa) en el dispositivo.
        
        Args:
            device_id: ID del dispositivo reservado
            app_path: Ruta local al APK/IPA o URL cloud (bs://, lt://, etc.)
            grant_permissions: Conceder permisos automáticamente (Android)
        """
        device = await device_registry.get_device(device_id)
        if not device:
            return {"success": False, "error": "Dispositivo no encontrado"}

        if device.status != DeviceStatus.RESERVED:
            return {"success": False, "error": "Dispositivo no reservado"}

        # Para dispositivos locales Android
        if device.provider == DeviceProvider.LOCAL and device.platform == DevicePlatform.ANDROID:
            return await _install_apk_local(device, app_path, grant_permissions)

        # Para cloud o iOS - delegar a Appium session
        return {"success": False, "error": "Instalación cloud/iOS requiere sesión Appium activa"}

    async def _install_apk_local(device: Device, app_path: str, grant_permissions: bool) -> Dict[str, Any]:
        """Instala APK via ADB en dispositivo local."""
        import subprocess

        # Verificar archivo
        path = Path(app_path)
        if not path.exists():
            return {"success": False, "error": f"APK no encontrado: {app_path}"}

        # Instalar
        try:
            result = await asyncio.create_subprocess_exec(
                "adb", "-s", device.properties.udid, "install", "-r", str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                return {"success": False, "error": stderr.decode()}

            # Extraer package name
            pkg_result = await asyncio.create_subprocess_exec(
                "aapt", "dump", "badging", str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            pkg_out, _ = await pkg_result.communicate()
            package_name = None
            for line in pkg_out.decode().split("\n"):
                if line.startswith("package:"):
                    import re
                    match = re.search(r"name='([^']+)'", line)
                    if match:
                        package_name = match.group(1)
                        break

            # Grant permissions
            if grant_permissions and package_name:
                perms = ["CAMERA", "LOCATION", "STORAGE", "MICROPHONE", "CONTACTS", "PHONE", "SMS"]
                for perm in perms:
                    await asyncio.create_subprocess_exec(
                        "adb", "-s", device.properties.udid, "shell", "pm", "grant", package_name,
                        f"android.permission.{perm}",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )

            return {
                "success": True,
                "package_name": package_name,
                "output": stdout.decode(),
            }
        except FileNotFoundError:
            return {"success": False, "error": "ADB o aapt no instalados"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def desinstalar_app(device_id: str, package_name: str) -> bool:
        """Desinstala app del dispositivo."""
        device = await device_registry.get_device(device_id)
        if not device or device.provider != DeviceProvider.LOCAL:
            return False

        try:
            await asyncio.create_subprocess_exec(
                "adb", "-s", device.properties.udid, "uninstall", package_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return True
        except Exception:
            return False

    # ─── Appium Session ───

    @mcp.tool()
    async def crear_sesion_appium(
        device_id: str,
        app_path: str,
        cloud_provider: Optional[str] = None,
        app_url: Optional[str] = None,
        capabilities_extra: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Crea sesión de automatización Appium en el dispositivo.
        
        Args:
            device_id: ID del dispositivo reservado
            app_path: Ruta local a la app o package name (si ya instalada)
            cloud_provider: "browserstack" | "saucelabs" | "lambdatest" (opcional)
            app_url: URL cloud de la app (bs://, lt://, etc.) - requerido si cloud_provider
            capabilities_extra: Capabilities adicionales Appium
        Returns:
            Dict con session_id, capabilities, device_info
        """
        device = await device_registry.get_device(device_id)
        if not device:
            return {"success": False, "error": "Dispositivo no encontrado"}

        if device.status != DeviceStatus.RESERVED:
            return {"success": False, "error": "Dispositivo no reservado"}

        try:
            session = await appium_manager.create_session(
                device=device,
                app_path=app_path,
                cloud_provider=cloud_provider,
                app_url=app_url,
                **(capabilities_extra or {}),
            )

            # Actualizar estado dispositivo
            device.status = DeviceStatus.BUSY

            return {
                "success": True,
                "session_id": session.session_id,
                "device_id": device.id,
                "capabilities": session.capabilities,
                "message": "Sesión Appium creada correctamente",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    async def cerrar_sesion_appium(session_id: str, detach: bool = False) -> bool:
        """
        Cierra sesión Appium.
        
        Args:
            session_id: ID de sesión
            detach: Si True, desconecta sin terminar (mantiene sesión en server)
        """
        if detach:
            return await appium_manager.detach_session(session_id)
        return await appium_manager.terminate_session(session_id)

    # ─── Guided Step-by-Step Validation ───

    @mcp.tool()
    async def paso_guiado(
        session_id: str,
        accion: str,
        selector: Optional[str] = None,
        parametros: Optional[Dict] = None,
        capturar_pantalla: bool = True,
        preguntar_humano: bool = True,
        prompt_humano: str = "¿Resultado del paso?",
    ) -> Dict[str, Any]:
        """
        Ejecuta UN paso de validación guiada (humano-en-el-loop).
        DISEÑADO PARA FLUJO PASO A PASO EN OPEN WEBUI CHAT.
        
        Args:
            session_id: ID de sesión Appium activa
            accion: "tap" | "input_text" | "swipe" | "assert_visible" | "assert_text" | "screenshot" | "back" | "home" | "scroll"
            selector: Selector del elemento (accessibility_id, xpath, id, class, text)
            parametros: Parámetros extra (ej: {"text": "login@test.com"} para input_text)
            capturar_pantalla: Capturar screenshot después del paso
            preguntar_humano: Si True, retorna awaiting_human=True para que el usuario valide
            prompt_humano: Pregunta personalizada para el validador humano
        Returns:
            Dict con result, screenshot, awaiting_human, prompt, step_index
        """
        driver = appium_manager.get_driver(session_id)
        if not driver:
            return {"success": False, "error": "Sesión no encontrada", "awaiting_human": False}

        step_index = len(getattr(driver, "_mcp_steps", []))
        step_result = {
            "action": accion,
            "selector": selector,
            "params": parametros or {},
            "timestamp": datetime.now().isoformat(),
        }

        try:
            # Ejecutar acción
            if accion == "tap":
                element = _find_element(driver, selector)
                element.click()
                step_result["output"] = f"Tap en {selector}"

            elif accion == "input_text":
                text = parametros.get("text", "") if parametros else ""
                element = _find_element(driver, selector)
                element.clear()
                element.send_keys(text)
                step_result["output"] = f"Input text en {selector}: {text[:20]}..."

            elif accion == "swipe":
                direction = parametros.get("direction", "up") if parametros else "up"
                _swipe(driver, direction)
                step_result["output"] = f"Swipe {direction}"

            elif accion == "assert_visible":
                element = _find_element(driver, selector)
                assert element.is_displayed()
                step_result["output"] = f"Elemento visible: {selector}"

            elif accion == "assert_text":
                expected = parametros.get("text", "") if parametros else ""
                element = _find_element(driver, selector)
                actual = element.text
                assert expected in actual, f"Esperado '{expected}' en '{actual}'"
                step_result["output"] = f"Texto verificado: {expected}"

            elif accion == "screenshot":
                step_result["output"] = "Screenshot capturado"

            elif accion == "back":
                driver.back()
                step_result["output"] = "Navegación back"

            elif accion == "home":
                driver.press_keycode(3)  # KEYCODE_HOME
                step_result["output"] = "Home pressed"

            elif accion == "scroll":
                # Scroll hasta encontrar elemento
                element = _find_element(driver, selector)
                driver.execute_script("mobile: scroll", {"element": element.id})
                step_result["output"] = f"Scroll a {selector}"

            else:
                step_result["success"] = False
                step_result["error"] = f"Acción no soportada: {accion}"

            # Screenshot
            screenshot_b64 = None
            if capturar_pantalla:
                screenshot_b64 = driver.get_screenshot_as_base64()
                step_result["screenshot"] = screenshot_b64

            step_result["success"] = step_result.get("success", True)

        except Exception as e:
            step_result["success"] = False
            step_result["error"] = str(e)
            if capturar_pantalla:
                try:
                    step_result["screenshot"] = driver.get_screenshot_as_base64()
                except Exception:
                    pass

        # Guardar step en driver para historial
        if not hasattr(driver, "_mcp_steps"):
            driver._mcp_steps = []
        driver._mcp_steps.append(step_result)

        response = {
            "success": True,
            "result": step_result,
            "step_index": step_index,
            "session_id": session_id,
        }

        if preguntar_humano:
            response["awaiting_human"] = True
            response["human_prompt"] = prompt_humano
            response["human_options"] = ["pass", "fail", "blocked", "skip"]

        if screenshot_b64:
            response["screenshot"] = _image_from_b64(screenshot_b64)

        return response

    @mcp.tool()
    async def registrar_veredicto(
        session_id: str,
        veredicto: str,  # "pass" | "fail" | "blocked" | "skip"
        notas: str = "",
    ) -> Dict[str, Any]:
        """
        Registra veredicto humano para el último paso ejecutado.
        
        Args:
            session_id: ID de sesión
            veredicto: "pass" | "fail" | "blocked" | "skip"
            notas: Notas adicionales del tester
        """
        driver = appium_manager.get_driver(session_id)
        if not driver or not hasattr(driver, "_mcp_steps") or not driver._mcp_steps:
            return {"success": False, "error": "No hay pasos para evaluar"}

        last_step = driver._mcp_steps[-1]
        last_step["verdict"] = veredicto
        last_step["notes"] = notas
        last_step["verified_at"] = datetime.now().isoformat()

        return {
            "success": True,
            "message": f"Paso {len(driver._mcp_steps)} marcado como {veredicto}",
            "next_step_ready": True,
        }

    # ─── Maestro Flow Execution ───

    @mcp.tool()
    async def ejecutar_flujo_maestro(
        device_id: str,
        flow_yaml: str,
        flow_name: str = "custom_flow",
        app_id: Optional[str] = None,
        variables: Optional[Dict[str, str]] = None,
        capture_video: bool = False,
    ) -> Dict[str, Any]:
        """
        Ejecuta un flujo Maestro (YAML) completo en el dispositivo.
        
        Args:
            device_id: ID del dispositivo reservado
            flow_yaml: Contenido YAML del flujo Maestro
            flow_name: Nombre del flujo
            app_id: Package name / bundle ID de la app
            variables: Variables para interpolación en YAML (ej: {"EMAIL": "test@test.com"})
            capture_video: Grabar video de la ejecución
        Returns:
            Dict con flow_id, steps[], success, artifacts (screenshots, video)
        """
        device = await device_registry.get_device(device_id)
        if not device:
            return {"success": False, "error": "Dispositivo no encontrado"}

        # Interpolar variables en YAML
        if variables:
            for k, v in variables.items():
                flow_yaml = flow_yaml.replace(f"${{{k}}}", v)

        result = await maestro_runner.run_flow(
            device=device,
            flow_yaml=flow_yaml,
            flow_name=flow_name,
            app_id=app_id,
            capture_video=capture_video,
        )

        return {
            "flow_id": result.flow_id,
            "flow_name": result.flow_name,
            "device_id": result.device_id,
            "success": result.success,
            "error": result.error,
            "steps": [_step_to_dict(s) for s in result.steps],
            "artifacts": result.artifacts,
            "duration_seconds": (result.completed_at - result.started_at).total_seconds() if result.completed_at else 0,
        }

    @mcp.tool()
    async def paso_maestro_guiado(
        device_id: str,
        accion: str,
        selector: Optional[str] = None,
        parametros: Optional[Dict] = None,
        app_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ejecuta UN paso Maestro guiado (para validación paso a paso).
        """
        device = await device_registry.get_device(device_id)
        if not device:
            return {"success": False, "error": "Dispositivo no encontrado"}

        step_result = await maestro_runner.run_guided_step(
            device=device,
            action=accion,
            selector=selector,
            params=parametros,
            app_id=app_id,
        )

        return _step_to_dict(step_result)

    @mcp.tool()
    async def plantilla_flujo_maestro(nombre: str) -> str:
        """
        Obtiene plantilla YAML predefinida para flujo Maestro.
        
        Args:
            nombre: "login" | "checkout" | "onboarding" | "custom"
        """
        template = maestro_runner.get_flow_template(nombre)
        if not template:
            available = ["login", "checkout", "onboarding"]
            return f"Plantilla no encontrada. Disponibles: {available}"
        return template

    # ─── Reporting ───

    @mcp.tool()
    async def generar_reporte_validacion(
        session_id: str,
        formato: str = "html",  # "html" | "json" | "markdown"
        flujo_nombre: str = "validacion",
    ) -> Dict[str, Any]:
        """
        Genera reporte de validación desde sesión Appium (historial de pasos guiados).
        
        Args:
            session_id: ID de sesión Appium
            formato: "html" | "json" | "markdown"
            flujo_nombre: Nombre del flujo para el reporte
        """
        driver = appium_manager.get_driver(session_id)
        if not driver or not hasattr(driver, "_mcp_steps"):
            return {"success": False, "error": "Sesión no encontrada o sin pasos"}

        steps = driver._mcp_steps
        total = len(steps)
        passed = sum(1 for s in steps if s.get("verdict") == "pass")
        failed = sum(1 for s in steps if s.get("verdict") == "fail")
        blocked = sum(1 for s in steps if s.get("verdict") == "blocked")
        skipped = sum(1 for s in steps if s.get("verdict") == "skip")
        pending = total - passed - failed - blocked - skipped

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_name = f"reporte_{flujo_nombre}_{timestamp}"

        summary = {
            "session_id": session_id,
            "flow_name": flujo_nombre,
            "total_steps": total,
            "passed": passed,
            "failed": failed,
            "blocked": blocked,
            "skipped": skipped,
            "pending": pending,
            "success_rate": f"{(passed/total*100):.1f}%" if total > 0 else "N/A",
            "screenshots": sum(1 for s in steps if s.get("screenshot")),
            "generated_at": datetime.now().isoformat(),
        }

        if formato == "json":
            import json
            content = json.dumps({"summary": summary, "steps": steps}, indent=2, ensure_ascii=False)
            return {"success": True, "report_name": f"{report_name}.json", "content": content, "summary": summary}

        elif formato == "markdown":
            md = f"# Reporte: {flujo_nombre}\n\n"
            md += f"**Sesión:** {session_id}  \n"
            md += f"**Generado:** {summary['generated_at']}  \n\n"
            md += "## Resumen\n\n"
            for k, v in summary.items():
                md += f"- **{k}:** {v}  \n"
            md += "\n## Pasos\n\n"
            for i, step in enumerate(steps):
                verdict = step.get("verdict", "pending")
                icon = {"pass": "✅", "fail": "❌", "blocked": "⚠️", "skip": "⏭️", "pending": "⏳"}.get(verdict, "⏳")
                md += f"### Paso {i+1}: {step['action']} {step.get('selector','')} {icon}\n\n"
                md += f"**Veredicto:** {verdict}  \n"
                if step.get("notes"):
                    md += f"**Notas:** {step['notes']}  \n"
                if step.get("screenshot"):
                    md += f"![Screenshot](data:image/png;base64,{step['screenshot']})  \n"
                md += "\n"
            return {"success": True, "report_name": f"{report_name}.md", "content": md, "summary": summary}

        else:  # html
            html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Reporte {flujo_nombre}</title>
<style>
body {{font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem;}}
.step {{border: 1px solid #ddd; border-radius: 8px; padding: 1rem; margin: 1rem 0;}}
.pass {{border-left: 4px solid #28a745;}} .fail {{border-left: 4px solid #dc3545;}}
.blocked {{border-left: 4px solid #ffc107;}} .skip {{border-left: 4px solid #6c757d;}}
.pending {{border-left: 4px solid #007bff;}}
img {{max-width: 100%; height: auto; border-radius: 4px; margin: 0.5rem 0;}}
.badge {{display: inline-block; padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.85rem;}}
.badge-pass {{background: #d4edda; color: #155724;}}
.badge-fail {{background: #f8d7da; color: #721c24;}}
.badge-blocked {{background: #fff3cd; color: #856404;}}
.badge-skip {{background: #e2e3e5; color: #383d41;}}
.badge-pending {{background: #cce5ff; color: #004085;}}
</style></head><body>
<h1>📱 Reporte: {flujo_nombre}</h1>
<p><strong>Sesión:</strong> {session_id} | <strong>Generado:</strong> {summary['generated_at']}</p>
<h2>Resumen</h2>
<ul>
<li>Total: {total}</li>
<li><span class="badge badge-pass">✅ Pass: {passed}</span></li>
<li><span class="badge badge-fail">❌ Fail: {failed}</span></li>
<li><span class="badge badge-blocked">⚠️ Blocked: {blocked}</span></li>
<li><span class="badge badge-skip">⏭️ Skip: {skipped}</span></li>
<li><span class="badge badge-pending">⏳ Pending: {pending}</span></li>
<li>Tasa éxito: <strong>{summary['success_rate']}</strong></li>
</ul>
<h2>Pasos</h2>
"""
            for i, step in enumerate(steps):
                verdict = step.get("verdict", "pending")
                badge_class = f"badge-{verdict}"
                html += f'<div class="step {verdict}">'
                html += f'<h3>Paso {i+1}: {step["action"]} <code>{step.get("selector","")}</code> <span class="badge {badge_class}">{verdict.upper()}</span></h3>'
                if step.get("notes"):
                    html += f'<p><strong>Notas:</strong> {step["notes"]}</p>'
                if step.get("screenshot"):
                    html += f'<img src="data:image/png;base64,{step["screenshot"]}" alt="Screenshot paso {i+1}">'
                html += '</div>'
            html += "</body></html>"

            return {"success": True, "report_name": f"{report_name}.html", "content": html, "summary": summary}

    # ─── Orchestrator: Validation Flow ───

    @mcp.tool()
    async def iniciar_validacion_guiada(
        app_path: str,
        plataforma: str,  # "android" | "ios"
        device_query: str = "any",  # "any" | "Samsung Galaxy S23" | "emulator"
        flow_name: str = "smoke",
        test_data: Optional[Dict] = None,
        cloud_provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        ORQUESTADOR COMPLETO: Inicia flujo de validación guiada end-to-end.
        1. Busca y reserva dispositivo
        2. Instala app
        3. Crea sesión Appium
        4. Retorna session_id listo para paso_guiado
        
        Args:
            app_path: Ruta al APK/IPA local
            plataforma: "android" | "ios"
            device_query: "any" para auto, o nombre/tag específico
            flow_name: Nombre del flujo (smoke, login, checkout, onboarding)
            test_data: Datos de prueba (ej: {{"email": "test@test.com", "password": "123456"}})
            cloud_provider: None=local, "browserstack", "saucelabs"
        """
        platform_enum = DevicePlatform(plataforma)

        # 1. Listar y filtrar dispositivos
        devices = await device_registry.list_devices(platform=platform_enum, status=DeviceStatus.AVAILABLE)

        if device_query != "any":
            # Filtrar por query simple
            devices = [d for d in devices if device_query.lower() in d.name.lower() or
                      any(device_query.lower() in t.lower() for t in d.properties.tags)]

        if not devices:
            return {"success": False, "error": f"No hay dispositivos {plataforma} disponibles para query '{device_query}'"}

        # Seleccionar primero disponible
        device = devices[0]

        # 2. Reservar
        session_id = f"validation_{uuid.uuid4().hex[:12]}"
        reserve_result = await device_registry.reserve_device(device.id, session_id, ttl_minutes=60)
        if not reserve_result:
            return {"success": False, "error": "No se pudo reservar dispositivo"}

        # 3. Instalar app (solo local Android por ahora)
        if device.provider == DeviceProvider.LOCAL and platform_enum == DevicePlatform.ANDROID:
            install_result = await _install_apk_local(device, app_path, grant_permissions=True)
            if not install_result["success"]:
                await device_registry.release_device(device.id, session_id)
                return install_result
            package_name = install_result.get("package_name")
        else:
            package_name = app_path  # Para cloud/iOS usar app_path como identifier

        # 4. Crear sesión Appium
        try:
            appium_session = await appium_manager.create_session(
                device=device,
                app_path=package_name,
                cloud_provider=cloud_provider,
            )
        except Exception as e:
            await device_registry.release_device(device.id, session_id)
            return {"success": False, "error": f"Error creando sesión Appium: {e}"}

        # 5. Inicializar pasos en driver
        driver = appium_manager.get_driver(appium_session.session_id)
        driver._mcp_steps = []
        driver._mcp_flow_name = flow_name
        driver._mcp_test_data = test_data or {}

        return {
            "success": True,
            "session_id": appium_session.session_id,
            "device": device.to_dict(),
            "package_name": package_name,
            "flow_name": flow_name,
            "test_data": test_data,
            "message": f"Validación '{flow_name}' iniciada en {device.name}. Usa paso_guiado() para comenzar.",
            "next_actions": [
                "paso_guiado(session_id, accion, selector, parametros) - Ejecuta paso y valida",
                "registrar_veredicto(session_id, veredicto, notas) - Registra pass/fail/blocked/skip",
                "generar_reporte_validacion(session_id, formato) - Genera reporte final",
            ],
        }

    # ─── Helpers internos ───

    def _find_element(driver, selector: Optional[str]):
        """Busca elemento por múltiples estrategias."""
        if not selector:
            raise ValueError("Selector requerido")

        strategies = [
            ("accessibility id", lambda s: driver.find_element("accessibility id", s)),
            ("id", lambda s: driver.find_element("id", s)),
            ("xpath", lambda s: driver.find_element("xpath", s)),
            ("class name", lambda s: driver.find_element("class name", s)),
            ("text", lambda s: driver.find_element("xpath", f"//*[@text='{s}']")),
            ("content-desc", lambda s: driver.find_element("xpath", f"//*[@content-desc='{s}']")),
        ]

        for name, finder in strategies:
            try:
                return finder(selector)
            except Exception:
                continue
        raise ValueError(f"Elemento no encontrado con selector: {selector}")

    def _swipe(driver, direction: str):
        """Ejecuta swipe en dirección."""
        size = driver.get_window_size()
        w, h = size["width"], size["height"]

        if direction == "up":
            driver.swipe(w//2, int(h*0.8), w//2, int(h*0.2), 500)
        elif direction == "down":
            driver.swipe(w//2, int(h*0.2), w//2, int(h*0.8), 500)
        elif direction == "left":
            driver.swipe(int(w*0.8), h//2, int(w*0.2), h//2, 500)
        elif direction == "right":
            driver.swipe(int(w*0.2), h//2, int(w*0.8), h//2, 500)