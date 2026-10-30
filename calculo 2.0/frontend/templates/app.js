/* app.js — Lógica de la interfaz de PoliClima: sube archivos, aplica filtros, pide datos al servidor y los muestra. */

// ── 1. UTILIDADES ───────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);                     // atajo para buscar un elemento por su id
const TURQUESA = "#14a3c7", NARANJA = "#f59e0b";                   // turquesa = dato medido, naranja = dato estimado
let grafica;                                                       // la gráfica actual (para poder reemplazarla)
let rango = null;                                                  // primera y última fecha del archivo cargado

// Escribe un número con coma decimal, como en Colombia (13,9)
const formato = (n, decimales = 1) =>
  n == null ? "–" : Number(n).toLocaleString("es-CO", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });

// Anima un número desde su valor anterior hasta el nuevo (efecto de conteo suave)
const anteriores = {};
function animarNumero(id, destino, decimales = 1) {
  const el = $(id);
  if (destino == null) { el.textContent = "–"; anteriores[id] = 0; return; }
  const inicio = anteriores[id] || 0, t0 = performance.now(), duracion = 800;
  (function paso(t) {
    const p = Math.min((t - t0) / duracion, 1);
    const suave = 1 - Math.pow(1 - p, 3);                          // desacelera al final
    el.textContent = formato(inicio + (destino - inicio) * suave, decimales);
    if (p < 1) requestAnimationFrame(paso);
  })(t0);
  anteriores[id] = destino;
}

// Convierte una fecha en texto AAAA-MM-DD (el formato que entienden los campos de fecha)
const aTexto = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

// ── 2. FILTROS ──────────────────────────────────────────────────────────────
// Llena las listas de horas (00:00 a 23:00)
for (let h = 0; h < 24; h++) {
  const hora = `${String(h).padStart(2, "0")}:00`;
  $("h-desde").add(new Option(hora, h));
  $("h-hasta").add(new Option(`${String(h).padStart(2, "0")}:59`, h));
}
$("h-hasta").value = 23;

// Junta los filtros elegidos en un texto para enviarlos al servidor
function parametros() {
  const p = new URLSearchParams();
  if ($("desde").value) p.set("desde", $("desde").value);
  if ($("hasta").value) p.set("hasta", $("hasta").value);
  p.set("hora_desde", $("h-desde").value);
  p.set("hora_hasta", $("h-hasta").value);
  return p;
}

// Cada cambio en un filtro recalcula todo (con una pausa corta para no pedir datos de más)
let espera;
function alCambiarFiltro() { clearTimeout(espera); espera = setTimeout(actualizarTodo, 250); }
["desde", "hasta", "h-desde", "h-hasta"].forEach((id) => $(id).addEventListener("change", alCambiarFiltro));

// Botón «Quitar filtros»: vuelve al rango completo y a todas las horas
$("quitar").addEventListener("click", () => {
  if (!rango) return;
  $("desde").value = rango.desde; $("hasta").value = rango.hasta;
  $("h-desde").value = 0; $("h-hasta").value = 23;
  alCambiarFiltro();
});

// Botones «Últimos 7 / 30 días»: terminan en la última fecha del archivo
document.querySelectorAll(".rapido").forEach((b) => b.addEventListener("click", () => {
  if (!rango) return;
  const fin = new Date(rango.hasta + "T00:00:00");
  const ini = new Date(fin); ini.setDate(ini.getDate() - (Number(b.dataset.dias) - 1));
  $("desde").value = aTexto(ini) < rango.desde ? rango.desde : aTexto(ini);
  $("hasta").value = rango.hasta;
  alCambiarFiltro();
}));

// ── 3. RESUMEN: tarjetas, alertas, calidad y tabla ──────────────────────────
// Colores de las alertas según su nivel: 0 verde, 1 amarillo, 2 naranja, 3 rojo
const COLOR_ALERTA = [
  "bg-emerald-50 border-emerald-300 text-emerald-900", "bg-amber-50 border-amber-300 text-amber-900",
  "bg-orange-50 border-orange-300 text-orange-900", "bg-red-50 border-red-300 text-red-900",
];
const COLOR_PUNTO = ["bg-emerald-500", "bg-amber-500", "bg-orange-500", "bg-red-500"];

function mostrarAlertas(alertas) {
  $("alertas-fecha").textContent = alertas.length ? `· ${alertas[0].fecha}` : "";
  $("alertas").innerHTML = alertas.map((a) => `
    <article class="fundido rounded-xl border-2 p-4 ${COLOR_ALERTA[a.nivel]}">
      <div class="flex items-center gap-2">
        <span class="w-3 h-3 rounded-full ${COLOR_PUNTO[a.nivel]} ${a.nivel >= 2 ? "animate-pulse" : ""}"></span>
        <h3 class="font-bold">${a.titulo}</h3>
      </div>
      <p class="text-2xl font-extrabold mt-1">${a.etiqueta}</p>
      <p class="text-sm font-medium">${a.dato}</p>
      <p class="text-sm mt-1">${a.consejo}</p>
    </article>`).join("");
}

function mostrarTabla(filas) {
  $("tabla").innerHTML = filas.map((f) => `
    <tr class="border-t border-slate-100">
      <td class="py-2 pr-4 font-bold">${f.nombre} <span class="font-normal text-slate-500">(${f.unidad})</span></td>
      <td class="pr-4">${formato(f.minimo)} – ${formato(f.maximo)}</td>
      <td class="pr-4">${f.total != null ? formato(f.total) + " en total" : formato(f.media)}</td>
      <td class="pr-4">${f.faltantes} (${formato(f.porcentaje)} %)</td>
      <td class="text-slate-600">${f.tratamiento}</td>
    </tr>`).join("");
}

async function cargarResumen() {
  const r = await (await fetch("/api/resumen?" + parametros())).json();
  if (r.vacio) return;                                             // todavía no hay archivo

  // La primera vez con un archivo nuevo, los filtros se ajustan a sus fechas
  if (!rango) {
    rango = r.rango;
    ["desde", "hasta"].forEach((id) => { $(id).min = rango.desde; $(id).max = rango.hasta; });
    $("desde").value = rango.desde; $("hasta").value = rango.hasta;
  }
  $("archivo").textContent = `Archivo actual: ${r.archivo}`;
  $("periodo").textContent = `Datos del ${r.rango.desde.split("-").reverse().join("/")} al ${r.rango.hasta.split("-").reverse().join("/")}`;

  // El selector solo ofrece las variables que existen en el archivo
  const select = $("variable"), actual = select.value;
  select.innerHTML = r.variables.map((v) => `<option value="${v.id}">${v.nombre}</option>`).join("");
  if (r.variables.some((v) => v.id === actual)) select.value = actual;

  // Si los filtros no dejan ningún dato, se avisa y se limpian las tarjetas
  const aviso = $("aviso");
  if (r.sin_datos) {
    ["temp", "lluvia", "hum", "calidad", "c-orig", "c-final"].forEach((id) => animarNumero(id, null));
    $("alertas").innerHTML = ""; $("tabla").innerHTML = ""; $("filtro-info").textContent = "";
    aviso.textContent = r.mensaje;
    return false;
  }

  // Tarjetas, calidad y barra de completitud
  const i = r.informe, t = r.tarjetas;
  animarNumero("temp", t.temperatura); animarNumero("lluvia", t.precipitacion); animarNumero("hum", t.humedad, 0);
  animarNumero("calidad", t.calidad); animarNumero("c-orig", i.completitud_original); animarNumero("c-final", i.completitud_final);
  $("barra").style.width = i.completitud_final + "%";
  $("filtro-info").textContent = `Mostrando ${r.filtrado.registros.toLocaleString("es-CO")} registros del ${r.filtrado.desde.split("-").reverse().join("/")} al ${r.filtrado.hasta.split("-").reverse().join("/")}.`;

  // Mensaje claro sobre qué faltaba y qué se hizo
  let txt = "No hay datos faltantes en este rango.";
  if (i.faltantes > 0) {
    txt = `Faltaban ${i.faltantes} datos. Se interpolaron ${i.interpolados}.`;
    if (i.sin_resolver > 0) txt += ` ${i.sin_resolver} quedaron vacíos (huecos largos o lluvia, que no se estima).`;
  }
  aviso.textContent = txt;
  aviso.classList.remove("fundido"); void aviso.offsetWidth; aviso.classList.add("fundido");   // reinicia el fundido

  mostrarAlertas(r.alertas);
  mostrarTabla(r.tabla);
  return true;
}

// ── 4. GRÁFICA: línea o barras según la variable ────────────────────────────
async function cargarGrafica() {
  const v = $("variable").value;
  if (!v) return;
  const resp = await fetch(`/api/serie?variable=${v}&vista=${$("vista").value}&${parametros()}`);
  if (!resp.ok) { if (grafica) grafica.destroy(); grafica = null; return; }
  const d = await resp.json();
  $("titulo").textContent = d.titulo;

  const colores = d.interpolados.map((x) => (x ? NARANJA : TURQUESA));      // naranja = hay datos estimados
  if (grafica) grafica.destroy();
  grafica = new Chart($("grafica"), {
    type: d.tipo,
    data: {
      labels: d.etiquetas,
      datasets: [{
        data: d.valores,
        borderColor: TURQUESA,
        backgroundColor: d.tipo === "bar" ? colores : "#fff",
        pointBackgroundColor: colores,
        pointBorderColor: colores,
        pointRadius: d.interpolados.map((x) => (x ? 6 : 3)),                // los estimados se ven más grandes
        tension: 0.35,
      }],
    },
    options: {
      maintainAspectRatio: false,
      animation: { duration: 900, easing: "easeOutCubic" },                 // la gráfica se dibuja suavemente
      plugins: { legend: { display: false } },
      scales: { y: { title: { display: true, text: d.unidad } } },
    },
  });
}

async function actualizarTodo() {
  const hayDatos = await cargarResumen();
  if (hayDatos !== false) await cargarGrafica();
  else if (grafica) { grafica.destroy(); grafica = null; }
}

// ── 5. SUBIDA DE ARCHIVOS (botón y arrastrar-soltar) ────────────────────────
async function subirArchivo(archivo) {
  $("error").textContent = "";
  const datos = new FormData();
  datos.append("archivo", archivo);
  const resp = await fetch("/api/subir", { method: "POST", body: datos });
  const r = await resp.json();
  if (!resp.ok) { $("error").textContent = r.error; return; }             // muestra por qué no se pudo leer
  rango = null;                                                           // los filtros se ajustan al archivo nuevo
  actualizarTodo();
}

$("boton").addEventListener("click", () => $("entrada").click());
$("entrada").addEventListener("change", (e) => e.target.files[0] && subirArchivo(e.target.files[0]));

const zona = $("zona");
zona.addEventListener("dragover", (e) => { e.preventDefault(); zona.classList.add("bg-poli-claro", "scale-[1.01]"); });
zona.addEventListener("dragleave", () => zona.classList.remove("bg-poli-claro", "scale-[1.01]"));
zona.addEventListener("drop", (e) => {
  e.preventDefault();
  zona.classList.remove("bg-poli-claro", "scale-[1.01]");
  if (e.dataTransfer.files[0]) subirArchivo(e.dataTransfer.files[0]);
});

// Al cambiar la variable o la vista, solo se redibuja la gráfica
$("variable").addEventListener("change", cargarGrafica);
$("vista").addEventListener("change", cargarGrafica);

// ── 6. EXPLICACIÓN: los pasos aparecen al llegar a ellos ────────────────────
const observador = new IntersectionObserver((entradas) => {
  entradas.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("visible"); observador.unobserve(e.target); } });
}, { threshold: 0.2 });
document.querySelectorAll(".revelar").forEach((el, n) => { el.style.transitionDelay = `${(n % 2) * 0.12}s`; observador.observe(el); });

actualizarTodo();                                                         // al abrir la página, carga lo que ya haya
