import geopy
import geopy.distance
import json
import logging
import pandas as pd
import requests  # type: ignore

from enum import Enum
from typing import Any, TypedDict


class StationType(str, Enum):
    """Station type."""

    WEATHER = "weather"
    PRECIPITATION = "precipitation"


_LOGGER = logging.getLogger(__name__)

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;"
    "q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, sdch",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML"
    ", like Gecko) Chrome/1337 Safari/537.36",
}

MS_BASE_URL = "https://www.meteosuisse.admin.ch"
JSON_FORECAST_URL = "https://app-prod-ws.meteoswiss-app.ch/v1/forecast?plz={}00&graph=false&warning=true"
CURRENT_CONDITION_URL = (
    "https://data.geo.admin.ch/ch.meteoschweiz.messwerte-aktuell/VQHA80.csv"
)
STATION_URL = "https://data.geo.admin.ch/ch.meteoschweiz.messnetz-automatisch/ch.meteoschweiz.messnetz-automatisch_fr.csv"
STATION_TYPE_PRECIPITATION = "Précipitation"
STATION_TYPE_WEATHER = "Station météo"

MS_VERSIONS_URL = "https://www.meteoswiss.admin.ch/product/output/versions.json"
MS_24FORECAST_URL = (
    "https://www.meteosuisse.admin.ch/product/output/forecast-chart/version__{}/fr/{}00.json"
)
MS_24FORECAST_REF = "https://www.meteosuisse.admin.ch//content/meteoswiss/fr/home.mobile.meteo-products--overview.html"


class CurrentWeather(TypedDict):
    time: int
    icon: int
    iconV2: int
    temperature: float


class DayForecast(TypedDict):
    dayDate: str
    iconDay: int
    iconDayV2: int
    temperatureMax: float
    temperatureMin: float
    precipitation: float


def DayForecast_from_meteoswiss_data(data: dict[str, Any]) -> DayForecast:
    return DayForecast(
        dayDate=data["dayDate"],
        iconDay=int(data["iconDay"]),
        iconDayV2=int(data["iconDayV2"]),
        temperatureMax=float(data["temperatureMax"]),
        temperatureMin=float(data["temperatureMin"]),
        precipitation=float(data["precipitation"]),
    )


class Forecast(TypedDict):
    plz: str
    currentWeather: CurrentWeather
    regionForecast: list[DayForecast]


def Forecast_from_meteoswiss_data(data: dict[str, Any]):
    return Forecast(
        plz=data["plz"],
        currentWeather=data["currentWeather"],
        regionForecast=[
            DayForecast_from_meteoswiss_data(x) for x in data["regionForecast"]
        ],
    )


class CurrentCondition(TypedDict):
    station: str
    date: int
    tre200s0: float | None
    rre150z0: float | None
    sre000z0: float | None
    gre000z0: float | None
    ure200s0: float | None
    tde200s0: float | None
    dkl010z0: float | None
    fu3010z0: float | None
    fu3010z1: float | None
    prestas0: float | None
    pp0qffs0: float | None
    pp0qnhs0: float | None
    ppz850s0: float | None
    ppz700s0: float | None
    dv1towz0: float | None
    fu3towz0: float | None
    fu3towz1: float | None
    ta1tows0: float | None
    uretows0: float | None
    tdetows0: float | None


def CurrentCondition_from_meteoswiss_data(data: dict[str, Any]) -> CurrentCondition:
    def floatornone(val: Any) -> float | None:
        if val == "" or val == "-":
            return None
        return float(val)

    return CurrentCondition(
        station=data["Station/Location"],
        date=int(data["Date"]),
        tre200s0=floatornone(data["tre200s0"]),
        rre150z0=floatornone(data["rre150z0"]),
        sre000z0=floatornone(data["sre000z0"]),
        gre000z0=floatornone(data["gre000z0"]),
        ure200s0=floatornone(data["ure200s0"]),
        tde200s0=floatornone(data["tde200s0"]),
        dkl010z0=floatornone(data["dkl010z0"]),
        fu3010z0=floatornone(data["fu3010z0"]),
        fu3010z1=floatornone(data["fu3010z1"]),
        prestas0=floatornone(data["prestas0"]),
        pp0qffs0=floatornone(data["pp0qffs0"]),
        pp0qnhs0=floatornone(data["pp0qnhs0"]),
        ppz850s0=floatornone(data["ppz850s0"]),
        ppz700s0=floatornone(data["ppz700s0"]),
        dv1towz0=floatornone(data["dv1towz0"]),
        fu3towz0=floatornone(data["fu3towz0"]),
        fu3towz1=floatornone(data["fu3towz1"]),
        ta1tows0=floatornone(data["ta1tows0"]),
        uretows0=floatornone(data["uretows0"]),
        tdetows0=floatornone(data["tdetows0"]),
    )


class ClientResult(TypedDict):
    name: str
    forecast: list[Forecast]
    condition: list[CurrentCondition]


def ClientResult_from_meteoswiss_data(data: dict[str, Any]) -> ClientResult:
    return ClientResult(
        name=data["name"],
        forecast=Forecast_from_meteoswiss_data(data["forecast"]),
        condition=[CurrentCondition_from_meteoswiss_data(x) for x in data["condition"]],
    )


class meteoSwissClient:
    def __init__(self, displayName=None, postcode=None, station=None):
        _LOGGER.debug("MS Client INIT")
        self._postCode = postcode
        self._station = station
        self._name = displayName
        self._allStations = None
        self._condition = None
        self._forecast = None
        _LOGGER.debug(
            "INIT meteoswiss client : name = %s station = %s postcode = %s"
            % (self._name, self._station, self._postCode)
        )

    def get_data(self):
        self.get_forecast()
        self.get_current_condition()
        return {
            "name": self._name,
            "forecast": self._forecast,
            "condition": self._condition,
        }

    def get_typed_data(self) -> ClientResult:
        data = self.get_data()
        return ClientResult_from_meteoswiss_data(data)

    def get_24hforecast(self):
        _LOGGER.debug("Start update 24h forecast data")
        s = requests.Session()
        # Forcing headers to avoid 500 error when downloading file
        s.headers.update(_HEADERS)
        _LOGGER.debug("Main URL : %s" % MS_VERSIONS_URL)
        versionsResponse = s.get(MS_VERSIONS_URL, timeout=10)
        version = json.loads(versionsResponse.text).get('forecast-chart')
        forecastUrl = MS_24FORECAST_URL.format(version, self._postCode)
        _LOGGER.debug("Data URL : %s" % forecastUrl)
        s.headers.update(
            {
                "referer": MS_24FORECAST_REF,
                "x-requested-with": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "dnt": "1",
            }
        )
        jsonData = s.get(forecastUrl, timeout=10)
        jsonData.encoding = "utf8"
        jsonDataTxt = jsonData.text

        jsonObj = json.loads(jsonDataTxt)

        self._forecast24 = jsonObj
        _LOGGER.debug("End of 24 forecast udate")

    def get_forecast(self):
        _LOGGER.debug("Start update forecast data")
        s = requests.Session()
        # Forcing headers to avoid 500 error when downloading file
        s.headers.update(_HEADERS)

        jsonUrl = JSON_FORECAST_URL.format(self._postCode)
        jsonData = s.get(jsonUrl, timeout=10)
        jsonDataTxt = jsonData.text

        jsonObj = json.loads(jsonDataTxt)

        self._forecast = jsonObj
        _LOGGER.debug("End of forecast udate")

    def get_current_condition(self):
        _LOGGER.debug("Update current condition")

        data = pd.read_csv(CURRENT_CONDITION_URL, sep=";", header=0)

        _LOGGER.debug("Get current condition for : %s" % self._station)
        stationData = data.loc[data["Station/Location"].str.contains(self._station)]
        stationData = stationData.to_dict("records")
        self._condition = stationData

    def update(self):
        self.get_forecast()
        self.get_current_condition()

    def __get_all_stations(self):
        _LOGGER.debug("Getting all stations from : %s" % (STATION_URL))
        data = pd.read_csv(
            STATION_URL,
            sep=";",
            header=0,
            skipfooter=4,
            encoding="latin1",
            engine="python",
        )
        stationList = {}
        for index, line in data.iterrows():
            stationData = {}
            stationData["code"] = line["Abr."]
            stationData["name"] = line["Station"]
            stationData["lat"] = line["Latitude"]
            stationData["lon"] = line["Longitude"]
            stationData["altitude"] = line["Altitude station m s. mer"]
            if line["Type de station"] == STATION_TYPE_PRECIPITATION:
                stationData["type"] = StationType.PRECIPITATION
            elif line["Type de station"] == STATION_TYPE_WEATHER:
                stationData["type"] = StationType.WEATHER
            else:
                assert 0, "unknown station type %s" % line["Type de station"]
            stationList[stationData["code"]] = stationData
        return stationList

    def get_all_stations(
        self,
        station_type=StationType | None,
    ) -> dict[str, Any]:
        if self._allStations is None:
            self._allStations = self.__get_all_stations()
        s: dict[str, Any] = {}
        for station_name, station in self._allStations.items():
            if station_type is not None and station["type"] != station_type:
                continue
            s[station_name] = station
        return s

    def get_closest_station(
        self, currentLat, currnetLon, station_type=StationType | None
    ):
        hPoint = geopy.Point(currentLat, currnetLon)
        data = []
        for station_name, station in self.get_all_stations(station_type).items():
            if station_type is not None and station["type"] != station_type:
                # User has requested a specific station type
                # and this station is not of that type.
                continue
            sPoint = geopy.Point(
                "%s/%s"
                % (
                    station["lat"],
                    station["lon"],
                )
            )
            distance = geopy.distance.distance(hPoint, sPoint)
            data += ((distance.km, station_name),)
        data.sort(key=lambda tup: tup[0])
        try:
            return data[0][1]
        except BaseException:
            _LOGGER.warning(
                "Unable to get closest station for lat : %s lon : %s"
                % (currentLat, currnetLon)
            )
            return None

    def get_station_name(self, stationId):
        if self._allStations is None:
            self._allStations = self.__get_all_stations()

        try:
            return self._allStations[stationId]["name"]
        except Exception:
            _LOGGER.warning("Unable to find station name for : %s" % (stationId))
            return None

    def getGeoData(self, lat, lon):
        s = requests.Session()
        lat = str(lat)
        lon = str(lon)
        s.headers.update(_HEADERS)

        geoData = s.get(
            "https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat="
            + lat
            + "&lon="
            + lon
            + "&zoom=18"
        ).text
        _LOGGER.debug("Got data from OpenStreetMap: %s" % (geoData))
        return json.loads(geoData)

    def getPostCode(self, lat, lon):
        geoData = self.getGeoData(lat, lon)
        try:
            return geoData["address"]["postcode"]
        except Exception:
            _LOGGER.warning(
                "Unable to get post code for location lat : %s lon : %s" % (lat, lon)
            )
            return None

    def get_wind_bearing(self, val):
        lis = {
            "N": [0, 11.25],
            "NNE": [11.25, 33.75],
            "NE": [33.75, 56.25],
            "ENE": [56.25, 78.75],
            "E": [78.75, 101.25],
            "ESE": [101.25, 123.75],
            "SE": [123.75, 146.25],
            "SSE": [146.25, 168.75],
            "S": [168.75, 191.25],
            "SSW": [191.25, 213.75],
            "SW": [213.75, 236.25],
            "WSW": [236.25, 258.75],
            "W": [258.75, 281.25],
            "WNW": [281.25, 303.75],
            "NW": [303.75, 326.25],
            "NNW": [326.25, 348.75],
        }

        for it in lis:
            if lis[it][0] <= float(val) <= lis[it][1]:
                return it
        return "N"
