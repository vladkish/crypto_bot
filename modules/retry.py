import asyncio
from loguru import logger

from settings import RETRY

from requests.exceptions import JSONDecodeError as json_error1
from json.decoder import JSONDecodeError as json_error2


class CustomError(Exception): pass

class DataBaseError(Exception): pass

class OnetimeError(Exception): pass

class TransactionError(Exception):
    def __init__(self, message: str, error_code: str, encoded_tx: str = ""):
        error_string = f"{message}: {error_code}" + (f" | encoded tx: {encoded_tx}" if encoded_tx else "")
        super().__init__(error_string)
        self.error_code = error_code
        self.encoded_tx = encoded_tx


def have_json(func):
    async def wrapper(*args, **kwargs):
        response = await func(*args, **kwargs)
        try:
            response.json()
        except (json_error1, json_error2):
            error_msg = response.text[:350].replace("\n", " ")
            raise Exception(f'bad json response: {error_msg}')

        return response
    return wrapper


def retry(
        source: str,
        module_str: str = None,
        exceptions = Exception,
        retries: int = RETRY,
        not_except = (CustomError,),
        infinity_errors_text: list = None,
        to_raise: bool = True,
        sleep_on_error: int = 2,
):
    def decorator(f):
        custom_module_str = f.__name__.replace('_', ' ').title() if not module_str else module_str
        async def newfn(*args, **kwargs):
            attempt = 0
            while attempt < retries:
                try:
                    return await f(*args, **kwargs)

                except not_except as e:
                    if to_raise: raise e.__class__(f'{custom_module_str}: {e}')
                    else: return False

                except exceptions as e:
                    try:
                        if hasattr(args[0], "address"):
                            error_owner = args[0].address + " | "
                        elif hasattr(args[0], "browser") and hasattr(args[0].browser, "address"):
                            error_owner = args[0].browser.address + " | "
                        elif hasattr(args[0], "wallet") and hasattr(args[0].wallet, "address"):
                            error_owner = args[0].wallet.address + " | "
                        else:
                            error_owner = ""
                    except:
                        error_owner = ""

                    attempt += 1

                    if infinity_errors_text and any([error_text in str(e) for error_text in infinity_errors_text]):
                        infinity_retries = 10

                        logger.warning(f'[-] {error_owner}{source} | {custom_module_str} | {e} [{attempt}/{infinity_retries}]')
                        if attempt == infinity_retries:
                            if to_raise: raise ValueError(f'{custom_module_str}: {e}')
                            else: return False

                    else:
                        logger.opt(colors=True).error(f'[-] {error_owner}<white>{source}</white> | {custom_module_str} | {e} [{attempt}/{retries}]')

                        if attempt == retries:
                            if to_raise: raise ValueError(f'{custom_module_str}: {e}')
                            else: return False

                    await asyncio.sleep(sleep_on_error)
        return newfn
    return decorator
