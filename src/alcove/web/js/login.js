import { api, esc } from "./api.js";
import { signedIn } from "./main.js";

export async function renderLogin(app, setup) {
  if (!setup) {
    const status = await api("/status").catch(() => ({ setup_needed: false }));
    if (status.setup_needed) { location.hash = "#/setup"; return; }
  }
  app.innerHTML = `<main class="signin">
    <form class="signin-card" novalidate>
      <h1 class="brand brand-large">Alcove</h1>
      <p class="signin-lede">${setup
        ? "Create the admin account. You’ll use it to add people and look after the library."
        : "Sign in to your library."}</p>
      <label>Name<input name="username" autocomplete="username" required autofocus></label>
      <label>Password<input name="password" type="password" autocomplete="${setup ? "new-password" : "current-password"}" required></label>
      <p class="form-error" role="alert" hidden></p>
      <button class="btn btn-primary" type="submit">${setup ? "Create admin account" : "Sign in"}</button>
    </form>
  </main>`;
  const form = app.querySelector("form");
  const error = form.querySelector(".form-error");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    error.hidden = true;
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      const user = await api(setup ? "/setup" : "/login", {
        method: "POST", body: { username: form.username.value, password: form.password.value },
      });
      signedIn({ id: user.id, username: user.username, admin: user.admin });
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
      button.disabled = false;
    }
  });
}
