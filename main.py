from astrbot.api.all import *
from astrbot.api.message_components import *
import aiohttp
import asyncio
import time
from typing import Dict, Optional
from astrbot.api import logger
import ssl
from collections import defaultdict
import shutil

# 用于跟踪每个用户的状态，防止超时或重复请求
USER_STATES: Dict[str, Optional[float]] = {}

@register("saveImg", "Bocity", "这是 AstrBot 的保存图片插件，可以帮你保存你想存储的图片。", "1.0.0", "https://github.com/Bocity/astrbot_plugin_saveimg")
class SaveImg(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.save_path = config.get("savePath", "")  # 获取配置中的保存路径
        self.user_file_msg_buffer = defaultdict(list)
    
    async def download_file(self, image_url: str, workplace_path: str, filename: str) -> str:
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
                image_path = os.path.join(workplace_path, f"{filename}")
                with open(image_path, 'wb') as f:
                    f.write(await resp.read())
                return f"{filename}"
    async def copy_local_file(self, src_path, dst_path):
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, 
                lambda: shutil.copy(src_path, dst_path)
            )
            return dst_path
        except Exception as e:
            logger.warning(f"文件复制失败 {src_path} -> {dst_path}: {str(e)}")
            return None

    async def process_nested_messages(self, messages, client):
        media_files = []
        saveTime = time.time()
        img_idx = 1
        video_idx = 1

        def recursive_collect(message_list):
            nonlocal img_idx, video_idx
            tasks = []
            
            for msg in message_list:
                # 处理消息主体
                if 'message' in msg:
                    for comp in msg['message']:
                        # 图片处理
                        if comp.get('type') == 'image':
                            image_data = comp.get('data', {})
                            if image_url := image_data.get('url'):
                                clean_url = image_url.replace('&amp;', '&')
                                tasks.append({
                                    "type": "image",
                                    "url": clean_url,
                                    "filename": f"img_{saveTime}_{img_idx}.jpg"
                                })
                                img_idx += 1
                                
                        # 视频处理
                        elif comp.get('type') == 'video':
                            video_data = comp.get('data', {})
                            video_url = video_data.get('path')
                            if video_url:
                                tasks.append({
                                    "type": "video",
                                    "file": video_data.get('file'),
                                    "url": video_url,
                                    "filename": f"video_{saveTime}_{video_idx}.mp4"
                                })
                                video_idx += 1
                                
                        # 递归处理嵌套转发
                        elif comp.get('type') == 'forward' and 'data' in comp:
                            if forward_content := comp['data'].get('content'):
                                tasks.extend(recursive_collect(forward_content))
                                
                # 处理content直连的情况
                elif isinstance(msg, dict) and 'content' in msg:
                    tasks.extend(recursive_collect(msg['content']))
                    
            return tasks

        try:
            # 收集所有媒体任务
            all_tasks = recursive_collect(messages)
            if not all_tasks:
                return []

            # 并行处理下载
            download_coros = []
            for task in all_tasks:
                # HTTP下载
                if task['url'].startswith('http'):
                    download_coros.append(
                        self.download_file(
                            task['url'],
                            self.save_path,
                            task['filename']
                        )
                    )
                # 本地文件复制
                elif task['url'].startswith('/'):
                    payloads = {
                        "file": task['file'],
                    }
                    ret = await client.api.call_action('get_file', **payloads)
                    logger.info(f"文件详细内容: {ret}")
                    download_coros.append(
                        self.copy_local_file(
                            task['url'],
                            os.path.join(self.save_path, task['filename'])
                        )
                    )

            # 执行所有任务
            results = await asyncio.gather(*download_coros, return_exceptions=True)
            
            # 处理结果
            success_files = []
            for result, task in zip(results, all_tasks):
                if not isinstance(result, Exception) and result:
                    success_files.append({
                        "type": task['type'],
                        "path": result
                    })
            
            return success_files

        except Exception as e:
            logger.error(f"媒体处理失败: {str(e)}")
            return []
    # 处理"保存"命令
    @command("保存")
    @event_message_type(EventMessageType.PRIVATE_MESSAGE)
    async def save_image(self, event: AstrMessageEvent):
        # 如果未配置API Key，提醒用户
        if not self.save_path:
            yield event.plain_result("杂鱼♥还没告诉姐姐保存到哪里哦~")
            return
        user_id = event.get_sender_id()  # 获取用户ID
        USER_STATES[user_id] = time.time()  # 记录用户请求的时间
        yield event.plain_result("杂鱼~还得靠我呢!把你要存的东西都交给我吧yo~")  # 提示用户发送图片

    # 处理"不保存"命令
    @command("不保存")
    @event_message_type(EventMessageType.PRIVATE_MESSAGE)
    async def exit_image(self, event: AstrMessageEvent):
        # 如果超时，删除用户状态并通知用户
        user_id = event.get_sender_id()  # 获取用户ID
        if user_id in USER_STATES:
            del USER_STATES[user_id]
            yield event.plain_result("不帮你保存了哦，杂鱼~")
        else:
            yield event.plain_result("杂鱼~你没有保存哦")

     # 处理所有消息类型的事件
    @event_message_type(EventMessageType.PRIVATE_MESSAGE)
    async def on_private_message(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()  # 获取发送者的ID
        if user_id not in USER_STATES:  # 如果用户没有发起请求，跳过
            return
        # 如果未配置API Key，提醒用户
        if not self.save_path:
            yield event.plain_result("杂鱼♥还没告诉姐姐保存到哪里哦~")
            return
        logger.info(event.message_obj.raw_message) # 平台下发的原始消息在这里
        logger.info(event.message_obj.message) # AstrBot 解析出来的消息链内容
        ForwardFlag = 0
        for comp in event.message_obj.message:
            if isinstance(comp, Forward):
                ForwardFlag += 1
        if ForwardFlag > 0:
            if event.get_platform_name() == "aiocqhttp":
                # qq
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
                assert isinstance(event, AiocqhttpMessageEvent)
                client = event.bot # 得到 client
                payloads = {
                    "message_id": event.message_obj.message_id,
                }
                try:
                    ret = await client.api.call_action('get_forward_msg', **payloads) # 调用 协议端  API
                    logger.info(f"转发消息内容: {ret}")
                    saved_media = await self.process_nested_messages(ret['messages'], client)
                    if saved_media:
                        img_count = sum(1 for m in saved_media if m['type'] == 'image')
                        video_count = sum(1 for m in saved_media if m['type'] == 'video')
                        
                        msg = []
                        if img_count > 0:
                            msg.append(f"保存了{img_count}张图片")
                        if video_count > 0:
                            msg.append(f"{video_count}个视频")
                        
                        yield event.plain_result(f"{'和'.join(msg)}都存好啦~ 杂鱼！")
                    else:
                        yield event.plain_result("没有找到可以保存的内容呢，笨蛋！")
                    
                except Exception as e:
                    logger.error(f"处理失败: {traceback.format_exc()}")
                    yield event.plain_result("呜...保存失败了，杂鱼程序员快检查日志！")
            return

            
        # 检查消息中是否包含图片
        imgFlag = 0
        images = [c for c in event.message_obj.message if isinstance(c, Image)]
        if not images:  # 如果没有图片，跳过
            imgFlag += 1
        
        videoFlag = 0
        videos = [c for c in event.message_obj.message if isinstance(c, Video)]
        if not videos:
            videoFlag += 1
        if videoFlag > 0 and imgFlag > 0:
            return
        
        # 图片
        if imgFlag == 0:

            images = []
            saveTime = time.time()
            idx = 1
            try:
                for comp in event.message_obj.message:
                    if isinstance(comp, Image):
                        image_url = comp.url if comp.url else comp.file
                        if image_url.startswith("http"):
                            image_path = await self.download_file(image_url, self.save_path, f"img_{saveTime}_{idx}.jpg")
                            idx += 1
                            if image_path:
                                images.append(image_path)
                # 发送最终的结果，直接传递消息列表
                logger.info(f"保存成功: {images}")
                yield event.plain_result("图片帮你存下来了哦~杂鱼~")
                    
            except Exception as e:  # 捕获异常并返回错误信息
                logger.info(f"保存失败: {str(e)}")
                yield event.plain_result("保存失败了哦，杂鱼程序员又写bug了！")

        # 视频
        if videoFlag == 0:
            videos = []
            saveTime = time.time()
            idx = 1
            try:
                for comp in event.message_obj.message:
                    if isinstance(comp, Video):
                        video_url = comp.url if comp.url else comp.path
                        if video_url.startswith("http"):
                            video_path = await self.download_file(video_url, self.save_path, f"video_{saveTime}_{idx}.mp4")
                            idx += 1
                            if video_path:
                                videos.append(video_path)
                        if video_url.startswith("/"):
                            file_name = os.path.basename(video_url)
                            file_path = os.path.join(self.save_path, file_name)
                            shutil.copy(video_url, file_path)
                            videos.append(file_path)
                logger.info(f"保存成功: {video_path}")
                yield event.plain_result("视频帮你存下来了哦~杂鱼~")
            except Exception as e:  # 捕获异常并返回错误信息
                logger.info(f"保存失败: {str(e)}")
                yield event.plain_result("保存失败了哦，杂鱼程序员又写bug了！")