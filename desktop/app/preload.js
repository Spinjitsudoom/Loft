// What the desktop app offers the pages it shows, as window.AlcoveDesktop. Alcove's web app uses
// it the way it uses the Android app's bridge: to show and change the server.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("AlcoveDesktop", {
  /** Check `url` is an Alcove server, remember it and open it. Resolves to an error message, or null. */
  connect: (url) => ipcRenderer.invoke("alcove:connect", url),
  /** The server this app opens. */
  getServer: () => ipcRenderer.sendSync("alcove:get-server"),
  /** Back to the start screen to type another server address. */
  changeServer: () => ipcRenderer.send("alcove:change-server"),
});
