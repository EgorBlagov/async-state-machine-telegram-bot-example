from typing import Any
import asyncio
import abc
import aiohttp
import yarl
import requests


def simple_request(url: str, **query_params: Any) -> dict:
    return requests.get(yarl.URL(url).update_query(**query_params)).json()

class IoApi(abc.ABC):
    @abc.abstractmethod
    def input(self, prompt: str | None = None) -> str:
        pass

    @abc.abstractmethod
    def print(self, message: str) -> None:
        pass


class CliApi(IoApi):
    def input(self, prompt: str | None = None) -> str:
        return input(prompt)

    def print(self, message: str) -> None:
        print(message)


def weather_query(io: IoApi):
    while True:
        city = io.input("Name a city: ")
        response = simple_request(
            "https://geocoding-api.open-meteo.com/v1/search", name=city
        )
        cities = response.get("results")

        if not cities:
            io.print("Found nothing")
            continue

        city = cities[0]
        io.print(
            "Found {name} ({country}) at latitude {latitude} and longitude {longitude}".format(
                **city
            )
        )

        response = simple_request(
            "https://api.open-meteo.com/v1/forecast",
            latitude=city["latitude"],
            longitude=city["longitude"],
            current_weather=1,
        )

        io.print(
            f"Current temperature is {response['current_weather']['temperature']} °C"
        )

io = CliApi()
weather_query(io)
