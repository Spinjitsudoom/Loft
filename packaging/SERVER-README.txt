Loft server
===========

This folder is the whole Loft server: nothing else needs installing. Keep the folder together.

Start it
--------
  Windows:  double-click loft-server.exe. A window opens and shows the server's messages; closing
            that window stops Loft. The first time, Windows may say it protected your PC: choose
            "More info", then "Run anyway". Allow it through the firewall if other devices should
            reach it.
  macOS:    in Terminal, go into this folder and run   ./loft-server
            The first time, macOS blocks programs downloaded from the internet that aren't from the
            App Store or a registered developer. Clear that once with
                xattr -dr com.apple.quarantine .
            run inside this folder, then start it again.
  Linux:    in a terminal, go into this folder and run   ./loft-server

Then open http://localhost:4545 in a browser (from other devices: this computer's address, port
4545). The first person to open it creates the admin account, then chooses the books folder in
Library settings.

Settings
--------
Most settings are in the web app. For the rest (port, address to listen on, where Loft keeps its
data) copy config.example.toml to config.toml in the folder you start Loft from, or set
LOFT_CONFIG to its path. LOFT_PORT, LOFT_HOST, LOFT_DATA_DIR and LOFT_BOOKS_DIRS work too.

Loft's own data (accounts, the library, covers) is kept in
  Windows:  %LOCALAPPDATA%\Loft
  macOS and Linux:  ~/.local/share/loft
Back that folder up. Your books themselves are never changed.

CBR comics need a RAR tool: Windows 10 and later and macOS already have one (tar); on Linux install
unar, unrar or 7z.

More: https://github.com/Spinjitsudoom/Loft
