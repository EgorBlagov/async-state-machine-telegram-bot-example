# Integrating Async State Machine with Telegram Bot keeping Business logic safe

## Intro

Hi everyone, today we are going to develop interactive Telegram bot, starting with interactive CLI (Command Line Interface) for basic task: weather check in specified city. We won't implement anything revolutional, but we'll nail down `asyncio` and use it to write better and simple code!

Recently, I've made a bot for personal use, and I'd come up with the structure I'm going to describe. I really liked the way the main logic was split from Telegram's handlers, and got to know `asyncio` better, so I just want to share it with you.
We will start from scratch and go through all the steps together. I'll attach Github commits for all stages.

We will learn a little about `asyncio`, abstraction, `python-telegram-bot` and my incompetence.

## Technologies

We will use:
- `Python 3.10+` *could be lower, if you tune type annotations*
- [`asyncio`](https://docs.python.org/3/library/asyncio.html)
- [`aiohttp`](https://docs.aiohttp.org/en/stable/)
- [`pydantic`](https://docs.pydantic.dev/) *optional, I use it for fancy env variable parsing*
- [`python-telegram-bot`](https://python-telegram-bot.org/) *I could not refuse*
- [`yarl`](https://yarl.aio-libs.org/en/latest/) *to build a URL query*

You'll need to install the dependencies, likely you'll do it this way:

```bash

pip install aiohttp pydantic yarl
pip install --pre python-telegram-bot

```
*__Note:__ I use pre-release version of `python-telegram-bot`, hence the `--pre` flag*


## Sync CLI script that makes things done

So to demonstrate let's start with the CLI to handle our task. The CLI will ask us for the city name, and will print current temperature there. This will represent our business logic.
I've found some simple open API to get the weather and city coordinates called [Open-Meteo](https://open-meteo.com/en). And drafted the script ([commit](https://github.com/EgorBlagov/async-state-machine-telegram-bot-example/commit/9eccc3537cece64633277d70207c74458da323a7)):

```python

from typing import Any
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
```

I've added a wrapper to simplify my HTTP request. Let me explain it bit by bit:
1. Ask the user for a city name.
2. Fetch the city coordinates (if we didn't find anything, ask the user to enter the city name again).
3. Print what we've found.
4. Use the received coordinates to fetch the weather in the city.
5. Print the temperature.
6. Repeat the process forever.

Here is an example of the output:

```
Name a city: Paris
Found Paris (France) at latitude 48.85341 and longitude 2.3488
Current temperature is 9.7 °C
Name a city: Berlin
Found Berlin (Germany) at latitude 52.52437 and longitude 13.41053
Current temperature is 3.0 °C
```

Let's not stop here for long. It does the job, though I'd suggest to wrap IO actions like `print` and `input` with some abstraction ([commit](https://github.com/EgorBlagov/async-state-machine-telegram-bot-example/commit/6fe60a66595b1f918afdc7dbb4cdb2e3e5a5ae3f)), let's introduce the interface that will meet our needs:

```python

class IoApi(abc.ABC):
    @abc.abstractmethod
    def input(self, prompt: str | None = None) -> str:
        pass

    @abc.abstractmethod
    def print(self, message: str) -> None:
        pass

```

And now we can implement the interface with our CLI interaction methods:

```python

class CliApi(IoApi):
    def input(self, prompt: str | None = None) -> str:
        return input(prompt)

    def print(self, message: str) -> None:
        print(message)

```

Quite straightforward I believe. Last thing to do is to pass the object into our main function, and use it's methods instead of direct calls of `print` and `input`:

```diff

-def weather_query():
+def weather_query(io: IoApi):
     while True:
-        city = input("Name a city: ")
+        city = io.input("Name a city: ")
         response = simple_request(
             "https://geocoding-api.open-meteo.com/v1/search", name=city
         )
         cities = response.get("results")
 
         if not cities:
-            print("Found nothing")
+            io.print("Found nothing")
             continue
 
         city = cities[0]
-        print(
+        io.print(
             "Found {name} ({country}) at latitude {latitude} and longitude {longitude}".format(
                 **city
             )
@@ -35,8 +53,9 @@ def weather_query():
             current_weather=1,
         )
 
-        print(
+        io.print(
             f"Current temperature is {response['current_weather']['temperature']} °C"
         )

```

My goodness, we're doing some serious stuff here, abstractions, interfaces, objects... Why to bother? I was motivated to save an opportunity to quickly shut off Telegram bot and test it directly in CLI.

At this point I decided that our simple example is too primitive, and added another IO operation, called `choose` ([commit](https://github.com/EgorBlagov/async-state-machine-telegram-bot-example/commit/e6d2521da126c6a3f96aa3898a3bb6893280cd1e)):

```diff

@@ -57,5 +71,13 @@ def weather_query(io: IoApi):
             f"Current temperature is {response['current_weather']['temperature']} °C"
         )
 
+        CONTINUE, QUIT = "continue", "quit"
+
+        choice = io.choose(CONTINUE, QUIT)
+        if choice == QUIT:
+            io.print("Terminating")
+            break
+

```

The idea is straightforward: we show the user a list of options, they choose one, and we act accordingly, Here is my implementation:

```python

# Interface

    @abc.abstractmethod
    def choose(self, *options: str) -> str:
        pass

# Implementation

    def choose(self, *options: str) -> str:
        while True:
            try:
                option_lines = [f"{i}) {opt}" for i, opt in enumerate(options)]
                self.print("\n".join(option_lines))
                user_input = self.input("Enter index: ")
                return options[int(user_input)]
            except KeyboardInterrupt:
                raise
            except:
                self.print("Try again")

```

Hope you follow me! So here we just print list of options to user, they decide what they want and should type an index of desired option.


## State machine

I've promised you a State machine here, my approach bases on the `State` interface, and infinite loop that runs `State.run` and get's next state as the result:

```python

class State(abc.ABC):
    class ExitLoop(Exception):
        pass

    @abc.abstractmethod
    def run(self, io: IoApi) -> "State":
        pass

# ... States definitions

def weather_query(io: IoApi):
    current_state = FindCityPosition()

    while True:
        try:
            next_state = current_state.run(io)
            current_state = next_state

        except State.ExitLoop:
            io.print("Terminating")
            return

```

With this approach we can create complicated behavior with states and branching. Though our original behavior is very basic we can split the stages logically into several states:

1. Search City location
2. Fetch the weather
3. Ask if we continue or try again

The `State.ExitLoop` exception is used inside states to initiate exit from the main loop. It's raised from `ExitOrContinue` state if user selects `QUIT` option.

Details you can check in the [commit](https://github.com/EgorBlagov/async-state-machine-telegram-bot-example/commit/3b6f04a5bb382f610a44cf49d34ffbfa1dfa5862), but the structure a state class might look like this:

```python

class MyAwesomeState(State):
    def __init__(self, some_argument: str):
        self._some_argument = some_argument

    def run(self, io: IoApi) -> "State":
        # do stuff

        if self._some_argument == "something":
            return self # repeat the state again
        
        # do some other stuff

        if self._some_argument == "something else":
            return MyAwesomeNextState(10)
        
        # maybe do more stuff
    
        return MyAwesomeAnotherState(30)

```

It's an overkill for our task, but if we try to implement something more advanced we will be able to easily add more and more different states and interactions.

## Async

Why use async? For my initial task there was no difference whether my thing need to work synchronously or asynchronously. I made it async because of three reasons:

1. Telegram wrapper used `asyncio`
2. Abstraction
3. Increase throughput (as we are IO bound)

If we have a look at example:

```python

user_input = input('give me some input')

```

The thing actually is an async operation, you can pause your program here, and wait for user input (IO bound operation). So we should think of it like this:

```python

user_input = await some_input('give me some input')

```

Under the hood various things can occur: we can show the dialog to user and wait for their input, we can send a message in Telegram, and wait for user reply, we can print text into the console and wait for user input and so on...

Here I don't care how it works under the hood, I need some abstract async function `some_input` that will send the text somewhere, and return the reply to me, I just want to wait for the result.

We could do the same thing with a blocking call (synchronous), but we would have to lock one thread (per user) and make it wait without doing any useful work. This is doable, but it's much easier to implement a Future-like (spoiler) object using async programming and wait for it to resolve. And let's not forget async is known to have good performance if you need to work with many users at once with IO bound tasks.

Let's rewrite our HTTP request to become async:


```diff

-def simple_request(url: str, **query_params: Any) -> dict:
-    return requests.get(yarl.URL(url).update_query(**query_params)).json()
+async def simple_request(url: str, **query_params: Any) -> dict:
+    async with aiohttp.ClientSession() as session:
+        async with session.get(yarl.URL(url).update_query(**query_params)) as response:
+            return await response.json()
 
```

*__Note:__ It's worth noting that if you have several requests (fetching data from multiple places at once) you should call them within a single `ClientSession` context to improve performance ([have a look at the aiohttp docs](https://docs.aiohttp.org/en/latest/http_request_lifecycle.html#why-is-aiohttp-client-api-that-way)), for our example it's not needed*

To not bore you and not spend kilobytes I'll put here only one state changes, rest of the changes can be found in the [commit](https://github.com/EgorBlagov/async-state-machine-telegram-bot-example/commit/d5bb2d48a6937de8880b17775d6f48c18d8429f4):

```diff

class FindCityPosition(State):
-    def run(self, io: IoApi) -> "State":
-        city = io.input("Name a city: ")
-        response = simple_request(
+    async def run(self, io: IoApi) -> "State":
+        city = await io.input("Name a city: ")
+        response = await simple_request(
             "https://geocoding-api.open-meteo.com/v1/search", name=city
         )
         cities = response.get("results")
 
         if not cities:
-            io.print("Found nothing")
+            await io.print("Found nothing")
             return self
 
         city = cities[0]
-        io.print(
+        await io.print(
             "Found {name} ({country}) at latitude {latitude} and longitude {longitude}".format(
                 **city
             )

```

To call an async function (they're called coroutines), you need to put it into an event loop. Usually in this kind of tutorials it's done this way:

```python

io = CliApi()
loop = asyncio.new_event_loop()
loop.run_until_complete(weather_query(io))

```

It's ok for us now.

## Here comes Telegram

I'm not going to dive into usage of `python-telegram-bot`, they have plenty of examples in the repo. Let's take small steps, parsing Telegram API key from env (yep, you should never commit your secrets into the repo, it's a common approach to take it from env):


```python

class TelegramSettings(pydantic.BaseSettings):
    api_key: str

    class Config:
        env_prefix = "TELEGRAM_BOT_"

```

This will make `pydantic` look for `TELEGRAM_BOT_API_KEY` variable within environment.
If you're confused about environment variables, just before you start script do this:

```bash

export TELEGRAM_BOT_API_KEY=<your-api-key>
python3 main.py

```

Good, now let's create the application:

```python

application = Application.builder().token(TelegramSettings().api_key).build()

```
Implementing the commands:

```python

ACTIVE_TASK_KEY = "active_task_key"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ACTIVE_TASK_KEY in context.user_data:
        await update.message.reply_text("Already running, call /cancel to exit")
        return

    context.user_data[ACTIVE_TASK_KEY] = True
    await update.message.reply_text("Started")

async def on_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"I received text: {update.message.text}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Exiting...")
    del context.user_data[ACTIVE_TASK_KEY]

```

Now we're adding silly error handler:

```python

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

```

To prevent bot from stopping or replying to our messages if we didn't start anything, let's add the decorator:

```python

def start_first(f):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if ACTIVE_TASK_KEY not in context.user_data:
            await update.message.reply_text("Not started, call /start first")
            return

        return await f(update, context)

    return wrapper

```

and decorate the commands we don't want to be available until the user doesn't start bot

```diff

+ @start_first
async def on_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"I received text: {update.message.text}")


+ @start_first
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Exiting...")
    del context.user_data[ACTIVE_TASK_KEY]

```

Finally, we are registering the handlers and start the application:

```python

application.add_handler(CommandHandler("start", start))
application.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_received)
)
application.add_handler(CommandHandler("cancel", cancel))
application.add_error_handler(error_handler)
application.run_polling()

```

*__Note:__ I've removed our main coroutine start for now, because we didn't connect our code with Telegram yet*

Almost forgot, here is the [commit](https://github.com/EgorBlagov/async-state-machine-telegram-bot-example/commit/2681f5ab7259d2b76539ab515a0c761e287ae498)

## Putting everything together

We're almost there! To summarize, we have our state machine that can be started as an async coroutine, and skeleton for Telegram bot. Do you remember how we've extracted our `IoApi` as an abstraction? Let's implement it now. We are starting from something simple:

```python


class TelegramApi(IoApi):
    def __init__(self, app: Application, user_id: int):
        self.app = app
        self.user_id = user_id

    @property
    def bot(self) -> ExtBot:
        return self.app.bot

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
                
```

The `ReplyKeyboardMarkup` applies to your `choose` method easily. The `print` method is quite simple, we just send the message to the user. Though in `choose` we send query to the user, wait for `input` (which is not yet implemented) and then repeat the process if user input is invalid.

Now to the **important part**. Basically it was the most puzzling thing I tried to resolve. Somehow I want to send message to Telegram, and somehow I need to wait for the reply. Ok we know how to handle reply, we have the handler:

```python

class TelegramApi(IoApi):
    # ...
    
    def on_text_received(self, text):
        # do something...but what?

@start_first
async def on_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[IO_API_KEY].on_text_received(update.message.text)

```

Meet the future!! No, really meet the [`asyncio.Future`](https://docs.python.org/3/library/asyncio-future.html). It's an awaitable object. So the idea is to create `Future` object once we call the `input` coroutine representing the input we are waiting from the user. Then we `await` it until it's resolved. In our `on_text_received` handler we get the `IoApi` object and call it's method to resolve the `Future` object. And once it's resolved -- `await` will be finished, and we will return from the `input` coroutine to the caller:

```python

    def __init__(self, app: Application, user_id: int):
        self.app = app
        self.user_id = user_id
        self._pending_input: asyncio.Future | None = None

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

```

Ok, we're done with one problem, and the solution doesn't look overcomplicated. Now we have another problem, if you remember how we've started our main coroutine:

```python

loop = asyncio.new_event_loop()
loop.run_until_complete(weather_query(io)) # execution blocks here

```

And how we start Telegram app:

```python

application.run_polling() # execution blocks here

```

Oh boy, what should we do? The thing that came to my mind was ingenious (it was self-assured). Actually no, I thought I could try to run my custom event loop, store it within `user_data` and forward it each time we get anything from user. But event loop inside another event loop turned out to be an antipattern. For the reader the solution might be obvious now, when we've took all the steps. But the idea of event loop and even using async for my state machine was not so clear when tried to abstract `input` and `output`. Actually I'd made my own "event loop" and instead of using `async`/`await` and `Future` I used `yield` (for the record, initially `asyncio` was implemented based on the same principle, moreover, modern `asyncio` coroutines are still very similar to generators)...

Good times... Though the solution is stupidly simple! Meet the [`asyncio.Task`](https://docs.python.org/3/library/asyncio-task.html#creating-tasks). We just need to put our coroutine into the `Task` and feed it to our event loop. It will be started right away.

*__Important:__ you should keep reference to the `Task` to prevent it from being collected by GC, [more info here](https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task)*


Let's update our `start` handler:

```diff

 async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
-    if ACTIVE_TASK_KEY in context.user_data:
+    if is_running(context):
         await update.message.reply_text("Already running, call /cancel to exit")
         return
 
-    context.user_data[ACTIVE_TASK_KEY] = True
-    await update.message.reply_text("Started")
+    await update.message.reply_text("Starting...")
+
+    loop = asyncio.get_running_loop()
+    telegram_io = TelegramApi(context.application, update.effective_user.id)
+    context.user_data[IO_API_KEY] = telegram_io
+    context.user_data[ACTIVE_TASK_KEY] = loop.create_task(weather_query(telegram_io))
 
```


That's it! Let's break it into the steps:

1. We create our `telegram_io` for the user
2. We save it into `user_data` to use it when we receive a message from user
3. We create our `Task` and save it into the `user_data` as well

What I really like about tasks -- you can cancel them. With threads it's not that easy...
Here is the [commit](https://github.com/EgorBlagov/async-state-machine-telegram-bot-example/commit/f4188245000f72765b444f08839fb4e0d090826d).

Notice how the main coroutine is divided from Telegram interaction -- when we attached telegram we didn't change anything in our state's logic!

## Conclusion

Let's revisit what we've done:

1. Implemented the code solving our problem
2. Extracted IO interaction as an abstraction
3. Made everything async
4. Split it into the states
5. Attached it to Telegram without changing our business logic

Now you can easily extend your business logic with loose coupling to IO interaction, by working with the states. The `IoApi`, is where improvements come in, like `send_image` or `send_audio`.

Though there might be some limitations. For example it might be challenging to work with the Keyboard: showing and hiding it without higher coupling to Telegram. I believe it's harder to fully utilize Telegram's capabilities keeping the abstraction. Also I cannot tell if this structure will work for chats with multiple users, because initial goal was to implement some single user application.

It's been an interesting experience for me, and again I was confused about usage of event loop, and I came to realize how I can use `asyncio.Future` and `asyncio.Task` to create more complicated execution flow. But of course I'm a little ashamed I didn't know it.

Try it out, and let me know if you have any questions or suggestions!