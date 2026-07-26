import csv
import datetime
import json
import logging
from enum import Enum
from typing import Any, TypedDict

import geopy
import geopy.distance
import requests  # type: ignore
from bs4 import BeautifulSoup


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
JSON_FORECAST_URL = "https://app-prod-ws.meteoswiss-app.ch/v2/forecast?plz={}00&graph_startLowResolution=true&warning=true"
# The Swiss Meteo enrichment payload also includes warnings, which may be useful later.
JSON_PLZ_DETAIL_URL = "https://app-prod-ws.meteoswiss-app.ch/v1/plzDetail?plz={}00"
MS_SEARCH_URL = "https://www.meteosuisse.admin.ch/home/actualite/infos.html?ort={}&pageIndex=0&tab=search_tab"
CURRENT_CONDITION_URL = (
    "https://data.geo.admin.ch/ch.meteoschweiz.messwerte-aktuell/VQHA80.csv"
)
CURRENT_PRECIPITATION_URL = (
    "https://data.geo.admin.ch/ch.meteoschweiz.messwerte-aktuell/VQHA98.csv"
)
STATION_URL = "https://data.geo.admin.ch/ch.meteoschweiz.messnetz-automatisch/ch.meteoschweiz.messnetz-automatisch_fr.csv"
STATION_TYPE_PRECIPITATION = "Précipitation"
STATION_TYPE_WEATHER = "Station météo"

MS_24FORECAST_URL = (
    "https://www.meteosuisse.admin.ch/product/output/forecast-chart/{}/fr/{}00.json"
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


class HourlyForecast(TypedDict):
    time: datetime.datetime
    temperatureMax: float
    temperatureMean: float
    temperatureMin: float
    precipitationMax: float
    precipitationMean: float
    precipitationMin: float
    condition: int | None


def HourlyForecast_from_meteoswiss_data(data: dict[str, Any]) -> list[HourlyForecast]:
    time = datetime.datetime.fromtimestamp(
        data["start"] / 1000, tz=datetime.timezone.utc
    )
    results: list[HourlyForecast] = []
    for idx in range(
        min(
            [
                len(data["temperatureMin1h"]),
                len(data["temperatureMax1h"]),
                len(data["temperatureMean1h"]),
                len(data["precipitationMin1h"]),
                len(data["precipitationMean1h"]),
                len(data["precipitationMax1h"]),
            ]
        )
    ):
        d = HourlyForecast(
            time=time,
            temperatureMax=data["temperatureMax1h"][idx],
            temperatureMean=data["temperatureMean1h"][idx],
            temperatureMin=data["temperatureMin1h"][idx],
            precipitationMin=data["precipitationMin1h"][idx],
            precipitationMean=data["precipitationMean1h"][idx],
            precipitationMax=data["precipitationMax1h"][idx],
            condition=None,
        )
        results.append(d)
        time = time + datetime.timedelta(hours=1)
    return results


def enrich_hourly_forecast_conditions_from_plz_detail(
    hourly_forecast: list[HourlyForecast], data: dict[str, Any] | None
) -> list[HourlyForecast]:
    """
    Enrich the hourly forecast with condition icons from the PLZ detail data when available.

    The PLZ detail data contains 3-hourly condition icons, so we match them to the hourly forecast entries based on
    their timestamps.
    """
    if data is None:
        return hourly_forecast

    graph = data.get("graph")
    if not isinstance(graph, dict):
        return hourly_forecast

    start_low_resolution = graph.get("startLowResolution")
    if start_low_resolution is None:
        return hourly_forecast

    weather_icon_3h = graph.get("weatherIcon3h")
    if not isinstance(weather_icon_3h, list):
        return hourly_forecast

    def intornone(val: Any) -> int | None:
        if val is None or val == "":
            return None
        return int(val)

    time_to_condition: dict[datetime.datetime, int | None] = {}
    start_time = datetime.datetime.fromtimestamp(
        start_low_resolution / 1000, tz=datetime.timezone.utc
    )
    for idx in range(len(weather_icon_3h)):
        time_to_condition[start_time + datetime.timedelta(hours=idx * 3)] = intornone(
            weather_icon_3h[idx]
        )

    latest_condition: int | None = None
    for idx, hourly_entry in enumerate(hourly_forecast):
        matched_condition = time_to_condition.get(hourly_entry["time"])
        if matched_condition is not None:
            latest_condition = matched_condition

        hourly_forecast[idx] = HourlyForecast(
            time=hourly_entry["time"],
            temperatureMax=hourly_entry["temperatureMax"],
            temperatureMean=hourly_entry["temperatureMean"],
            temperatureMin=hourly_entry["temperatureMin"],
            precipitationMin=hourly_entry["precipitationMin"],
            precipitationMean=hourly_entry["precipitationMean"],
            precipitationMax=hourly_entry["precipitationMax"],
            condition=latest_condition,
        )

    return hourly_forecast


class Forecast(TypedDict):
    plz: str
    currentWeather: CurrentWeather
    regionForecast: list[DayForecast]
    regionHourlyForecast: list[HourlyForecast]


def Forecast_from_meteoswiss_data(
    data: dict[str, Any], plz_detail_data: dict[str, Any] | None
) -> Forecast:
    hourly_forecast = HourlyForecast_from_meteoswiss_data(data["graph"])
    hourly_forecast = enrich_hourly_forecast_conditions_from_plz_detail(
        hourly_forecast, plz_detail_data
    )

    return Forecast(
        plz=data["plz"],
        currentWeather=data["currentWeather"],
        regionForecast=[
            DayForecast_from_meteoswiss_data(x) for x in data["regionForecast"]
        ],
        regionHourlyForecast=hourly_forecast,
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
        if val == "" or val == "-" or val is None:
            return None
        return float(val)

    return CurrentCondition(
        station=data["Station/Location"],
        date=int(data["Date"]),
        tre200s0=floatornone(data.get("tre200s0")),
        rre150z0=floatornone(data.get("rre150z0")),
        sre000z0=floatornone(data.get("sre000z0")),
        gre000z0=floatornone(data.get("gre000z0")),
        ure200s0=floatornone(data.get("ure200s0")),
        tde200s0=floatornone(data.get("tde200s0")),
        dkl010z0=floatornone(data.get("dkl010z0")),
        fu3010z0=floatornone(data.get("fu3010z0")),
        fu3010z1=floatornone(data.get("fu3010z1")),
        prestas0=floatornone(data.get("prestas0")),
        pp0qffs0=floatornone(data.get("pp0qffs0")),
        pp0qnhs0=floatornone(data.get("pp0qnhs0")),
        ppz850s0=floatornone(data.get("ppz850s0")),
        ppz700s0=floatornone(data.get("ppz700s0")),
        dv1towz0=floatornone(data.get("dv1towz0")),
        fu3towz0=floatornone(data.get("fu3towz0")),
        fu3towz1=floatornone(data.get("fu3towz1")),
        ta1tows0=floatornone(data.get("ta1tows0")),
        uretows0=floatornone(data.get("uretows0")),
        tdetows0=floatornone(data.get("tdetows0")),
    )


class ClientResult(TypedDict):
    name: str
    forecast: Forecast | None
    # A list of current conditions for the first station passed.
    condition: list[CurrentCondition]
    # A dictionary of station -> list of the current precipitation
    # returned by the corresponding station.
    condition_by_station: dict[str, CurrentCondition]


def ClientResult_from_meteoswiss_data(
    data: dict[str, Any], plz_detail_data: dict[str, Any] | None
) -> ClientResult:
    # PLZ came back as zero or None, no forecast
    if not data["forecast"].get("plz"):
        forecast = None
    else:
        forecast = Forecast_from_meteoswiss_data(
            data["forecast"], plz_detail_data)
    return ClientResult(
        name=data["name"],
        forecast=forecast,
        condition=[CurrentCondition_from_meteoswiss_data(
            x) for x in data["condition"]],
        condition_by_station={
            station: CurrentCondition_from_meteoswiss_data(condition)
            for (station, condition) in data["condition_by_station"].items()
        },
    )


class meteoSwissClient:
    def __init__(self, displayName=None, postcode=None, *station: str):
        _LOGGER.debug("MS Client INIT")
        self._postCode = postcode
        self._stations = station
        self._name = displayName
        self._allStations: dict[str, Any] | None = None
        self._condition = None
        self._conditions: dict[str, Any] = {}
        self._precipitation = None
        self._precipitations: dict[str, Any] = {}
        self._forecast = None
        _LOGGER.debug(
            "INIT meteoswiss client : name = %s stations = %s postcode = %s"
            % (self._name, self._stations, self._postCode)
        )

    def get_data(self):
        self.get_forecast()
        self.get_current_condition()
        return {
            "name": self._name,
            "forecast": self._forecast,
            "condition": self._condition,
            "condition_by_station": self._conditions,
        }

    def get_typed_data(self) -> ClientResult:
        data = self.get_data()
        plz_detail_data = None
        if self._forecast is not None:
            plz_detail_data = self._forecast.get("plzDetail")
        return ClientResult_from_meteoswiss_data(data, plz_detail_data)

    def get_24hforecast(self):
        _LOGGER.debug("Start update 24h forecast data")
        s = requests.Session()
        # Forcing headers to avoid 500 error when downloading file
        s.headers.update(_HEADERS)
        searchUrl = MS_SEARCH_URL.format(self._postCode)
        _LOGGER.debug("Main URL : %s" % searchUrl)
        tmpSearch = s.get(searchUrl, timeout=10)

        soup = BeautifulSoup(tmpSearch.text, features="html.parser")
        widgetHtml = soup.find_all("section", {"id": "weather-widget"})
        jsonUrl = widgetHtml[0].get("data-json-url")
        jsonUrl = str(jsonUrl)
        version = jsonUrl.split("/")[5]
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
        s = requests.Session()
        # Forcing headers to avoid 500 error when downloading file
        s.headers.update(_HEADERS)

        jsonUrl = JSON_FORECAST_URL.format(self._postCode)
        _LOGGER.debug("Start update forecast data with URL %s", jsonUrl)
        jsonData = s.get(jsonUrl, timeout=10)
        jsonData.raise_for_status()
        jsonObj = jsonData.json()

        # Keep the current 1-hour forecast endpoint as source of truth,
        # then enrich it with 3-hour condition icons when available.
        plzDetailUrl = JSON_PLZ_DETAIL_URL.format(self._postCode)
        _LOGGER.debug(
            "Fetching 3-hour condition data from URL %s", plzDetailUrl)
        try:
            plzDetailData = s.get(plzDetailUrl, timeout=10)
            plzDetailData.raise_for_status()
            jsonObj["plzDetail"] = plzDetailData.json()
        except requests.RequestException:
            _LOGGER.exception(
                "Could not fetch 3-hour condition data from MeteoSwiss URL %s",
                plzDetailUrl,
            )

        self._forecast = jsonObj
        _LOGGER.debug("End of forecast update")

    def get_current_condition(self):
        _LOGGER.debug("Update current condition")
        with requests.get(CURRENT_CONDITION_URL) as response:
            response.raise_for_status()
            response.encoding = "iso_8859_1"
            lines = response.text.split("\n")
            csv_reader = csv.DictReader(lines, delimiter=";")
            data = [row for row in csv_reader if row]
        with requests.get(CURRENT_PRECIPITATION_URL) as response:
            response.raise_for_status()
            response.encoding = "iso_8859_1"
            lines = response.text.split("\n")
            csv_reader = csv.DictReader(lines, delimiter=";")
            rain_data = [row for row in csv_reader if row]
        conditions = {}
        condition_list = []
        for station in self._stations:
            _LOGGER.debug("Get current condition for : %s" % station)
            stationData = [d for d in data if d["Station/Location"] == station]
            _LOGGER.debug("stationData: %s", stationData)
            rainData = [
                d for d in rain_data if d["Station/Location"] == station]
            _LOGGER.debug("rainData: %s", rainData)
            if rainData and not stationData:
                stationData = rainData
            elif rainData and stationData:
                # Add all values from each rain data to each station data.
                for sd, rd in zip(stationData, rainData):
                    for k, v in rd.items():
                        sd[k] = v
            else:
                # if
                # (stationData and not rainData)
                # or
                # (not stationData and not rainData)
                pass
            condition_list.extend(stationData)
            if stationData:
                conditions[station] = stationData[0]
        self._condition = condition_list
        self._conditions = conditions

    def update(self):
        self.get_forecast()
        self.get_current_condition()

    def __get_all_stations(self) -> dict[str, Any]:
        _LOGGER.debug("Getting all stations from : %s" % (STATION_URL))
        with requests.get(STATION_URL) as response:
            response.encoding = "iso_8859_1"
            lines = response.text.split("\n")
            csv_reader = csv.DictReader(lines, delimiter=";")
            data = [row for row in csv_reader if row]

        stationList = {}
        for line in data:
            if (
                line["Type de station"] != STATION_TYPE_PRECIPITATION
                and line["Type de station"] != STATION_TYPE_WEATHER
            ):
                continue
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
                _LOGGER.debug("unknown station type %s" %
                              line["Type de station"])
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
            _LOGGER.warning(
                "Unable to find station name for : %s" % (stationId))
            return None

    def getGeoData(self, lat, lon, user_agent=None):
        s = requests.Session()
        s.headers.update(_HEADERS)
        if user_agent:
            s.headers.update({"User-Agent": user_agent})

        uri = (
            "https://nominatim.openstreetmap.org/reverse"
            f"?format=jsonv2&lat={lat}&lon={lon}&zoom=18"
        )
        _LOGGER.debug("Requesting Nominatim OSM data at URL %s", uri)
        geoData_req = s.get(uri)
        try:
            geoData_req.raise_for_status()
            geoData = geoData_req.json()
            _LOGGER.debug("Got data from OpenStreetMap: %s" % (geoData))
            return geoData
        except Exception:
            _LOGGER.exception(
                "Cannot get Nominatim OSM data: %s", geoData_req.text)
            raise

    def getPostCode(self, lat, lon):
        geoData = self.getGeoData(lat, lon)
        try:
            return geoData["address"]["postcode"]
        except Exception:
            _LOGGER.warning(
                "Unable to get post code for location lat : %s lon : %s" % (
                    lat, lon)
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
