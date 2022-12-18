from typing import Any
import asyncio
import abc
import aiohttp
import yarl
import requests


def simple_request(url: str, **query_params: Any) -> dict:
    return requests.get(yarl.URL(url).update_query(**query_params)).json()

def weather_query():
    while True:
        city = input("Name a city: ")
        response = simple_request(
            "https://geocoding-api.open-meteo.com/v1/search", name=city
        )
        cities = response.get("results")

        if not cities:
            print("Found nothing")
            continue

        city = cities[0]
        print(
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

        print(
            f"Current temperature is {response['current_weather']['temperature']} °C"
        )

weather_query()
