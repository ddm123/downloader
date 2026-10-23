"""Download service used by the video downloader GUI."""

import os
from typing import Any, Callable
import json
import time
import random
import shutil
import re
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse
import asyncio

import httpx
from bs4 import BeautifulSoup
import m3u8
from Crypto.Cipher import AES

def output(msg: str, outputter: Callable):
    outputter(msg)

def output_fail(msg: str, outputter: Callable):
    output(msg, outputter)

def output_success(msg: str, outputter: Callable):
    output(msg, outputter)

def output_warning(msg: str, outputter: Callable):
    output(msg, outputter)


def _convert_ts_to_mp4(
    video_path: Path,
    ffmpeg_path: str,
    log_callback: Callable[[str], None],
) -> None:
    mp4_path = video_path.with_suffix(".mp4")
    log_callback(f"正在转换为 MP4: {mp4_path}")
    result = subprocess.run(
        [
            ffmpeg_path,
            "-nostdin",
            "-loglevel",
            "error",
            "-n",
            "-i",
            str(video_path),
            "-c",
            "copy",
            str(mp4_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        details = result.stderr.strip() or f"ffmpeg 退出码: {result.returncode}"
        raise RuntimeError(f"转换 MP4 失败 ({video_path}): {details}")

    video_path.unlink()
    log_callback(f"✅ MP4 转换完成: {mp4_path}")
    log_callback(f"已删除原 TS 文件: {video_path}")


# ===================== 配置 =====================
class Config:
    def __init__(self) -> None:
        # 下载相关
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
        ]
        self.headers = {"accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6"}  # 基础头
        self.proxies = None  # 代理，如 {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}

        # 防反爬参数
        self.request_interval = 60          # 两次请求之间最小间隔（秒）
        self.retry_delay = 180              # 非200状态重试等待时间（秒），即3分钟
        self.max_retries = 10                # 最大重试次数
        self.use_random_ip = True           # 是否伪造 X-Forwarded-For
        self.use_random_ua = True           # 是否随机 UA

        # 下载分片参数
        self.max_workers = 50
        self.retries = 50
        self.timeout = 30
        self.chunk_size = 8192
        self.fill_missing = True
        self.keep_temp = False

    def get_user_agent(self) -> str:
        return random.choice(self.user_agents)

    def get_headers(self) -> dict:
        headers = self.headers.copy()
        headers["User-Agent"] = self.get_user_agent() if self.use_random_ua else self.user_agents[0]

        if self.use_random_ip:
            headers["X-Forwarded-For"] = f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"

        return headers

class VideoPageFetcher:
    def __init__(
        self,
        config: Config|None,
        log_callback: Callable[[str], None],
        progress_callback: Callable[[str, int, int], None],
    ):
        self.config = config or Config()
        self.last_request_url = None
        self.last_request_time = 0
        self.client = httpx.Client(proxy=self.config.proxies, timeout=self.config.timeout)
        self.log_callback = log_callback
        self.progress_callback = progress_callback

    def log(self, message: str) -> None:
        self.log_callback(message)

    async def fetch_segment_with_retry(self, client: httpx.AsyncClient, index: int, parts_dir: str, url: str, headers: dict={}) -> httpx.Response|None:
        max_retries = self.config.retries
        tmp_path = os.path.join(parts_dir, f"{index}.ts")
        p = Path(tmp_path)
        downloaded_size = p.stat().st_size if p.exists() else 0
        headers=self.config.get_headers()|headers

        for attempt in range(max_retries):
            wait_seconds = 60 if attempt>=5 else 2 ** (attempt + 1)
            try:
                if downloaded_size > 100:
                    # 尝试从断点续传
                    headers["Range"] = f"bytes={downloaded_size}-"
                async with client.stream("GET", url, headers=headers, timeout=self.config.timeout, follow_redirects=True) as resp:
                    mode = None
                    if resp.status_code == 200: # 不支持 Range，从头下载（覆盖）
                        mode = "wb"
                        downloaded_size = 0
                    elif resp.status_code == 206: # 支持 Range，追加写入
                        mode = "ab"

                    if mode is not None:
                        with p.open(mode) as out_f:
                            async for chunk in resp.aiter_bytes(self.config.chunk_size):
                                downloaded_size += out_f.write(chunk)
                        if downloaded_size == 0:
                            output_warning(f"#{index} 分片 {self.shorten_url(url)} 返回 空内容", self.log)
                            p.unlink(missing_ok=True)
                        elif attempt:
                            output_success(f"#{index} 分片 {self.shorten_url(url)} 重试 {attempt} 次后成功下载", self.log)
                        return resp  # 成功，返回
                    output_fail(f"#{index} 分片 {self.shorten_url(url)} 返回 {resp.status_code}，{wait_seconds}秒后重试 {attempt+1}/{max_retries}", self.log)
            except httpx.RequestError as e:
                output_fail(f"#{index} 分片 {self.shorten_url(url)} 请求异常: {e}，{wait_seconds}秒后重试 {attempt+1}/{max_retries}", self.log)

            # 等待一会再重试
            await asyncio.sleep(wait_seconds)

        output_fail(self.shorten_url(url) + " 重试耗尽，下载失败", self.log)
        return None  # 重试耗尽

    def fetch_with_retry(self, url: str, referer: str|None=None) -> httpx.Response|None:
        max_retries = self.config.max_retries
        for attempt in range(max_retries):
            headers = self.config.get_headers()
            if referer:
                headers["Referer"] = referer

            try:
                resp = self.client.get(url, headers=headers, timeout=self.config.timeout, follow_redirects=True)
                if resp.status_code == 200:
                    if attempt: output_success(f"{url} 重试 {attempt} 次后成功", self.log)
                    return resp

                output_fail(f"{url} 返回 {resp.status_code}，等待 {self.config.retry_delay} 秒后重试... {attempt+1}/{max_retries}", self.log)
            except httpx.RequestError as e:
                output_fail(f"{url} 请求异常: {e}，等待 {self.config.retry_delay} 秒后重试... {attempt+1}/{max_retries}", self.log)

            time.sleep(self.config.retry_delay)

        return None

    def download_enckey(self, key: m3u8.Key|None, m3u8_url: str) -> tuple[str, bytes, bytes|None]|None:
        if not key or not key.uri: return None

        self.log('密钥下载中...')
        response = self.fetch_with_retry(urljoin(m3u8_url, key.uri), m3u8_url)
        if response is None:
            raise RuntimeError("下载密钥（"+key.uri+"）失败")

        key_bytes = response.content.strip()
        if len(key_bytes) == 32 and all(ch in b"0123456789abcdefABCDEF" for ch in key_bytes):
            try:
                key_bytes = bytes.fromhex(key_bytes.decode("ascii"))
            except ValueError:
                raise RuntimeError(f"密钥十六进制解码失败: {key_bytes!r}")

        if len(key_bytes) != 16:
            raise RuntimeError(f"密钥({key_bytes!r})长度不是16字节")

        iv_bytes = None
        if iv_hex := key.iv:
            if iv_hex.startswith('0x'):
                iv_hex = iv_hex[2:]
            iv_bytes = bytes.fromhex(iv_hex)
        #elif key.method == "AES-128":
        #    iv_bytes = b"\x00" * 16

        return key.method, key_bytes, iv_bytes

    def download_segments(self, m3u8_obj: m3u8.M3U8, m3u8_url: str, output_dir: str, filename: str) -> int:
        segments: list[dict[str, Any]] = []
        enckeys: dict[str, tuple[str, bytes, bytes|None]|None] = dict()
        for segment in (m3u8_obj.segments or []):
            if not segment.uri: continue

            seg = {"url": segment.uri, "key": None}
            k = segment.key.uri if segment.key else None
            if not k or k in enckeys:
                seg["key"] = enckeys[k] if k else None
            else:
                enckeys[k] = seg["key"] = self.download_enckey(segment.key, m3u8_url)

            seg["url"] = urljoin(m3u8_url, seg["url"])
            segments.append(seg)

        total = len(segments)
        if total == 0:
            output_warning(f"没有找到任何分片: {filename}", self.log)
            return 0

        parts_dir = os.path.join(output_dir, ".parts_" + filename)
        os.makedirs(parts_dir, exist_ok=True)

        existing = set()
        for fname in os.listdir(parts_dir):
            if fname.endswith(".ts"):
                idx = int(fname[:-3])
                existing.add(idx)

        need_download = [i for i in range(total) if i not in existing]
        need_count = len(need_download)
        self.log(f"总共 {total} 个分片，已有 {len(existing)} 个，需要下载 {need_count} 个")

        if need_count > 0:
            async def download(segments: list[dict[str, Any]], need_download: list[int]):
                headers = {"Referer": m3u8_url}
                async with httpx.AsyncClient(proxy=self.config.proxies, timeout=self.config.timeout) as client:
                    need_downloads = [
                        need_download[i:i+self.config.max_workers]
                        for i in range(0, need_count, self.config.max_workers)
                    ] if need_count > self.config.max_workers else [need_download]
                    completed = 0
                    self.progress_callback("下载分片", completed, need_count)
                    for idxs in need_downloads:
                        tasks = [self.fetch_segment_with_retry(client, i, parts_dir, segments[i]["url"], headers) for i in idxs]
                        for coro in asyncio.as_completed(tasks):
                            await coro
                            completed += 1
                            self.progress_callback("下载分片", completed, need_count)

            asyncio.run(download(segments, need_download))

        self.merge_segments(m3u8_obj, m3u8_url, segments, output_dir, parts_dir, filename)
        return total

    @staticmethod
    def _unpad_pkcs7(data: bytes) -> bytes:
        if not data:
            return data
        pad_len = data[-1]
        if 1 <= pad_len <= 16 and data.endswith(bytes([pad_len]) * pad_len):
            return data[:-pad_len]
        return data

    def merge_segments(self, m3u8_obj: m3u8.M3U8, m3u8_url: str, segments: list[dict[str, Any]], output_dir: str, parts_dir: str, filename: str):
        if not segments:
            output_warning(f"没有分片可合并，跳过: {filename}", self.log)
            return

        video_path = os.path.join(output_dir, f"{filename}.ts")
        self.log(f"正在合并分片到 {video_path} ...")

        with open(video_path, "wb") as out_f:
            self.progress_callback("合并分片", 0, len(segments))
            for i, segment in enumerate(segments):
                tmp_path = os.path.join(parts_dir, f"{i}.ts")
                p = Path(tmp_path)
                if p.exists() and p.stat().st_size > 0:
                    with p.open("rb") as in_f:
                        chunk = in_f.read()
                        if segment["key"]:
                            method, key_bytes, iv_bytes = segment["key"]
                            if iv_bytes is None:
                                media_sequence = m3u8_obj.media_sequence or 0
                                iv_int = media_sequence + i
                                iv_bytes = iv_int.to_bytes(16, byteorder='big')
                            cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
                            decrypted = cipher.decrypt(chunk)
                            out_f.write(self._unpad_pkcs7(decrypted))
                        else:
                            out_f.write(chunk)

                    self.progress_callback("合并分片", i + 1, len(segments))
                else:
                    if self.config.fill_missing:
                        output_fail(f"⚠ 分片 {i} 缺失，开始重新去下载缺失的分片", self.log)
                        p.unlink(missing_ok=True)
                        self.download_segments(m3u8_obj, m3u8_url, output_dir, filename)
                        return
                    else:
                        output_fail(f"⚠ 分片 {i} 缺失，跳过写入", self.log)

        if self.config.keep_temp:
            self.log(f"临时文件保留在: {parts_dir}，可支持断点续传")
        else:
            shutil.rmtree(parts_dir, ignore_errors=True)

        output_success(f"✅ 视频下载完成: {video_path}", self.log)

    def get_segments(self, url: str, referer: str|None=None, seen_urls: set[str]|None=None) -> tuple[m3u8.M3U8, str, str|None]|None:
        if seen_urls is None:
            seen_urls = set()

        if url in seen_urls:
            output_warning(f"检测到循环引用 M3U8，停止递归: {url}", self.log)
            return None
        seen_urls.add(url)

        self.log("正在下载视频分片列表文件... " + url)
        response = self.fetch_with_retry(url, referer)
        if response is None:
            return None

        lines = response.text.strip()
        if lines == "":
            return None

        if "#EXT-X-STREAM-INF" in lines:
            variants: list[tuple[int, str]] = []
            current_bandwidth = None

            for line in lines.splitlines():
                line = line.strip()
                if not line:
                    continue

                if line.startswith("#EXT-X-STREAM-INF"):
                    match = re.search(r"BANDWIDTH=(\d+)", line, re.IGNORECASE)
                    current_bandwidth = int(match.group(1)) if match else None
                    continue

                if line.startswith("#"):
                    continue

                if current_bandwidth is not None:
                    variants.append((current_bandwidth, urljoin(url, line)))
                    current_bandwidth = None

            if not variants:
                self.log(f"未找到可用的子 M3U8 清单: {url}")
                return None

            best_bandwidth, best_url = max(variants, key=lambda item: item[0])
            self.log(f"检测到主清单，切换到更高码率子清单: {best_url} (bandwidth={best_bandwidth})")
            return self.get_segments(best_url, url, seen_urls)

        try:
            return m3u8.loads(lines), url, referer
        except Exception as e:
            output_fail(f"解析 M3U8 失败: {url}, error={e}", self.log)
            return None

    def get_video_url(self, url: str) -> tuple[str|None, str|None, str|None]:
        response = self.fetch_with_retry(url, self.last_request_url)
        html_content = "" if response is None else response.text

        if html_content == "":
            return None, None, None

        self.last_request_url = url

        if "thinkingali.com" in url:
            return self.get_thinkingali_video_url(url, BeautifulSoup(html_content, "html.parser"))

        return self.get_piank_video_url(url, BeautifulSoup(html_content, "html.parser"))

    def get_piank_video_url(self, url: str, soup: BeautifulSoup) -> tuple[str|None, str|None, str|None]:
        """ https://www.piank.cc/play/94E11G-1-1.html """

        script_tags = soup.find_all("script", type="text/javascript")
        target_script = None
        for script in script_tags:
            script_string = script.string
            if script_string and "var player_aaaa" in script_string:
                target_script = script
                break

        video_url = None
        video_next_url = None
        link_next = None

        if target_script:
            player_data = target_script.string.strip() if target_script.string else None
            if player_data:
                try:
                    player_json = player_data.split("var player_aaaa=")[1]
                    player_obj = json.loads(player_json)
                    video_url = player_obj.get("url")
                    video_next_url = player_obj.get("url_next")
                    link_next = player_obj.get("link_next")
                    if link_next:
                        link_next = urljoin(url, link_next)
                except Exception as e:
                    output_fail(f"解析 player_aaaa 数据失败: {e}", self.log)
            else:
                output_fail("Could not find the video URL.", self.log)
        else:
            output_fail("Could not find the target <script> tag.", self.log)

        return video_url, video_next_url, link_next

    def get_thinkingali_video_url(self, url: str, soup: BeautifulSoup) -> tuple[str|None, str|None, str|None]:
        """ https://www.thinkingali.com/video/19539-2-185.html """

        script = soup.find('script', string=re.compile(r'\bnow\s*=\s*["\']|\bnextPage\s*=\s*["\']'))
        if not script:
            output_fail("Could not find the target <script> tag.", self.log)
            return None, None, None

        content = script.string
        pattern = re.compile(r'\b(?:var\s+)?(\w+)\s*=\s*(["\'])(.*?)\2', re.DOTALL)
        matches = {m[0]: m[2] for m in pattern.findall(content)} # type: ignore

        if not matches:
            output_fail("Could not find the video URL.", self.log)
            return None, None, None

        return (
            urljoin(url, video_url) if (video_url := matches.get('now')) else None,
            urljoin(url, video_next_url) if (video_next_url := matches.get('next')) else None,
            urljoin(url, link_next) if video_next_url and (link_next := matches.get('nextPage')) else None
        )

    def shorten_url(self, url: str, min_length: int|None = None) -> str:
        # 如果设置了最小长度且当前长度未超过阈值，直接返回
        if min_length is not None and len(url) <= min_length:
            return url

        try:
            parsed = urlparse(url)
            index = parsed.path.rfind('/', 0, -1)
            if index <= 0:
                return url

            new_path = parsed.path[index:]

            # 重新组合 URL（丢弃查询参数和片段，如需要可保留，这里按原需求仅保留协议+域名+路径）
            short_url = f"{parsed.scheme}://{parsed.netloc}/...{new_path}"
            return short_url

        except Exception:
            # 解析失败时返回原 URL
            return url


def download_video(
    url: str,
    output_dir: str,
    log_callback: Callable[[str], None],
    progress_callback: Callable[[str, int, int], None],
    ffmpeg_path: str | None = None,
) -> None:
    """Download a video and report all output through the GUI callbacks."""
    os.makedirs(output_dir, exist_ok=True)
    fetcher = VideoPageFetcher(
        Config(),
        log_callback=log_callback,
        progress_callback=progress_callback,
    )
    try:
        while True:
            fetcher.log(f"\n========== 处理页面: {url} ==========")
            is_video_url = url.endswith(".m3u8")
            if is_video_url:
                video_url = url
                video_next_url = link_next = ""
            else:
                video_url, video_next_url, link_next = fetcher.get_video_url(url)

            if video_url:
                result = fetcher.get_segments(video_url, url)
                if result is not None:
                    if is_video_url:
                        filename = time.strftime("%Y%m%d%H%M%S")
                    else:
                        path = Path(urlparse(url).path)
                        filename = path.stem if path.stem else "video"
                    fetcher.download_segments(result[0], result[1], output_dir, filename)
                    if ffmpeg_path:
                        _convert_ts_to_mp4(
                            Path(output_dir) / f"{filename}.ts",
                            ffmpeg_path,
                            fetcher.log,
                        )
                else:
                    output_fail("下载视频分片列表文件("+video_url+")失败", fetcher.log)
            elif video_url is None:
                output_fail("请求 " + url + " 失败", fetcher.log)
            else:
                output_fail("未获取到视频 M3U8，可能页面结构变化或已失效", fetcher.log)

            if link_next:
                url = link_next
                time.sleep(2)
            else:
                fetcher.log("没有下一集，下载结束。")
                break
    finally:
        fetcher.client.close()
