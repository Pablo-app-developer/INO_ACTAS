"use strict";

const formulario = document.querySelector("#form-login");
const aviso = document.querySelector("#error-login");
const boton = document.querySelector("#btn-entrar");

function mostrarError(texto) {
  aviso.textContent = texto;
  aviso.hidden = false;
}

formulario.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  aviso.hidden = true;

  const usuario = document.querySelector("#usuario").value.trim();
  const clave = document.querySelector("#clave").value;
  if (!usuario || !clave) {
    mostrarError("Escribe tu usuario y tu contraseña.");
    return;
  }

  boton.disabled = true;
  boton.textContent = "Entrando…";
  try {
    const respuesta = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ usuario, clave }),
    });
    if (respuesta.ok) {
      window.location.href = "/";
      return;
    }
    let detalle = "";
    try { detalle = (await respuesta.json()).detail; } catch { /* sin cuerpo JSON */ }
    mostrarError(typeof detalle === "string" && detalle ? detalle : `No se pudo iniciar sesión (error ${respuesta.status}).`);
    document.querySelector("#clave").select();
  } catch {
    mostrarError("No se pudo conectar con el servidor. Revisa tu conexión.");
  }
  boton.disabled = false;
  boton.textContent = "Entrar";
});
