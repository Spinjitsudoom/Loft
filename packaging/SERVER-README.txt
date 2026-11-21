Loft server
===========

This folder is the whole Loft server: nothing else needs installing. Keep the folder together.

Start it
--------
  Windows:  start Loft Server (from the Start menu after the setup, or double-click
            "Loft Server.exe" in this folder). It runs in the background with an icon in the
            notification area, by the clock: click it to open Loft; right-click it for the address
            other devices use, Update, Start with Windows (on from the first start), the data
            folder, Restart and Quit. What the server says goes to %LOCALAPPDATA%\Loft\server.log.
            The first time, Windows may say it protected your PC: choose "More info", then
            "Run anyway"; and allow Loft through the firewall so other devices can reach it.
            loft-server.exe on its own runs the server in a console window instead.
  macOS:    in Terminal, go into this folder and run   ./loft-server
            The first time, macOS blocks programs downloaded from the internet that aren't from the
            App Store or a registered developer. Clear that once with
                xattr -dr com.apple.quarantine .
            run inside this folder, then start it again.
  Linux:    in a terminal, go into this folder and run   ./loft-server

Then open http://localhost:4545 in a browser (from other devices: this computer's address, port
4545). The first person to open it creates the admin account, then chooses the books folder in
Library settings.

Updates
-------
Once a day Loft checks for a new version and downloads it. Admins see "Loft x.y.z is ready" in
the notifications and in Library settings, where Restart to update swaps it in (the old version is
kept beside this folder as loft-server.previous; on Windows, a copy installed with the setup is
updated by the next setup instead). On Windows the tray icon also says so, with Update in its menu. Loft needs to be allowed to write to the folder this one is in.
Turn checking off in Library settings.

Settings
--------
Most settings are in the web app. For the rest (port, address to listen on, where Loft keeps its
data) copy config.example.toml to config.toml in the folder you start Loft from (on Windows, when
Loft Server runs it: %LOCALAPPDATA%\Loft\config.toml, then Restart in its menu), or set
LOFT_CONFIG to its path. LOFT_PORT, LOFT_HOST, LOFT_DATA_DIR and LOFT_BOOKS_DIRS work too.

Loft's own data (accounts, the library, covers) is kept in
  Windows:  %LOCALAPPDATA%\Loft
  macOS and Linux:  ~/.local/share/loft
Back that folder up. Your books themselves are never changed, and uninstalling Loft leaves this
folder where it is.

CBR comics need a RAR tool: Windows 10 and later and macOS already have one (tar); on Linux install
unar, unrar or 7z.

More: https://github.com/Spinjitsudoom/Loft
