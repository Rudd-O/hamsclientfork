"""meteoswiss - Library to get data from meteo swiss"""

__version__ = "0.2.20"
__author__ = "websylv <div@webhu.org>"
__all__ = ["meteoSwissClient", "StationType"]

from .client import StationType, meteoSwissClient
