"use strict";

/* ===================== utilidades ===================== */

const $ = (selector) => document.querySelector(selector);

/** Crea un elemento. Los textos se insertan como texto (nunca como HTML). */
function el(etiqueta, props = {}, ...hijos) {
  const nodo = document.createElement(etiqueta);
  for (const [clave, valor] of Object.entries(props)) {
    if (valor === false || valor == null) continue;
    if (clave === "class") nodo.className = valor;
    else if (clave.startsWith("on")) nodo.addEventListener(clave.slice(2), valor);
    else nodo.setAttribute(clave, valor === true ? "" : valor);
  }
  for (const hijo of hijos.flat()) {
    if (hijo == null || hijo === false) continue;
    nodo.append(hijo.nodeType ? hijo : document.createTextNode(hijo));
  }
  return nodo;
}

const SVG_NS = "http://www.w3.org/2000/svg";

/** Icono del sprite de index.html (<symbol id="i-nombre">). */
function icono(nombre, clase = "ico") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", clase);
  svg.setAttribute("aria-hidden", "true");
  const uso = document.createElementNS(SVG_NS, "use");
  uso.setAttribute("href", `#i-${nombre}`);
  svg.append(uso);
  return svg;
}

function textoError(datos, status) {
  const detalle = datos && datos.detail;
  if (typeof detalle === "string") return detalle;
  if (Array.isArray(detalle)) return detalle.map((e) => e.msg).join("; ");
  return `Error del servidor (${status}).`;
}

async function api(ruta, opciones) {
  let respuesta;
  try {
    respuesta = await fetch(ruta, opciones);
  } catch {
    throw new Error("No se pudo conectar con el servidor. Revisa tu conexión.");
  }
  if (respuesta.status === 401) {
    window.location.href = "/login";
    throw new Error("Tu sesión terminó. Inicia sesión de nuevo.");
  }
  if (!respuesta.ok) {
    let datos = null;
    try { datos = await respuesta.json(); } catch { /* sin cuerpo JSON */ }
    throw new Error(textoError(datos, respuesta.status));
  }
  return respuesta.status === 204 ? null : respuesta.json();
}

function formatearBytes(bytes) {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function formatearFecha(iso) {
  return new Date(iso).toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" });
}

function avisar(texto, tipo = "ok") {
  const aviso = el("div", { class: `aviso ${tipo}` },
    icono(tipo === "ok" ? "check" : "alert"),
    el("span", {}, texto),
    el("button", { type: "button", "aria-label": "Cerrar aviso", onclick: () => aviso.remove() }, "×"));
  $("#avisos").prepend(aviso);
  if (tipo === "ok") setTimeout(() => aviso.remove(), 8000);
}

/* ===================== estado ===================== */

const contextoVacio = () => ({ nombre: "", descripcion: "", participantes: [], palabras_clave: [], notas: "" });
const clonar = (obj) => JSON.parse(JSON.stringify(obj));

const estado = {
  config: { formatos: [], max_subida_mb: 2048 },
  plantillas: [],
  modo: "",              // "" | "plantilla" | "nuevo" | "ninguno"
  plantillaId: null,
  ctx: contextoVacio(),
  base: "",              // contexto al elegirlo (para detectar cambios)
  archivo: null,
  trabajos: [],
  subiendo: false,
  yo: null,              // usuario con sesión iniciada
  editable: false,       // si el usuario actual puede modificar la plantilla elegida
};

/** Contexto listo para enviar: sin filas vacías ni espacios sobrantes. */
function contextoLimpio() {
  const c = estado.ctx;
  return {
    nombre: c.nombre.trim(),
    descripcion: c.descripcion.trim(),
    participantes: c.participantes
      .filter((p) => p.nombre.trim())
      .map((p) => ({ ...p, nombre: p.nombre.trim(), cargo: p.cargo.trim() })),
    palabras_clave: c.palabras_clave,
    notas: c.notas.trim(),
  };
}

const hayCambios = () => JSON.stringify(contextoLimpio()) !== estado.base;

/** Marca con una palomita los pasos ya resueltos (archivo elegido, contexto elegido). */
function actualizarPasos() {
  $("#paso-1").classList.toggle("completo", Boolean(estado.archivo));
  $("#paso-2").classList.toggle("completo", Boolean(estado.modo));
  $("#paso-3").classList.toggle("completo", Boolean(estado.archivo && estado.modo));
}

/* ===================== archivo ===================== */

function elegirArchivo(archivo) {
  if (!archivo) return;
  const extension = "." + archivo.name.split(".").pop().toLowerCase();
  if (!estado.config.formatos.includes(extension)) {
    avisar(`El formato «${extension}» no es compatible. Usa un audio o video (${estado.config.formatos.join(", ")}).`, "error");
    return;
  }
  if (archivo.size > estado.config.max_subida_mb * 1024 * 1024) {
    avisar(`El archivo pesa ${formatearBytes(archivo.size)} y el máximo es ${estado.config.max_subida_mb} MB.`, "error");
    return;
  }
  estado.archivo = archivo;
  const esVideo = [".mp4", ".webm", ".mkv", ".mov", ".avi"].includes(extension);
  $("#archivo-icono").replaceChildren(icono(esVideo ? "video" : "music"));
  $("#archivo-nombre").textContent = archivo.name;
  $("#archivo-detalle").textContent = `${formatearBytes(archivo.size)} · ${esVideo ? "video" : "audio"}`;
  $("#zona").classList.add("con-archivo");
  $("#zona-vacia").hidden = true;
  $("#zona-archivo").hidden = false;
  actualizarPasos();
}

function iniciarZonaArchivo() {
  const zona = $("#zona");
  const entrada = $("#archivo");
  entrada.accept = estado.config.formatos.join(",");
  $("#max-mb").textContent = estado.config.max_subida_mb;
  $("#formatos").textContent = "Formatos: " + estado.config.formatos.map((f) => f.slice(1)).join(", ");

  entrada.addEventListener("change", () => elegirArchivo(entrada.files[0]));
  for (const nombre of ["dragenter", "dragover"]) {
    zona.addEventListener(nombre, (e) => { e.preventDefault(); zona.classList.add("arrastrando"); });
  }
  for (const nombre of ["dragleave", "drop"]) {
    zona.addEventListener(nombre, () => zona.classList.remove("arrastrando"));
  }
  zona.addEventListener("drop", (e) => {
    e.preventDefault();
    const archivo = e.dataTransfer.files[0];
    if (archivo) {
      try { entrada.files = e.dataTransfer.files; } catch { /* navegadores antiguos */ }
      elegirArchivo(archivo);
    }
  });
}

/* ===================== selector de contexto ===================== */

function renderSelector(valor = "") {
  const selector = $("#selector");
  const opciones = (ambito) => estado.plantillas.filter((p) => p.ambito === ambito)
    .map((p) => el("option", { value: `p:${p.id}` }, p.nombre));
  const institucionales = opciones("institucional");
  const personales = opciones("personal");
  selector.replaceChildren(
    el("option", { value: "" }, "Elige un tipo de reunión…"),
    institucionales.length > 0 && el("optgroup", { label: "Plantillas del INO" }, ...institucionales),
    personales.length > 0 && el("optgroup", { label: "Mis plantillas" }, ...personales),
    el("option", { value: "nuevo" }, "＋ Crear un contexto nuevo"),
    el("option", { value: "ninguno" }, "Sin contexto (menor precisión)"),
  );
  selector.value = valor;
}

function alElegirContexto() {
  const valor = $("#selector").value;
  estado.plantillaId = null;
  estado.editable = false;
  if (valor.startsWith("p:")) {
    const plantilla = estado.plantillas.find((p) => p.id === Number(valor.slice(2)));
    estado.modo = "plantilla";
    estado.plantillaId = plantilla.id;
    estado.editable = plantilla.editable;
    estado.ctx = clonar({
      nombre: plantilla.nombre, descripcion: plantilla.descripcion,
      participantes: plantilla.participantes, palabras_clave: plantilla.palabras_clave, notas: plantilla.notas,
    });
  } else if (valor === "nuevo") {
    estado.modo = "nuevo";
    estado.ctx = contextoVacio();
  } else {
    estado.modo = valor === "ninguno" ? "ninguno" : "";
    estado.ctx = contextoVacio();
  }
  estado.base = JSON.stringify(contextoLimpio());
  renderEditor(true);
  actualizarPasos();
}

/* ===================== editor de contexto ===================== */

function renderEditor(restablecerPaneles = false) {
  const visible = estado.modo === "plantilla" || estado.modo === "nuevo";
  $("#editor").hidden = !visible;
  if (!visible) return;

  $("#c-nombre").value = estado.ctx.nombre;
  $("#c-descripcion").value = estado.ctx.descripcion;
  $("#c-notas").value = estado.ctx.notas;
  renderParticipantes();
  renderChips();

  if (restablecerPaneles) {
    $("#det-participantes").open = estado.modo === "nuevo" || estado.ctx.participantes.length <= 8;
    $("#det-claves").open = estado.modo === "nuevo";
    $("#det-notas").open = false;
  }
  actualizarAcciones();
}

function actualizarAcciones() {
  const esPlantilla = estado.modo === "plantilla";
  const cambios = hayCambios();
  const puedeEditar = esPlantilla && estado.editable;
  $("#btn-guardar").hidden = !puedeEditar;
  $("#btn-guardar").disabled = !cambios || estado.ctx.nombre.trim() === "";
  $("#btn-eliminar-plantilla").hidden = !puedeEditar;
  $("#lbl-institucional").hidden = !(estado.yo && estado.yo.es_admin);
  $("#btn-guardar-nueva").disabled = estado.ctx.nombre.trim() === "";

  const texto = $("#estado-contexto");
  texto.classList.toggle("modificado", esPlantilla && cambios);
  if (esPlantilla && !estado.editable) {
    texto.textContent = cambios
      ? "Hiciste cambios solo para esta reunión. Para conservarlos, guárdalos como plantilla nueva (será tuya)."
      : "Plantilla del INO. Puedes ajustarla para esta reunión sin modificar la original.";
  } else if (esPlantilla) {
    texto.textContent = cambios
      ? "Hiciste cambios. Se usarán en esta reunión; la plantilla guardada no cambia hasta que la actualices."
      : "Usando la plantilla tal como está guardada. Puedes ajustarla para esta reunión.";
  } else {
    texto.textContent = "Contexto nuevo. Guárdalo como plantilla si lo vas a reutilizar.";
  }
  $("#cnt-participantes").textContent = `(${estado.ctx.participantes.filter((p) => p.nombre.trim()).length})`;
  $("#cnt-claves").textContent = `(${estado.ctx.palabras_clave.length})`;
}

function renderParticipantes() {
  const filas = estado.ctx.participantes.map((p, i) => el("tr", {},
    el("td", {}, el("input", {
      type: "text", value: p.nombre, "aria-label": `Nombre del participante ${i + 1}`, autocomplete: "off",
      oninput: (e) => { p.nombre = e.target.value; actualizarAcciones(); },
    })),
    el("td", {}, el("input", {
      type: "text", value: p.cargo, "aria-label": `Cargo del participante ${i + 1}`, autocomplete: "off",
      oninput: (e) => { p.cargo = e.target.value; actualizarAcciones(); },
    })),
    el("td", {}, el("input", {
      type: "checkbox", checked: p.asiste, "aria-label": `${p.nombre || "Participante " + (i + 1)} asiste a la reunión`,
      onchange: (e) => { p.asiste = e.target.checked; actualizarAcciones(); },
    })),
    el("td", {}, el("button", {
      type: "button", class: "btn chico", "aria-label": `Quitar a ${p.nombre || "participante " + (i + 1)}`,
      onclick: () => { estado.ctx.participantes.splice(i, 1); renderParticipantes(); actualizarAcciones(); },
    }, "✕")),
  ));
  $("#lista-participantes").replaceChildren(...filas);
}

function renderChips() {
  $("#chips").replaceChildren(...estado.ctx.palabras_clave.map((palabra, i) =>
    el("span", { class: "chip" }, palabra,
      el("button", {
        type: "button", "aria-label": `Quitar la palabra ${palabra}`,
        onclick: () => { estado.ctx.palabras_clave.splice(i, 1); renderChips(); actualizarAcciones(); },
      }, "×"))));
}

function agregarPalabras(texto) {
  const existentes = new Set(estado.ctx.palabras_clave.map((k) => k.toLowerCase()));
  for (const palabra of texto.split(/[,;\n]+/).map((k) => k.trim()).filter(Boolean)) {
    if (!existentes.has(palabra.toLowerCase())) {
      existentes.add(palabra.toLowerCase());
      estado.ctx.palabras_clave.push(palabra);
    }
  }
  renderChips();
  actualizarAcciones();
}

function iniciarEditor() {
  $("#selector").addEventListener("change", alElegirContexto);
  $("#c-nombre").addEventListener("input", (e) => { estado.ctx.nombre = e.target.value; actualizarAcciones(); });
  $("#c-descripcion").addEventListener("input", (e) => { estado.ctx.descripcion = e.target.value; actualizarAcciones(); });
  $("#c-notas").addEventListener("input", (e) => { estado.ctx.notas = e.target.value; actualizarAcciones(); });

  $("#btn-add-participante").addEventListener("click", () => {
    estado.ctx.participantes.push({ nombre: "", cargo: "", asiste: true, nota: "" });
    renderParticipantes();
    actualizarAcciones();
    const campos = document.querySelectorAll("#lista-participantes tr:last-child input[type=text]");
    if (campos[0]) campos[0].focus();
  });

  const entrada = $("#c-clave");
  entrada.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      agregarPalabras(entrada.value);
      entrada.value = "";
    } else if (e.key === "Backspace" && entrada.value === "" && estado.ctx.palabras_clave.length) {
      estado.ctx.palabras_clave.pop();
      renderChips();
      actualizarAcciones();
    }
  });
  entrada.addEventListener("paste", (e) => {
    const pegado = (e.clipboardData || window.clipboardData).getData("text");
    if (/[,;\n]/.test(pegado)) {
      e.preventDefault();
      agregarPalabras(pegado);
    }
  });
  entrada.addEventListener("blur", () => {
    if (entrada.value.trim()) { agregarPalabras(entrada.value); entrada.value = ""; }
  });

  $("#btn-guardar").addEventListener("click", guardarPlantilla);
  $("#btn-guardar-nueva").addEventListener("click", guardarComoNueva);
  $("#btn-eliminar-plantilla").addEventListener("click", eliminarPlantilla);
}

/* ===================== plantillas ===================== */

async function cargarPlantillas() {
  estado.plantillas = await api("/api/contextos");
}

async function guardarPlantilla() {
  try {
    const guardada = await api(`/api/contextos/${estado.plantillaId}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(contextoLimpio()),
    });
    await cargarPlantillas();
    renderSelector(`p:${guardada.id}`);
    estado.ctx = clonar(contextoLimpio());
    estado.base = JSON.stringify(contextoLimpio());
    renderEditor();
    avisar(`Plantilla «${guardada.nombre}» actualizada.`);
  } catch (e) { avisar(e.message, "error"); }
}

async function guardarComoNueva() {
  try {
    const compartir = estado.yo && estado.yo.es_admin && $("#chk-institucional").checked;
    const nueva = await api(`/api/contextos${compartir ? "?institucional=true" : ""}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(contextoLimpio()),
    });
    await cargarPlantillas();
    renderSelector(`p:${nueva.id}`);
    alElegirContexto();
    avisar(`Plantilla «${nueva.nombre}» guardada.`);
  } catch (e) {
    avisar(e.message.includes("Ya existe") ? `${e.message} Cambia el nombre para guardarla como nueva.` : e.message, "error");
  }
}

let confirmaEliminarPlantilla = null;
async function eliminarPlantilla() {
  const boton = $("#btn-eliminar-plantilla");
  if (!confirmaEliminarPlantilla) {
    boton.textContent = "¿Seguro? Pulsa de nuevo";
    boton.classList.add("confirmar");
    confirmaEliminarPlantilla = setTimeout(restablecerBotonEliminar, 4000);
    return;
  }
  restablecerBotonEliminar();
  try {
    const nombre = estado.ctx.nombre;
    await api(`/api/contextos/${estado.plantillaId}`, { method: "DELETE" });
    await cargarPlantillas();
    renderSelector("");
    alElegirContexto();
    avisar(`Plantilla «${nombre}» eliminada.`);
  } catch (e) { avisar(e.message, "error"); }
}

function restablecerBotonEliminar() {
  clearTimeout(confirmaEliminarPlantilla);
  confirmaEliminarPlantilla = null;
  const boton = $("#btn-eliminar-plantilla");
  boton.textContent = "Eliminar plantilla";
  boton.classList.remove("confirmar");
}

/* ===================== cuenta ===================== */

function iniciales(nombre) {
  const partes = nombre.trim().split(/\s+/).filter(Boolean);
  if (partes.length === 0) return "?";
  return (partes[0][0] + (partes.length > 1 ? partes[partes.length - 1][0] : "")).toUpperCase();
}

function mostrarCuenta(usuario) {
  $("#avatar").textContent = iniciales(usuario.nombre);
  $("#usuario-nombre").textContent = usuario.nombre;
  $("#menu-nombre").textContent = usuario.nombre;
  $("#menu-rol").textContent = `${usuario.usuario} · ${usuario.es_admin ? "Administrador" : "Usuario"}`;
  $("#cuenta").hidden = false;
}

function iniciarCuenta() {
  const dialogo = $("#dlg-clave");
  const error = $("#error-clave");
  const menu = $("#menu-cuenta");
  const mostrarError = (texto) => { error.textContent = texto; error.hidden = false; };

  // Los menús desplegables se cierran al hacer clic fuera o con Escape
  document.addEventListener("click", (e) => {
    document.querySelectorAll("details.menu[open], details.mas[open]").forEach((d) => {
      if (!d.contains(e.target)) d.open = false;
    });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") document.querySelectorAll("details.menu[open], details.mas[open]").forEach((d) => { d.open = false; });
  });

  $("#btn-salir").addEventListener("click", async () => {
    try { await fetch("/api/logout", { method: "POST" }); } catch { /* se sale igual */ }
    window.location.href = "/login";
  });

  $("#btn-clave").addEventListener("click", () => {
    menu.open = false;
    $("#form-clave").reset();
    error.hidden = true;
    dialogo.showModal();
    $("#clave-actual").focus();
  });
  $("#clave-cancelar").addEventListener("click", () => dialogo.close());

  $("#form-clave").addEventListener("submit", async (e) => {
    e.preventDefault();
    error.hidden = true;
    const nueva = $("#clave-nueva").value;
    if (nueva.length < 10) return mostrarError("La contraseña nueva debe tener al menos 10 caracteres.");
    if (nueva !== $("#clave-repetir").value) return mostrarError("Las contraseñas nuevas no coinciden.");
    try {
      await api("/api/cuenta/clave", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actual: $("#clave-actual").value, nueva }),
      });
      dialogo.close();
      avisar("Contraseña actualizada. Se cerró tu sesión en otros dispositivos.");
    } catch (err) { mostrarError(err.message); }
  });
}

/* ===================== opciones de resultado ===================== */

function fechaDeHoy() {
  const hoy = new Date();
  const dos = (n) => String(n).padStart(2, "0");
  return `${hoy.getFullYear()}-${dos(hoy.getMonth() + 1)}-${dos(hoy.getDate())}`;
}

function iniciarOpcionesActa() {
  const acta = $("#generar-acta");
  const soloTranscribir = $("#sin-analisis");
  $("#acta-fecha").value = fechaDeHoy();

  let actaAntes = acta.checked;   // para restaurarla al desmarcar «solo transcribir»

  const sincronizar = () => {
    $("#datos-acta").hidden = !acta.checked;
    acta.disabled = soloTranscribir.checked;
  };
  acta.addEventListener("change", sincronizar);
  soloTranscribir.addEventListener("change", () => {
    if (soloTranscribir.checked) {
      actaAntes = acta.checked;
      acta.checked = false;
    } else {
      acta.checked = actaAntes;
    }
    sincronizar();
  });
  sincronizar();
}

/* ===================== envío ===================== */

function validarEnvio() {
  if (!estado.archivo) return "Primero elige el archivo de la reunión.";
  if (!estado.modo) return "Elige el tipo de reunión (o «Sin contexto») antes de continuar.";
  if (estado.modo !== "ninguno" && !estado.ctx.nombre.trim()) return "El contexto necesita un nombre.";
  if ($("#generar-acta").checked && !$("#acta-fecha").value) return "Indica la fecha de la reunión para redactar el acta.";
  return null;
}

function subirArchivo(datos, alProgreso) {
  return new Promise((resolver, rechazar) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/trabajos");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) alProgreso(e.loaded, e.total); };
    xhr.onload = () => {
      let cuerpo = null;
      try { cuerpo = JSON.parse(xhr.responseText); } catch { /* sin JSON */ }
      if (xhr.status === 401) window.location.href = "/login";
      if (xhr.status >= 200 && xhr.status < 300) resolver(cuerpo);
      else rechazar(new Error(textoError(cuerpo, xhr.status)));
    };
    xhr.onerror = () => rechazar(new Error("Se interrumpió la subida. Revisa tu conexión e inténtalo de nuevo."));
    xhr.send(datos);
  });
}

function mostrarSubida(fraccion, texto) {
  const barra = document.querySelector("#subida .barra");
  const porcentaje = Math.round(fraccion * 100);
  $("#subida").hidden = false;
  $("#subida-barra").style.width = `${porcentaje}%`;
  barra.setAttribute("aria-valuenow", String(porcentaje));
  $("#subida-texto").textContent = texto;
}

async function enviar(evento) {
  evento.preventDefault();
  if (estado.subiendo) return;
  const problema = validarEnvio();
  if (problema) { avisar(problema, "error"); return; }

  const datos = new FormData();
  datos.append("archivo", estado.archivo);
  if (estado.modo === "ninguno") datos.append("sin_contexto", "true");
  else datos.append("contexto", JSON.stringify(contextoLimpio()));
  if ($("#sin-analisis").checked) datos.append("sin_analisis", "true");
  if ($("#generar-acta").checked) {
    datos.append("generar_acta", "true");
    datos.append("acta_numero", $("#acta-numero").value.trim());
    datos.append("acta_fecha", $("#acta-fecha").value);
    datos.append("acta_hora", $("#acta-hora").value.trim());
  }

  estado.subiendo = true;
  const boton = $("#btn-enviar");
  boton.disabled = true;
  $("#btn-enviar-texto").textContent = "Subiendo…";
  try {
    await subirArchivo(datos, (cargado, total) => {
      mostrarSubida(cargado / total, cargado < total
        ? `Subiendo… ${Math.round((cargado / total) * 100)} % (${formatearBytes(cargado)} de ${formatearBytes(total)})`
        : "Guardando el archivo en el servidor…");
    });
    avisar("Archivo recibido. Puedes seguir el avance abajo, en «Mis transcripciones».");
    reiniciarArchivo();
    await cargarTrabajos();
    // En pantallas anchas el historial ya está a la vista; en las estrechas queda debajo
    if (window.matchMedia("(max-width: 999px)").matches) {
      $("#t-historial").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (e) {
    avisar(e.message, "error");
  } finally {
    estado.subiendo = false;
    boton.disabled = false;
    $("#btn-enviar-texto").textContent = "Procesar reunión";
    $("#subida").hidden = true;
  }
}

function reiniciarArchivo() {
  estado.archivo = null;
  $("#archivo").value = "";
  $("#zona").classList.remove("con-archivo");
  $("#zona-vacia").hidden = false;
  $("#zona-archivo").hidden = true;
  actualizarPasos();
}

/* ===================== historial ===================== */

const ETIQUETAS_ESTADO = { en_cola: "En cola", procesando: "Procesando", completado: "Listo", error: "Con error" };
const ETIQUETAS_ARCHIVO = {
  "acta.docx": "Acta (.docx)",
  "informe.md": "Informe (.md)",
  "transcripcion.txt": "Transcripción (.txt)",
  "transcripcion_tiempos.txt": "Con tiempos (.txt)",
  "datos.json": "Datos (.json)",
};

const esActivo = (t) => t.estado === "en_cola" || t.estado === "procesando";
const confirmandoEliminar = new Set();
const estadosPrevios = new Map();

const ICONO_ESTADO = { en_cola: "clock", procesando: "loader", completado: "check", error: "alert" };

/** Inserta puntos de corte tras _ . - para que un nombre largo se parta en lugares naturales. */
const nombreLegible = (nombre) => nombre.replace(/([_.\-])/g, "$1​");

const dato = (nombreIcono, texto) => el("span", {}, icono(nombreIcono), texto);

function tarjetaTrabajo(t) {
  const porcentaje = Math.round(t.progreso * 100);
  const confirmando = confirmandoEliminar.has(t.id);
  const otras = t.archivos.filter((n) => n !== "acta.docx");

  return el("li", { class: `trabajo ${t.estado}` },
    el("div", { class: "trabajo-icono" },
      icono(ICONO_ESTADO[t.estado], t.estado === "procesando" ? "ico girando" : "ico")),
    el("div", { class: "trabajo-cuerpo" },
      el("div", { class: "trabajo-cab" },
        el("span", { class: "trabajo-nombre" }, nombreLegible(t.archivo)),
        el("span", { class: `insignia ${t.estado}` }, ETIQUETAS_ESTADO[t.estado])),
      el("div", { class: "meta" },
        dato("clock", formatearFecha(t.creado)),
        dato("users", t.contexto ? t.contexto.nombre : "Sin contexto"),
        t.duracion ? dato("mic", `${Math.max(1, Math.round(t.duracion / 60))} min de audio`) : null,
        t.acta ? dato("file", `Acta${t.acta.numero ? " " + t.acta.numero : ""}`) : null,
        t.sin_analisis ? dato("mic", "Solo transcripción") : null),
      esActivo(t) && el("div", { class: "barra", role: "progressbar", "aria-label": `Avance de ${t.archivo}`,
        "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(porcentaje) },
        el("span", { style: `width:${porcentaje}%` })),
      esActivo(t) && el("p", { class: "trabajo-msg" }, `${t.mensaje || ""} — ${porcentaje} %`),
      t.estado === "error" && el("p", { class: "trabajo-msg error" }, t.error),
      ...t.advertencias.map((a) => el("p", { class: "trabajo-msg aviso-t" }, `Aviso: ${a}`)),
      el("div", { class: "acciones-trabajo" },
        t.archivos.includes("informe.md") &&
          el("button", { type: "button", class: "btn chico", onclick: () => verInforme(t) },
            icono("eye"), "Ver informe"),
        t.archivos.includes("acta.docx") && el("a", {
          class: "btn chico destacado", href: `/api/trabajos/${t.id}/archivos/acta.docx`, download: "",
        }, icono("download"), "Acta (.docx)"),
        otras.length > 0 && el("details", { class: "mas" },
          el("summary", { class: "btn chico" }, "Más descargas", icono("chevron", "ico chevron")),
          el("div", { class: "mas-panel" }, ...otras.map((nombre) => el("a", {
            href: `/api/trabajos/${t.id}/archivos/${nombre}`, download: "",
          }, icono("download"), ETIQUETAS_ARCHIVO[nombre])))),
        el("span", { class: "separador" }),
        t.estado !== "procesando" && el("button", {
          type: "button", class: `btn chico peligro${confirmando ? " confirmar" : " icono-solo"}`,
          title: "Eliminar", "aria-label": `Eliminar ${t.archivo}`, onclick: () => eliminarTrabajo(t),
        }, icono("trash"), confirmando ? "¿Seguro? Pulsa de nuevo" : null))));
}

function renderTrabajos() {
  $("#historial-vacio").hidden = estado.trabajos.length > 0;
  const contador = $("#cnt-trabajos");
  contador.hidden = estado.trabajos.length === 0;
  contador.textContent = String(estado.trabajos.length);
  $("#trabajos").replaceChildren(...estado.trabajos.map(tarjetaTrabajo));
}

function notificarCambios() {
  for (const t of estado.trabajos) {
    const previo = estadosPrevios.get(t.id);
    if (previo && (previo === "en_cola" || previo === "procesando")) {
      if (t.estado === "completado") avisar(`«${t.archivo}» está listo.`);
      if (t.estado === "error") avisar(`«${t.archivo}» no se pudo procesar. ${t.error || ""}`, "error");
    }
    estadosPrevios.set(t.id, t.estado);
  }
}

let temporizador = null;
let sinConexion = false;

async function cargarTrabajos() {
  clearTimeout(temporizador);
  try {
    estado.trabajos = await api("/api/trabajos");
    if (sinConexion) { sinConexion = false; avisar("Conexión recuperada."); }
    notificarCambios();
    renderTrabajos();
  } catch (e) {
    if (!sinConexion) { sinConexion = true; avisar("Se perdió la conexión con el servidor. Reintentando…", "error"); }
  }
  if (sinConexion) temporizador = setTimeout(cargarTrabajos, 5000);
  else if (estado.trabajos.some(esActivo)) temporizador = setTimeout(cargarTrabajos, 2000);
}

async function eliminarTrabajo(t) {
  if (!confirmandoEliminar.has(t.id)) {
    confirmandoEliminar.add(t.id);
    renderTrabajos();
    setTimeout(() => { confirmandoEliminar.delete(t.id); renderTrabajos(); }, 4000);
    return;
  }
  confirmandoEliminar.delete(t.id);
  try {
    await api(`/api/trabajos/${t.id}`, { method: "DELETE" });
    estadosPrevios.delete(t.id);
    await cargarTrabajos();
  } catch (e) { avisar(e.message, "error"); await cargarTrabajos(); }
}

async function verInforme(t) {
  try {
    const respuesta = await fetch(`/api/trabajos/${t.id}/archivos/informe.md`);
    if (!respuesta.ok) throw new Error("No se pudo abrir el informe.");
    $("#visor-titulo").textContent = `Informe: ${t.archivo}`;
    $("#visor-texto").textContent = await respuesta.text();
    $("#visor").showModal();
  } catch (e) { avisar(e.message, "error"); }
}

/* ===================== arranque ===================== */

async function iniciar() {
  $("#form").addEventListener("submit", enviar);
  $("#visor-cerrar").addEventListener("click", () => $("#visor").close());
  iniciarOpcionesActa();
  iniciarEditor();
  iniciarCuenta();
  try {
    estado.yo = await api("/api/yo");
    mostrarCuenta(estado.yo);
    [estado.config] = await Promise.all([api("/api/config"), cargarPlantillas()]);
    // Solo se promete borrar el audio si el servidor está configurado para hacerlo
    $("#nota-privacidad").hidden = estado.config.conservar_audio !== false;
  } catch (e) {
    avisar(e.message, "error");
  }
  iniciarZonaArchivo();
  renderSelector("");
  actualizarPasos();
  await cargarTrabajos();
}

iniciar();
