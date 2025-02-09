import asyncio
from json import loads

from httpx import AsyncClient
from nonebot.log import logger

from ..config import config

# from ..function_call import registry
from ..exception import RequestException
from ..schemas import Choice, Balance, Message, ChatChunkedCompletions


class API:
    _client = AsyncClient()
    _headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {config.api_key}",
    }

    @classmethod
    async def chat(cls, message: list[dict[str, str]], model: str = "deepseek-chat") -> ChatChunkedCompletions:
        """普通对话"""
        model_config = config.get_model_config(model)
        # if model == "deepseek-chat":
        #     json.update({"tools": registry.to_json()})
        json = {
            "stream": True,
            "model": model,
            "messages": [{"content": config.prompt, "role": "system"}] + message
            if config.prompt and model == "deepseek-chat"
            else message,
            **model_config.to_dict(),
        }
        logger.debug(f"使用模型 {model}，配置：{json}")
        async with cls._client.stream(
            "POST",
            f"{model_config.base_url}/chat/completions",
            json=json,
            headers={**cls._headers, "Content-Type": "application/json"},
        ) as response:
            result_model = None
            result_message = Message(role="assistant", content="")
            stream_iterator = response.aiter_lines()
            while True:
                chunk = await asyncio.wait_for(stream_iterator.__anext__(), timeout=10)
                if not chunk:
                    continue
                logger.debug(f"模型返回数据：{chunk}")
                chunk = chunk.lstrip("data:").strip()
                if chunk == "[DONE]":
                    break
                data = loads(chunk)
                if error := data.get("error"):
                    raise RequestException(error["message"])
                if data.get("usage"):
                    data["choices"][0].pop("delta")
                    data["choices"][0]["message"] = result_message
                    result_model = ChatChunkedCompletions(**data)
                    continue
                result_message.content += data["choices"][0]["delta"]["content"]
            if not result_model:
                if result_message.content:
                    result_message.content += "\n[模型返回数据异常]"
                choice = Choice(finish_reason="stop", message=result_message, index=0)
                result_model = ChatChunkedCompletions(id="ErrorCompletion", choices=[choice], created=0, model=model)
                raise RequestException("模型返回数据错误")
            return result_model

    @classmethod
    async def query_balance(cls) -> Balance:
        """查询账号余额"""
        response = await cls._client.get(f"{config.get_model_url('deepseek-chat')}/user/balance", headers=cls._headers)
        return Balance(**response.json())
