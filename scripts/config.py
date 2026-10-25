# Configuración común de los scripts de actualización.
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(RAIZ, "data")
RANKING = os.path.join(DATA, "ranking")

# Club de referencia: sus jugadores sirven para detectar si el ranking ha cambiado
CLUB = "ESCUADRON ALCALAINO"

# Jugadores que no deben aparecer nunca en la web (por idJugador). No se guardan en los datos.
EXCLUIDOS = {136375, 138402, 136352, 136361, 136367, 136371, 138478}

UA = "Mozilla/5.0 (Estadisticas Padel; uso personal)"
