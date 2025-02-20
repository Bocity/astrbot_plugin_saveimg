from astrbot.api.all import *
from astrbot.api.message_components import *
import aiohttp
import asyncio
import time
from typing import Dict, Optional
from astrbot.api import logger
import ssl

# 用于跟踪每个用户的状态，防止超时或重复请求
USER_STATES: Dict[str, Optional[float]] = {}

@register("saveImg", "Bocity", "这是 AstrBot 的保存图片插件，可以帮你保存你想存储的图片。", "1.0.0", "https://github.com/Bocity/astrbot_plugin_saveimg")
class SaveImg(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.save_path = config.get("savePath", "")  # 获取配置中的保存路径
    
    async def download_image(self, image_url: str, workplace_path: str, filename: str) -> str:
        '''Download image from url to workplace_path'''
        ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2  # 强制 TLSv1.2+
        ssl_context.options |= (
            ssl.OP_NO_SSLv2 | 
            ssl.OP_NO_SSLv3 |
            ssl.OP_NO_TLSv1 |
            ssl.OP_NO_TLSv1_1
        )
        ssl_context.set_ciphers("AES128-GCM-SHA256")  # 精确匹配服务器加密套件
        #ssl_context.set_ciphers("HIGH:!aNULL:!eNULL:!MD5")
    # 添加浏览器级 User-Agent 头
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*"
            }
        async with aiohttp.ClientSession(trust_env=False, headers=headers,connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            async with session.get(image_url) as resp:
                if resp.status != 200:
                    return ""
                image_path = os.path.join(workplace_path, f"{filename}.jpg")
                with open(image_path, 'wb') as f:
                    f.write(await resp.read())
                return f"{filename}.jpg"

    # 处理"保存"命令
    @command("保存")
    async def save_image(self, event: AstrMessageEvent):
        # 如果未配置API Key，提醒用户
        if not self.save_path:
            yield event.plain_result("杂鱼♥还没告诉姐姐保存到哪里哦~")
            return
        user_id = event.get_sender_id()  # 获取用户ID
        USER_STATES[user_id] = time.time()  # 记录用户请求的时间
        yield event.plain_result("杂鱼~还得靠我呢!把你要存的东西都交给我吧yo~")  # 提示用户发送图片

    # 处理"退出保存"命令
    @command("退出保存")
    async def exit_image(self, event: AstrMessageEvent):
        # 如果超时，删除用户状态并通知用户
        user_id = event.get_sender_id()  # 获取用户ID
        if user_id in USER_STATES:
            del USER_STATES[user_id]
            yield event.plain_result("不帮你保存了哦，杂鱼~")
        else
            yield event.plain_result("杂鱼~你没有保存哦")

     # 处理所有消息类型的事件
    @event_message_type(EventMessageType.ALL)
    async def handle_image(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()  # 获取发送者的ID
        if user_id not in USER_STATES:  # 如果用户没有发起请求，跳过
            return
        
        # 检查消息中是否包含图片
        images = [c for c in event.message_obj.message if isinstance(c, Image)]
        if not images:  # 如果没有图片，跳过
            return

        # 如果未配置API Key，提醒用户
        if not self.save_path:
            yield event.plain_result("杂鱼♥还没告诉姐姐保存到哪里哦~")
            return
        
        # 图片
        images = []
        saveTime = time.time()
        idx = 1
        try:
            for comp in event.message_obj.message:
                if isinstance(comp, Image):
                    image_url = comp.url if comp.url else comp.file
                    if image_url.startswith("http"):
                        image_path = await self.download_image(image_url, self.save_path, f"img_{saveTime}_{idx}")
                        idx += 1
                        if image_path:
                            images.append(image_path)
            # 发送最终的结果，直接传递消息列表
            logger.info(f"保存成功: {images}")
            yield event.plain_result("全部帮你存下来了哦~杂鱼~")
                
        except Exception as e:  # 捕获异常并返回错误信息
            logger.info(f"保存失败: {str(e)}")
            yield event.plain_result("保存失败了哦，杂鱼程序员又写bug了！")
