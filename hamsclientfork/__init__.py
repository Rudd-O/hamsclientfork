"""meteoswiss - Library to get data from meteo swiss"""

__version__ = "0.2.7"
__author__ = "websylv <div@webhu.org>"
__all__ = ["meteoSwissClient", "StationType"]

from .client import StationType, meteoSwissClient
