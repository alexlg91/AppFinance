import os
import sys
import streamlit.web.cli as stcli

if __name__ == "__main__":
    # Détermine le chemin absolu du dossier où se trouve le script/exe
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    app_path = os.path.join(base_path, "app.py")

    sys.argv = ["streamlit", "run", app_path, "--global.developmentMode=false"]
    sys.exit(stcli.main())