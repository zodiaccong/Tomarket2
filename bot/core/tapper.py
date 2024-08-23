import asyncio
from datetime import datetime
from random import randint
from time import time
from urllib.parse import unquote, quote

from aiocfscrape import CloudflareScraper
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from pyrogram import Client
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered, FloodWait
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw.types import InputBotAppShortName

from typing import Callable
import functools
from tzlocal import get_localzone
from bot.config import settings
from bot.exceptions import InvalidSession
from bot.utils import logger
from .agents import generate_random_user_agent
from .headers import headers

def error_handler(func: Callable):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            await asyncio.sleep(1)
            logger.error(f"{args[0].session_name} | {func.__name__} error: {e}")
    return wrapper

def convert_to_local_and_unix(iso_time):
    dt = datetime.fromisoformat(iso_time.replace('Z', '+00:00'))
    local_dt = dt.astimezone(get_localzone())
    unix_time = int(local_dt.timestamp())
    return unix_time

class Tapper:
    def __init__(self, tg_client: Client, proxy: str | None):
        self.session_name = tg_client.name
        self.tg_client = tg_client
        self.proxy = proxy

    async def get_tg_web_data(self) -> str:
        
        if self.proxy:
            proxy = Proxy.from_str(self.proxy)
            proxy_dict = dict(
                scheme=proxy.protocol,
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        try:
            if not self.tg_client.is_connected:
                try:
                    await self.tg_client.connect()

                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)
            
            while True:
                try:
                    peer = await self.tg_client.resolve_peer('Tomarket_ai_bot')
                    break
                except FloodWait as fl:
                    fls = fl.value

                    logger.warning(f"{self.session_name} | FloodWait {fl}")
                    logger.info(f"{self.session_name} | Sleep {fls}s")
                    await asyncio.sleep(fls + 3)
            
            ref_id = settings.REF_ID if randint(0, 100) <= 70 else "00005UEJ"
            
            web_view = await self.tg_client.invoke(RequestAppWebView(
                peer=peer,
                app=InputBotAppShortName(bot_id=peer, short_name="app"),
                platform='android',
                write_allowed=True,
                start_param=ref_id
            ))

            auth_url = web_view.url
            tg_web_data = unquote(
                string=unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]))
            tg_web_data_parts = tg_web_data.split('&')

            user_data = quote(tg_web_data_parts[0].split('=')[1])
            chat_instance = tg_web_data_parts[1].split('=')[1]
            chat_type = tg_web_data_parts[2].split('=')[1]
            auth_date = tg_web_data_parts[4].split('=')[1]
            hash_value = tg_web_data_parts[5].split('=')[1]

            init_data = (f"user={user_data}&chat_instance={chat_instance}&chat_type={chat_type}&start_param={ref_id}&auth_date={auth_date}&hash={hash_value}")
            
            if self.tg_client.is_connected:
                await self.tg_client.disconnect()

            return ref_id, init_data

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error: {error}")
            await asyncio.sleep(delay=3)
            return None, None

    @error_handler
    async def make_request(self, http_client, method, endpoint=None, url=None, **kwargs):
        full_url = url or f"https://api-web.tomarket.ai/tomarket-game/v1{endpoint or ''}"
        async with http_client.request(method, full_url, **kwargs) as response:
            return await response.json()
        
    @error_handler
    async def login(self, http_client, tg_web_data: str, ref_id: str) -> tuple[str, str]:
        response = await self.make_request(http_client, "POST", "/user/login", json={"init_data": tg_web_data, "invite_code": ref_id})
        return response.get('data', {}).get('access_token', None)

    @error_handler
    async def check_proxy(self, http_client: aiohttp.ClientSession) -> None:
        response = await self.make_request(http_client, 'GET', url='https://httpbin.org/ip', timeout=aiohttp.ClientTimeout(5))
        ip = response.get('origin')
        logger.info(f"{self.session_name} | Proxy IP: {ip}")

    @error_handler
    async def get_balance(self, http_client):
        return await self.make_request(http_client, "POST", "/user/balance")

    @error_handler
    async def claim_daily(self, http_client):
        return await self.make_request(http_client, "POST", "/daily/claim", json={"game_id": "fa873d13-d831-4d6f-8aee-9cff7a1d0db1"})

    @error_handler
    async def start_farming(self, http_client):
        return await self.make_request(http_client, "POST", "/farm/start", json={"game_id": "53b22103-c7ff-413d-bc63-20f6fb806a07"})

    @error_handler
    async def claim_farming(self, http_client):
        return await self.make_request(http_client, "POST", "/farm/claim", json={"game_id": "53b22103-c7ff-413d-bc63-20f6fb806a07"})

    @error_handler
    async def play_game(self, http_client):
        return await self.make_request(http_client, "POST", "/game/play", json={"game_id": "59bcd12e-04e2-404c-a172-311a0084587d"})

    @error_handler
    async def claim_game(self, http_client, points=None):
        return await self.make_request(http_client, "POST", "/game/claim", json={"game_id": "59bcd12e-04e2-404c-a172-311a0084587d", "points": points})

    @error_handler
    async def start_task(self, http_client, data):
        return await self.make_request(http_client, "POST", "/tasks/start", json=data)

    @error_handler
    async def check_task(self, http_client, data):
        return await self.make_request(http_client, "POST", "/tasks/check", json=data)

    @error_handler
    async def claim_task(self, http_client, data):
        return await self.make_request(http_client, "POST", "/tasks/claim", json=data)

    @error_handler
    async def get_combo(self, http_client):
        return await self.make_request(http_client, "POST", "/tasks/hidden")

    @error_handler
    async def get_stars(self, http_client):
        return await self.make_request(http_client, "POST", "/tasks/classmateTask")

    @error_handler
    async def start_stars_claim(self, http_client, data):
        return await self.make_request(http_client, "POST", "/tasks/classmateStars", json=data)

    @error_handler
    async def get_tasks(self, http_client):
        return await self.make_request(http_client, "POST", "/tasks/list", json={'language_code': 'en'})

    @error_handler
    async def run(self) -> None:

        if settings.USE_RANDOM_DELAY_IN_RUN:
            random_delay = randint(settings.RANDOM_DELAY_IN_RUN[0], settings.RANDOM_DELAY_IN_RUN[1])
            logger.info(f"{self.tg_client.name} | Bot will start in <red>{random_delay}s</red>")
            await asyncio.sleep(delay=random_delay)
        
        proxy_conn = ProxyConnector().from_url(self.proxy) if self.proxy else None
        http_client = CloudflareScraper(headers=headers, connector=proxy_conn)

        if self.proxy:
            await self.check_proxy(http_client=http_client)
        
        if settings.FAKE_USERAGENT:            
            http_client.headers['User-Agent'] = generate_random_user_agent(device_type='android', browser_type='chrome')

        ref_id, init_data = await self.get_tg_web_data()

        # ``
        # Наши переменные
        # ``
        end_farming_dt = 0
        tickets = 0
        next_stars_check = 0
        next_combo_check = 0

        while True:
            access_token = await self.login(http_client=http_client, tg_web_data=init_data, ref_id=ref_id)
            if not access_token:
                logger.info(f"{self.session_name} | Failed login")
                logger.info(f"{self.session_name} | Sleep <red>3600s</red>")
                await asyncio.sleep(delay=3600)
                return
            else:
                logger.info(f"{self.session_name} | <red>🍅 Login successful</red>")
                http_client.headers["Authorization"] = f"{access_token}"
            await asyncio.sleep(delay=1)

            balance = await self.get_balance(http_client=http_client)
            available_balance = balance['data']['available_balance']
            logger.info(f"{self.session_name} | Current balance: <red>{available_balance}</red>")

            if 'farming' in balance['data']:
                end_farm_time = balance['data']['farming']['end_at']
                if end_farm_time > time():
                    end_farming_dt = end_farm_time + 240
                    logger.info(f"{self.session_name} | Farming in progress, next claim in <red>{round((end_farming_dt - time()) / 60)}m.</red>")

            if time() > end_farming_dt:
                claim_farming = await self.claim_farming(http_client=http_client)
                if claim_farming['status'] == 500:
                    start_farming = await self.start_farming(http_client=http_client)
                    logger.info(f"{self.session_name} | Farm started.. 🍅")
                    end_farming_dt = start_farming['data']['end_at'] + 240
                    logger.info(f"{self.session_name} | Next farming claim in <red>{round((end_farming_dt - time()) / 60)}m.</red>")
                else:
                    farm_points = claim_farming['data']['claim_this_time']
                    logger.info(f"{self.session_name} | Success claim farm. Reward: <red>{farm_points}</red> 🍅")
                    start_farming = await self.start_farming(http_client=http_client)
                    logger.info(f"{self.session_name} | Farm started.. 🍅")
                    end_farming_dt = start_farming['data']['end_at'] + 240
                    logger.info(f"{self.session_name} | Next farming claim in <red>{round((end_farming_dt - time()) / 60)}m.</red>")
                await asyncio.sleep(1.5)

            if settings.AUTO_CLAIM_STARS and next_stars_check < time():
                get_stars = await self.get_stars(http_client)
                data_stars = get_stars.get('data', {})
                if get_stars.get('status', -1) == 0 and data_stars:
                    
                    if data_stars.get('status') > 2:
                        logger.info(f"{self.session_name} | Stars already claimed | Skipping....")

                    elif data_stars.get('status') < 3 and datetime.fromisoformat(data_stars.get('endTime')) > datetime.now():
                        start_stars_claim = await self.start_stars_claim(http_client=http_client, data={'task_id': data_stars.get('taskId')})
                        claim_stars = await self.claim_task(http_client=http_client, data=data)
                        if claim_stars is not None and claim_stars.get('status') == 0 and start_stars_claim is not None and start_stars_claim.get('status') == 0:
                            logger.info(f"{self.session_name} | Claimed stars | Stars: <red>+{start_stars_claim['data'].get('stars', 0)}</red>")
                    
                    next_stars_check = int(datetime.fromisoformat(get_stars['data'].get('endTime')).timestamp())

            await asyncio.sleep(1.5)

            if settings.AUTO_CLAIM_COMBO and next_combo_check < time():
                combo_info = await self.get_combo(http_client)
                combo_info_data = combo_info.get('data', [])[0] if combo_info.get('data') else []

                if combo_info is not None and combo_info.get('status') == 0 and combo_info_data:
                    if combo_info_data.get('status') > 0:
                        logger.info(f"{self.session_name} | Combo already claimed | Skipping....")
                    elif combo_info_data.get('status') == 0 and datetime.fromisoformat(
                            combo_info_data.get('end')) > datetime.now():
                        claim_combo = await self.claim_task(http_client, data = { 'task_id': combo_info_data.get('taskId') })

                        if claim_combo is not None and claim_combo.get('status') == 0:
                            logger.info(
                                f"{self.session_name} | Claimed combo | Points: <red>+{combo_info_data.get('score')}</red> | Combo code: <red>{combo_info_data.get('code')}</red>")
                    
                    next_combo_check = int(datetime.fromisoformat(combo_info_data.get('end')).timestamp())

            await asyncio.sleep(1.5)


            if settings.AUTO_DAILY_REWARD:
                claim_daily = await self.claim_daily(http_client=http_client)
                logger.info(f"{self.session_name} | Daily: <red>{claim_daily['data']['today_game']}</red> reward: <red>{claim_daily['data']['today_points']}</red>")

            await asyncio.sleep(1.5)

            if settings.AUTO_PLAY_GAME:
                available_tickets = balance.get('data').get('play_passes')
                tickets = available_tickets

                logger.info(f"{self.session_name} | Tickets: <red>{available_tickets}</red>")

                await asyncio.sleep(1.5)

                while tickets > 0:
                    logger.info(f"{self.session_name} | Start game...")
                    play_game = await self.play_game(http_client=http_client)
                    if play_game.get('status') == 0:
                        logger.info(f"{self.session_name} | Game in progress...")

                        await asyncio.sleep(30)
                        claim_game = await self.claim_game(http_client=http_client, points=randint(400, 600))

                        if claim_game.get('status') == 0:
                            logger.info(f"{self.session_name} | Game finish! Claimed points: <red>{claim_game.get('data').get('points')}</red>")
                            tickets -= 1
                            await asyncio.sleep(1.5)

            if settings.AUTO_TASK:
                logger.info(f"{self.session_name} | Start checking tasks.")
                tasks = await self.get_tasks(http_client=http_client)

                tasks_list = []
                if tasks["status"] == 0:
                    for values in tasks["data"].values():
                        for task in values:
                            if task.get('enable'):
                                if task.get('startTime') and task.get('endTime'):
                                    task_start = convert_to_local_and_unix(task['startTime'])
                                    task_end = convert_to_local_and_unix(task['endTime'])
                                    if task_start <= time() <= task_end:
                                        tasks_list.append(task)
                                elif task.get('type') != 'wallet':
                                    tasks_list.append(task)
                
                for task in tasks_list:
                    data = {'task_id': task['taskId']}
                    wait_second = task.get('waitSecond', 0)
                    await self.start_task(http_client=http_client, data=data)
                    await asyncio.sleep(wait_second)
                    checktask = await self.check_task(http_client=http_client, data=data)
                    if checktask.get('status') != 0:                    
                        claim = await self.claim_task(http_client=http_client, data=data)
                        logger.info(f"{self.session_name} | Start claim task <red>{task['name']}</red> 🍅")
                        if claim['status'] == 0:
                            logger.info(f"{self.session_name} | Task <red>{task['name']}</red> claimed! 🍅")
                            await asyncio.sleep(2)
                
                sleep_time = end_farming_dt - time()
                logger.info(f'{self.session_name} | Sleep <red>{round(sleep_time / 60, 2)}m.</red>')
                await asyncio.sleep(sleep_time)


async def run_tapper(tg_client: Client, proxy: str | None):
    try:
        await Tapper(tg_client=tg_client, proxy=proxy).run()
    except InvalidSession:
        logger.error(f"{tg_client.name} | Invalid Session")
