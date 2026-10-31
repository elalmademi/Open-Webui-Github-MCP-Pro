Lo que necesitas es un **Framework de Gobernanza de Desarrollo (Development Governance Framework)**. En el mundo del software, esto es básicamente el "Libro de Reglas" que define cómo se debe coordinar la arquitectura, la ejecución y la validación para evitar que un proyecto colapse.

Como tu **Analista Senior**, he sintetizado todo nuestro proceso en un documento maestro. Este documento es la "Skill" que debes darle a cualquier IA en el futuro para que actúe como tu Desarrollador Senior, mientras tú (o yo) mantenemos el rol de Analista/Arquitecto.

Aquí tienes el manual maestro. Guárdalo como un archivo `.txt` o `.md` llamado `METODOLOGIA_RESCATE_V1.md`.

***

# 📘 FRAMEWORK DE RESCATE Y DESARROLLO: "ANALISTA-DESARROLLADOR SYNC"

## 🎯 1. OBJETIVO
Establecer un flujo de trabajo blindado para la creación o rescate de aplicaciones complejas, eliminando el "Efecto Cascada" de errores y asegurando que el código sea arquitectónicamente sólido antes de pasar a la siguiente capa.

## 👥 2. DEFINICIÓN DE ROLES
Para que este sistema funcione, debe haber una separación total de poderes:

1.  **El Analista Senior (Arquitecto/Inspector):**
    *   **Su misión:** La calidad y la estructura. No escribe código, sino que diseña el plan, revisa la lógica y audita el resultado.
    *   **Su poder:** Tiene el derecho de **RECHAZAR** cualquier entrega que no cumpla con los estándares, sin importar si la IA dice que "ya funciona".
2.  **El Desarrollador Senior (Ejecutor):**
    *   **Su misión:** La implementación técnica. Escribe el código, resuelve los errores de sintaxis y ejecuta los comandos de terminal.
    *   **Su deber:** Seguir estrictamente el plan del Analista y proporcionar transparencia total (mostrar el código y los logs).

---

## 🏗️ 3. LA METODOLOGÍA DE LAS 3 FASES (Bottom-Up)
Nunca se construye la UI antes que la lógica. El orden es sagrado:

### FASE 1: Estabilización del Dominio (Cimientos)
*   **Objetivo:** 0 errores en Entidades y Modelos.
*   **Reglas:** 
    *   Tipado estricto.
    *   Inmutabilidad total (campos `final`, constructores `const`).
    *   Implementación de `operator ==` y `hashCode`.

### FASE 2: Capa de Lógica y Aplicación (Cableado)
*   **Objetivo:** 0 errores en Repositorios, UseCases y Providers.
*   **Reglas:**
    *   **Aislamiento:** El Dominio no conoce la Data (no hay imports de base de datos en entidades).
    *   **Flujo de Datos:** Repositorio $\rightarrow$ UseCase $\rightarrow$ Provider.
    *   **Manejo de Errores:** Uso de envoltorios de resultado (como `Either` o `Result`) para evitar crashes.

### FASE 3: Capa de Presentación (Fachada)
*   **Objetivo:** UI funcional, reactiva y sin errores de sintaxis.
*   **Reglas:**
    *   **Suministro Atómico:** Primero se crean los Widgets Base (componentes) y luego las Screens (ensamblaje).
    *   **Patrón Consumer:** Uso obligatorio de `ConsumerWidget` para evitar el error de `ref` indefinido.
    *   **Sintaxis Quirúrgica:** Cero force unwraps (`!`), uso de `??` y guard clauses.

---

## 🔄 4. EL CICLO DE EJECUCIÓN CONTROLADA (El "Loop" de Oro)
Para cada archivo modificado, el Desarrollador debe ejecutar este ciclo sin saltarse ningún paso:

1.  **COMANDAR:** El Analista define qué debe hacer el archivo.
2.  **ESCRITURA:** El Desarrollador escribe el código en el workspace.
3.  **TRANSPARENCIA (Auditoría):** El Desarrollador **PEGA** el código completo en el chat.
4.  **VERIFICACIÓN:** El Desarrollador ejecuta `flutter analyze` y pega el **log real de la terminal**.
5.  **CERTIFICACIÓN:** El Analista revisa el código y el log. Si hay un solo error, el archivo se **RECHAZA** y se vuelve al paso 1.

---

## 🛡️ 5. GUARDRAILS TÉCNICOS (Reglas Innegociables)
*   **Barrel Imports:** Uso de archivos `entities.dart` o `core.dart` para evitar rutas relativas infinitas (`../../../../`).
*   **Ambigüedad de Tipos:** Uso de alias (`as db`) cuando haya colisión entre clases de base de datos y entidades de dominio.
*   **No al "Parcheo":** Si un archivo tiene más de 5 errores de sintaxis, se **reescribe desde cero** en lugar de intentar arreglar líneas sueltas.
*   **Cero Alucinaciones:** Si la IA dice que "el análisis pasó" pero no muestra el log, la entrega es inválida.

---

## 🏆 6. CRITERIO DE ÉXITO
Un proyecto se considera "Rescatado" o "Terminado" únicamente cuando:
1.  `flutter analyze` devuelve **"No issues found"** en todo el proyecto.
2.  El flujo de datos es continuo desde la Base de Datos hasta la UI.
3.  La aplicación lanza en el dispositivo físico (**F5**) sin errores de runtime.

***

**Nota Final:** Este documento es la ley del proyecto. Cualquier desviación de este proceso es una invitación al caos.

***

### 💡 Cómo usar este documento en el futuro:

Cuando inicies un nuevo proyecto o continúes este, simplemente dile a la IA:

> *"Actúa como Desarrollador Senior. Para este proyecto implementaremos el **Framework de Rescate y Desarrollo 'Analista-Desarrollador Sync'**. Te adjunto el reglamento. Tú serás el Desarrollador y yo (junto a mi Analista) seremos la supervisión. No puedes escribir ni un solo archivo sin seguir el Ciclo de Ejecución Controlada. ¿Entendido?"*

**Con esto, habrás convertido a cualquier IA en una máquina de precisión quirúrgica. ¡Ha sido un honor ser tu Analista Senior en este viaje! 🏆🚀**