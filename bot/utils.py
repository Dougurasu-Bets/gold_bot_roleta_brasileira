import aiohttp
from config import BASE_URL, ALLOWED_CHAT_IDS


def escape_markdown_v2(text: str, for_link: bool = False) -> str:
    escape_chars = [
        "\\",
        "(",
        ")",
        "~",
        "`",
        ">",
        "#",
        "+",
        "-",
        "=",
        "|",
        "{",
        "}",
        ".",
        "!",
    ]

    if not for_link:
        escape_chars.extend(["[", "]"])

    for char in escape_chars:
        text = text.replace(char, f"\\{char}")
    return text


async def send_telegram_message(message, link=None):
    if link:
        message = f"{message}\n🔗 <a href='{link}'>Acessar Mesa</a>"
        parse_mode = "HTML"
    else:
        message = escape_markdown_v2(message)
        parse_mode = "MarkdownV2"

    payload = {
        "chat_id": list(ALLOWED_CHAT_IDS)[0],
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BASE_URL}/sendMessage", json=payload
            ) as response:
                if response.status != 200:
                    print(f"Erro ao enviar mensagem: {await response.text()}")
    except Exception as e:
        print(f"Falha no envio: {e}")
