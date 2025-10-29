# 🌾 El Silo Proyect (Versión 1.0)

Aplicación web avanzada para la **gestión de stocks agrícolas, ventas, usuarios, depósitos y movimientos**, desarrollada con **Flask**, **SQLAlchemy**, **HTML**, **CSS** y **Bootstrap 5**.
El objetivo es ofrecer una herramienta multiusuario robusta, segura y práctica para llevar un control detallado del inventario, registrar todas las operaciones y generar reportes analíticos para la toma de decisiones.

---

## **Objetivos SMART**

* **Específico (Specific):** Desarrollar una aplicación web que permita la gestión completa del ciclo de inventario: registro de stocks y depósitos, procesamiento de ventas con deducción automática, y generación de reportes operativos y financieros. El sistema deberá contar con un módulo de administración de usuarios basado en roles.
* **Medible (Measurable):** El éxito se medirá por la capacidad del sistema de procesar el 100% de las operaciones de stock y ventas sin errores, y generar los 5 reportes clave (Valor de Inventario, Ventas por Período, etc.) en menos de 15 segundos.
* **Alcanzable (Achievable):** El proyecto es realizable utilizando el stack tecnológico de Flask, SQLAlchemy y Bootstrap, que es ideal para un desarrollo ágil y escalable.
* **Relevante (Relevant):** La aplicación ataca directamente la necesidad de digitalizar y automatizar el control de inventario en el sector agrícola, reduciendo errores manuales, optimizando la gestión de ventas y mejorando la visibilidad financiera del stock.
* **Limitado en el Tiempo (Time-bound):** Se establece un plazo de 8 semanas para completar el desarrollo, las pruebas y la implementación de todas las funcionalidades descritas.

---

## **🎯 Indicadores de Éxito (KPIs)**

El éxito del proyecto se mide por el cumplimiento de los siguientes indicadores funcionales clave:

1.  **Integridad de la Carga Masiva:** El sistema debe procesar archivos Excel de hasta 200 registros (usuarios, stocks o depósitos) con una tasa de éxito del 100%, omitiendo únicamente las filas con datos inconsistentes (ej. depósitos no existentes) e informando al administrador.
2.  **Precisión de Exportación:** Todos los reportes generados (Excel y PDF) deben reflejar con una precisión del 100% los datos presentes en la base de datos al momento de la exportación, incluyendo cálculos de totales y filtros aplicados.
3.  **Trazabilidad Completa de Movimientos:** El 100% de las operaciones que modifican datos (creación, edición, eliminación de stocks, ventas, depósitos y usuarios) deben generar un registro correspondiente en el historial de movimientos, incluyendo el detalle de la operación.
4.  **Capacidad de Usuarios:** La plataforma debe soportar la gestión de hasta 50 usuarios concurrentes sin degradación perceptible en el rendimiento, con tiempos de respuesta para operaciones CRUD inferiores a 3 segundos.

---

## **Diagrama de Contexto**

* **Sistema Central:** `Sistema de Gestión "El Silo"`
* **Actores Externos:**
    * `Administrador`: Supervisa la operación y gestiona los accesos.
    * `Usuario`: Realiza las operaciones diarias de inventario y ventas.
* **Flujos de Datos Principales:**
    * **Usuario → Sistema:** Registra/edita/elimina ventas, stocks y depósitos.
    * **Sistema → Usuario:** Muestra el estado del stock, presenta notificaciones de inventario (stock bajo/agotado), permite generar reportes operativos.
    * **Administrador → Sistema:** Gestiona usuarios (crea, resetea contraseña), supervisa todos los movimientos y reportes.
    * **Sistema → Administrador:** Presenta notificaciones administrativas (solicitud de reseteo), ofrece reportes financieros y de rentabilidad.

---

## **Mapa de Impacto**

* **OBJETIVO (Why?):** Optimizar la gestión del ciclo de ventas e inventario para maximizar la rentabilidad y eficiencia operativa.
* **ACTORES (Who?):**
    * Usuario (Operador de Ventas/Depósito)
    * Administrador (Gerente/Supervisor)
* **IMPACTOS (How?):**
    * **Para el Usuario:**
        * Agilizar el registro de ventas.
        * Tener visibilidad inmediata del stock disponible.
        * Evitar errores al vender productos sin stock.
    * **Para el Administrador:**
        * Conocer la rentabilidad de las ventas.
        * Optimizar las decisiones de compra basadas en reportes de movimiento de stock.
        * Controlar y auditar todas las operaciones de manera centralizada.
* **ENTREGABLES (What?):**
    * **Módulo de Ventas:** Interfaz de registro, edición y exportación de ventas.
    * **Módulo de Inventario:** CRUD para stocks y depósitos con importación masiva.
    * **Módulo de Movimientos:** Log de trazabilidad para cada operación.
    * **Módulo de Reportes:** Generador a medida con filtros y exportación (Excel/PDF).
    * **Módulo de Administración:** Panel para la gestión de usuarios y sus accesos.

---

## **Historias de Usuario y Criterios de Aceptación**

1.  **HU01: Registrar una Venta**
    * **Como** usuario,
    * **quiero** registrar una nueva venta seleccionando un producto del stock existente,
    * **para** que la cantidad vendida se descuente automáticamente del inventario.
    * **Criterios de Aceptación:**
        * El formulario solo debe mostrar productos con cantidad mayor a cero.
        * El sistema debe impedir vender una cantidad mayor al stock disponible.
        * Al confirmar la venta, el stock del producto debe actualizarse instantáneamente.
        * La operación debe quedar registrada en el historial de movimientos.

2.  **HU02: Cargar Stock Masivamente**
    * **Como** usuario,
    * **quiero** importar una lista de productos desde un archivo Excel,
    * **para** agilizar la carga inicial o la recepción de grandes pedidos.
    * **Criterios de Aceptación:**
        * El sistema debe ofrecer una plantilla Excel descargable con el formato correcto.
        * La importación debe validar que el depósito especificado en el archivo exista en el sistema.
        * Cada producto importado debe generar un registro individual en el historial de movimientos.

3.  **HU03: Generar Reporte de Rentabilidad**
    * **Como** administrador,
    * **quiero** generar un reporte que muestre la ganancia estimada por cada venta realizada,
    * **para** analizar qué productos son más rentables.
    * **Criterios de Aceptación:**
        * El reporte debe calcular la ganancia restando el costo estimado (basado en el `precio_compra` del stock) del `precio_venta`.
        * El reporte debe poder exportarse en formatos Excel y PDF.

4.  **HU04: Administrar Accesos de Usuario**
    * **Como** administrador,
    * **quiero** crear y resetear las contraseñas de los usuarios desde un panel central,
    * **para** gestionar los accesos al sistema de forma segura.
    * **Criterios de Aceptación:**
        * La creación de un usuario solo requiere su DNI; la contraseña inicial es el mismo DNI.
        * Al resetear una contraseña, el sistema debe forzar al usuario a cambiarla en su próximo inicio de sesión.

---

## **Casos de Uso**

1.  **CU01: Procesar Ciclo de Venta**
    * **Actor:** Usuario
    * **Descripción:** El usuario accede a la sección "Ventas", crea una nueva venta, selecciona un producto del listado de stock disponible y define la cantidad. El sistema valida la disponibilidad, confirma la venta, actualiza el stock y registra el movimiento. Posteriormente, el usuario puede editar o eliminar la venta, y el sistema ajustará el stock correspondientemente.
2.  **CU02: Auditar Movimientos de un Producto**
    * **Actor:** Administrador
    * **Descripción:** El administrador accede a "Reportes", abre el generador de reportes a medida y selecciona "Historial de un Producto". Elige un producto específico del menú desplegable y genera un reporte exportable (PDF/Excel) que muestra cronológicamente todas las operaciones (ingresos de stock, ventas, ediciones) relacionadas con ese producto.
3.  **CU03: Gestionar Contraseña Olvidada**
    * **Actor:** Usuario, Administrador
    * **Descripción:** Un usuario que olvidó su contraseña hace clic en el enlace correspondiente en la página de login. Ingresa su DNI. El sistema valida el DNI y genera una notificación interna dirigida al administrador. El administrador ve la notificación en su barra de navegación, accede al panel de usuarios y resetea la contraseña del usuario afectado.

---

## **Requisitos Funcionales (RF) y No Funcionales (RNF)**

### **Requisitos Funcionales**
* **RF01:** El sistema **debe** descontar la cantidad vendida del stock del producto correspondiente inmediatamente después de confirmar una venta.
* **RF02:** El sistema **debe permitir** la importación masiva de stocks y depósitos desde archivos con formato .xlsx.
* **RF03:** El sistema **debe generar** un reporte de "Valor de Inventario por Depósito" que totalice el valor del stock agrupado por cada depósito y moneda, y permita su exportación.
* **RF04:** El sistema **debe registrar** cada operación de creación, edición o eliminación de stocks, ventas y depósitos en un historial de movimientos auditable.

### **Requisitos No Funcionales**
* **RNF01 (Seguridad):** Todas las contraseñas de usuario **deben ser** almacenadas en la base de datos de forma cifrada (hashed) utilizando Bcrypt.
* **RNF02 (Usabilidad):** La aplicación **debe ser** responsiva y garantizar una experiencia de usuario fluida tanto en dispositivos de escritorio como en móviles.
* **RNF03 (Rendimiento):** Las consultas a la base de datos para cargar las páginas principales (Stocks, Ventas) **no deben tardar** más de 3 segundos, incluso con más de 1,000 registros.
* **RNF04 (Seguridad):** El sistema **debe cerrar automáticamente** la sesión de un usuario después de 15 minutos de inactividad.

---

## 🛠️ Tecnologías Utilizadas

- **Backend**: Flask, Flask-SQLAlchemy, Flask-Login, Flask-Bcrypt
- **Base de datos**: SQLite3
- **Frontend**: HTML5, CSS3, Bootstrap 5
- **Reportes y Datos**: Pandas, Openpyxl, Reportlab
- **Servidor WSGI**: Gunicorn
- **PWA (Progressive Web App)**: `manifest.json` + `service-worker.js`.

---

## 🚀 Cómo Ejecutar el Proyecto Localmente

1.  **Clonar el repositorio:**
    ```bash
    git clone [https://github.com/DaniCardozo2023/El-Silo-Proyect](https://github.com/DaniCardozo2023/El-Silo-Proyect)
    cd EL-SILO-PROYECT
    ```

2.  **Instalar dependencias:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Ejecutar la app:**
    ```bash
    python app.py
    ```
    La primera vez se creará el usuario **administrador**:
    - **Usuario (DNI):** `admin`
    - **Contraseña:** `admin`

4.  **Abrir en el navegador:**
    `http://127.0.0.1:5000`

---

## 📚 Referencias Bibliográficas

-   [Flask Documentation](https://flask.palletsprojects.com/)
-   [Flask-SQLAlchemy Documentation](https://flask-sqlalchemy.palletsprojects.com/)
-   [Flask-Login Documentation](https://flask-login.readthedocs.io/)
-   [Pandas IO Tools](https://pandas.pydata.org/pandas-docs/stable/reference/io.html)
-   [ReportLab User Guide](https://www.reportlab.com/docs/reportlab-userguide.pdf)
-   [Bootstrap 5 Documentation](https://getbootstrap.com/docs/5.0/getting-started/introduction/)