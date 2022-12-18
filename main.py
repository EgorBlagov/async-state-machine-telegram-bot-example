import abc
import asyncio
import logging
from typing import Any

import aiohttp
import pydantic
import yarl
from telegram import Update, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ExtBot,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


async def simple_request(url: str, **query_params: Any) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(yarl.URL(url).update_query(**query_params)) as response:
            return await response.json()


class IoApi(abc.ABC):
    @abc.abstractmethod
    async def input(self, prompt: str | None = None) -> str:
        pass

    @abc.abstractmethod
    async def print(self, message: str) -> None:
        pass

    @abc.abstractmethod
    async def choose(self, *options: str) -> str:
        pass


class CliApi(IoApi):
    async def input(self, prompt: str | None = None) -> str:
        return input(prompt)

    async def print(self, message: str) -> None:
        print(message)

    async def choose(self, *options: str) -> str:
        while True:
            try:
                option_lines = [f"{i}) {opt}" for i, opt in enumerate(options)]
                await self.print("\n".join(option_lines))
                user_input = await self.input("Enter index: ")
                return options[int(user_input)]
            except KeyboardInterrupt:
                raise
            except:
                logger.exception("Error in choose")
                await self.print("Try again")


class State(abc.ABC):
    class ExitLoop(Exception):
        pass

    @abc.abstractmethod
    async def run(self, io: IoApi) -> "State":
        pass


class FindCityPosition(State):
    async def run(self, io: IoApi) -> "State":
        city = await io.input("Name a city: ")
        response = await simple_request(
            "https://geocoding-api.open-meteo.com/v1/search", name=city
        )
        cities = response.get("results")

        if not cities:
            await io.print("Found nothing")
            return self

        city = cities[0]
        await io.print(
            "Found {name} ({country}) at latitude {latitude} and longitude {longitude}".format(
                **city
            )
        )

        return ShowWeatherAtCoord(city["latitude"], city["longitude"])


class ShowWeatherAtCoord(State):
    def __init__(self, latitude: float, longitude: float):
        self.latitude = latitude
        self.longitude = longitude

    async def run(self, io: IoApi) -> "State":
        response = await simple_request(
            "https://api.open-meteo.com/v1/forecast",
            latitude=self.latitude,
            longitude=self.longitude,
            current_weather=1,
        )

        await io.print(
            f"Current temperature is {response['current_weather']['temperature']} °C"
        )

        return ExitOrContinue()


class ExitOrContinue(State):
    CONTINUE, QUIT = "continue", "quit"

    async def run(self, io: IoApi) -> "State":
        choice = await io.choose(self.CONTINUE, self.QUIT)
        if choice == self.QUIT:
            raise State.ExitLoop

        return FindCityPosition()


async def weather_query(io: IoApi):
    current_state = FindCityPosition()

    while True:
        try:
            next_state = await current_state.run(io)
            current_state = next_state

        except State.ExitLoop:
            await io.print("Terminating")
            return


class TelegramApi(IoApi):
    def __init__(self, app: Application, user_id: int):
        self.app = app
        self.user_id = user_id
        self._pending_input: asyncio.Future | None = None

    @property
    def bot(self) -> ExtBot:
        return self.app.bot

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    def on_text_received(self, text):
        if self._pending_input is not None:
            self._pending_input.set_result(text)

    async def input(self, prompt: str | None = None) -> str:
        if self._pending_input is None:
            self._pending_input = self.loop.create_future()
            if prompt is not None:
                await self.print(prompt)

        result = await self._pending_input
        self._pending_input = None
        return result

    async def print(self, message: str) -> None:
        await self.bot.send_message(
            self.user_id, message, parse_mode=ParseMode.MARKDOWN
        )

    async def choose(self, *options: str) -> str:
        while True:
            try:
                await self.bot.send_message(
                    self.user_id,
                    "What should we do next?",
                    reply_markup=ReplyKeyboardMarkup([options], one_time_keyboard=True),
                )
                user_input = await self.input()
                if user_input in options:
                    return user_input
            except KeyboardInterrupt:
                raise
            except:
                logger.exception("Error in choose")
                await self.print("Try again")


class TelegramSettings(pydantic.BaseSettings):
    api_key: str

    class Config:
        env_prefix = "TELEGRAM_BOT_"


ACTIVE_TASK_KEY = "active_task_key"
IO_API_KEY = "io_api_key"


def is_running(context: ContextTypes.DEFAULT_TYPE) -> bool:
    active_task: asyncio.Task | None = context.user_data.get(ACTIVE_TASK_KEY)
    return active_task is not None and not active_task.done()


def start_first(f):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_running(context):
            await update.message.reply_text("Not started, call /start first")
            return

        return await f(update, context)

    return wrapper


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_running(context):
        await update.message.reply_text("Already running, call /cancel to exit")
        return

    await update.message.reply_text("Starting...")

    loop = asyncio.get_running_loop()
    telegram_io = TelegramApi(context.application, update.effective_user.id)
    context.user_data[IO_API_KEY] = telegram_io
    context.user_data[ACTIVE_TASK_KEY] = loop.create_task(weather_query(telegram_io))


@start_first
async def on_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[IO_API_KEY].on_text_received(update.message.text)


@start_first
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task: asyncio.Task = context.user_data[ACTIVE_TASK_KEY]
    task.cancel()
    await update.message.reply_text("Terminating")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)


application = Application.builder().token(TelegramSettings().api_key).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_received)
)
application.add_handler(CommandHandler("cancel", cancel))
application.add_error_handler(error_handler)
application.run_polling()
