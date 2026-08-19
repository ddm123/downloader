import urllib.request
import urllib.error
import urllib.parse
import html.parser
import os
import time
import re
import http.client

class RomDownloader:
    def __init__(self, base_url, download_dir="downloads"):
        self.base_url = base_url
        self.download_dir = download_dir
        
        # 设置请求头
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    
    def _make_request(self, url, method='GET', headers=None, data=None):
        """使用urllib发送HTTP请求"""
        if headers is None:
            headers = {}
        
        # 合并headers
        request_headers = {**self.headers, **headers}
        
        # 创建请求
        if data:
            data = urllib.parse.urlencode(data).encode()
        
        req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        
        try:
            response = urllib.request.urlopen(req, timeout=30)
            return response
        except urllib.error.HTTPError as e:
            return e  # 返回HTTP错误对象
        except Exception as e:
            raise e
    
    def download_file_with_retry(self, url, filename, system_dir, max_retries=3):
        """下载文件，支持重试和断点续传"""
        # 创建系统目录
        os.makedirs(system_dir, exist_ok=True)
        filepath = os.path.join(system_dir, filename)
        
        for attempt in range(max_retries):
            try:
                success = self._download_file_resume(url, filepath, attempt + 1)
                if success:
                    return True
                else:
                    if attempt < max_retries - 1:
                        print(f"🔄 重试下载 ({attempt + 2}/{max_retries})")
                        time.sleep(2)
                    
            except Exception as e:
                print(f"❌ 下载出错: {e}")
                if attempt < max_retries - 1:
                    print(f"🔄 准备重试 ({attempt + 2}/{max_retries})")
                    time.sleep(2)
        
        print(f"💥 下载失败，已重试{max_retries}次: {os.path.basename(system_dir)}/{filename}")
        
        # 如果最终失败，删除可能损坏的空白文件
        if os.path.exists(filepath) and os.path.getsize(filepath) == 0:
            try:
                os.remove(filepath)
            except:
                pass
            
        return False
    
    def _download_file_resume(self, url, filepath, attempt_num):
        """支持断点续传的文件下载"""
        try:
            # 获取已下载的文件大小
            existing_size = 0
            file_exists = os.path.exists(filepath)
            
            if file_exists:
                existing_size = os.path.getsize(filepath)
                if existing_size > 0:
                    print(f"📁 发现已下载文件: {self._format_size(existing_size)}")
            
            # 获取服务器文件信息
            server_total_size = 0
            try:
                # 使用HEAD请求获取文件信息
                head_response = self._make_request(url, method='HEAD')
                if hasattr(head_response, 'status') and head_response.status == 200:
                    server_total_size = int(head_response.headers.get('Content-Length', 0))
                    print(f"🌐 服务器文件大小: {self._format_size(server_total_size)}")
            except Exception as e:
                print(f"⚠️ 无法获取服务器文件信息: {e}")
                raise
            
            headers = {}
            resume_download = False
            
            if server_total_size > 0:
                if existing_size == server_total_size:
                    # ✅ 情况1: 文件已完整下载
                    print(f"⏭️ 文件已完整，跳过下载")
                    return True
                    
                elif existing_size > 0 and existing_size < server_total_size:
                    # ✅ 情况2: 文件已部分下载，需要续传
                    headers['Range'] = f'bytes={existing_size}-'
                    resume_download = True
                    remaining_size = server_total_size - existing_size
                    print(f"🔄 继续下载: 剩余 {self._format_size(remaining_size)}")
                    
                elif existing_size > server_total_size:
                    # ✅ 情况3: 服务器文件更新，删除重下
                    print(f"🔄 服务器文件已更新，删除旧文件重新下载")
                    os.remove(filepath)
                    existing_size = 0
                    file_exists = False
                    
            else:
                # 无法获取服务器大小的情况
                if file_exists and existing_size > 1024:
                    print(f"⚠️ 无法验证服务器大小，但文件已存在: {self._format_size(existing_size)}")
                    return True
                elif file_exists:
                    print(f"🔄 文件太小可能不完整，重新下载")
                    os.remove(filepath)
                    existing_size = 0
            
            print(f"📥 下载({attempt_num}): {os.path.basename(os.path.dirname(filepath))}/{os.path.basename(filepath)}")
            
            # 执行下载
            response = self._make_request(url, headers=headers)
            
            # 检查响应状态
            if hasattr(response, 'status'):
                status_code = response.status
            else:
                status_code = 200  # urlopen成功默认是200
            
            # 处理服务器不支持断点续传的情况
            if resume_download and status_code != 206:
                print("⚠️ 服务器不支持断点续传，重新下载")
                try:
                    os.remove(filepath)  # 删除可能损坏的文件
                except:
                    pass
                existing_size = 0
                resume_download = False
                response = self._make_request(url)
            
            # 检查是否是错误响应
            if hasattr(response, 'status') and response.status >= 400:
                raise urllib.error.HTTPError(url, response.status, response.reason, response.headers, response)
            
            # 确定总文件大小
            total_size = 0
            if resume_download and 'Content-Range' in response.headers:
                content_range = response.headers['Content-Range']
                total_size = int(content_range.split('/')[-1])
            else:
                total_size = int(response.headers.get('Content-Length', 0))
                if resume_download:
                    total_size += existing_size
            
            # 下载文件
            mode = 'ab' if resume_download else 'wb'
            downloaded = existing_size if resume_download else 0
            
            with open(filepath, mode) as file:
                start_time = time.time()
                last_update = start_time
                
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    
                    file.write(chunk)
                    downloaded += len(chunk)
                    
                    # 显示进度（限制更新频率）
                    current_time = time.time()
                    if current_time - last_update > 0.5 or downloaded == total_size:
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            elapsed = current_time - start_time
                            speed = downloaded / elapsed / 1024 if elapsed > 0 else 0
                            print(f"\r📊 进度: {percent:.2f}% ({self._format_size(downloaded)}/{self._format_size(total_size)}) - {speed:.2f}KB/s", end='', flush=True)
                        last_update = current_time
            
            # 最终完整性验证
            final_size = os.path.getsize(filepath)
            if total_size > 0:
                if final_size == total_size:
                    print(f"\n✅ 下载完成，文件大小验证通过")
                    return True
                else:
                    print(f"\n❌ 文件验证失败: {self._format_size(final_size)} != {self._format_size(total_size)}")
                    # 删除不完整文件，让下次重试可以重新开始
                    try:
                        os.remove(filepath)
                    except:
                        pass
                    return False
            else:
                # 无法验证，但文件不为空就认为成功
                if final_size > 0:
                    print(f"\n✅ 下载完成: {self._format_size(final_size)}")
                    return True
                else:
                    print(f"\n❌ 下载失败: 文件为空")
                    return False
            
        except urllib.error.URLError as e:
            print(f"\n❌ 网络错误: {e}")
            return False
        except IOError as e:
            print(f"\n❌ 文件写入错误: {e}")
            return False
        except Exception as e:
            print(f"\n❌ 下载错误: {e}")
            return False
    
    def _format_size(self, size_bytes):
        """格式化文件大小显示"""
        if size_bytes == 0:
            return "0B"
        
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        
        return f"{size_bytes:.1f}{size_names[i]}"
    
    def get_system_from_url(self, rom_page_url):
        """从URL中提取系统名称"""
        match = re.search(r'/roms/([^/]+)/[^/]+\.htm', rom_page_url)
        if match:
            return match.group(1)
        return "unknown"
    
    def get_download_links(self, rom_page_url, attempt_num=1):
        """获取ROM页面的下载链接"""
        try:
            response = self._make_request(rom_page_url)
            if hasattr(response, 'status') and response.status >= 400:
                raise urllib.error.HTTPError(rom_page_url, response.status, response.reason, response.headers, response)
            
            html_content = response.read().decode('utf-8')
            
            # 使用自定义解析器解析下载链接
            parser = LinkParser()
            parser.feed(html_content)
            download_links = []
            
            for link_info in parser.get_download_links():
                href = link_info['href']
                filename = link_info['text'] or os.path.basename(href) or f"unknown_{len(download_links)}.zip"
                
                # 处理URL
                if href.startswith('//'):
                    full_url = 'https:' + href
                elif href.startswith('/'):
                    full_url = urllib.parse.urljoin(self.base_url, href)
                elif not href.startswith(('http://', 'https://')):
                    full_url = urllib.parse.urljoin(rom_page_url, href)
                else:
                    full_url = href
                
                # 清理文件名
                filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
                if not filename.endswith(('.zip', '.rar', '.7z')):
                    filename += '.zip'
                
                download_links.append((full_url, filename))
            
            return download_links
            
        except Exception as e:
            if attempt_num < 3:
                print(f"🔄 获取下载链接失败，重试 ({attempt_num}/3): {e}")
                time.sleep(2)
                return self.get_download_links(rom_page_url, attempt_num + 1)

            print(f"❌ 获取下载链接失败: {e}")
            return []
    
    def download_all_roms(self, max_roms=None):
        """下载所有ROM文件，按系统分类保存"""
        try:
            print("🚀 开始ROM下载任务")
            print(f"📁 下载目录: {os.path.abspath(self.download_dir)}")
            
            # 获取主页面
            response = self._make_request(self.base_url)
            if hasattr(response, 'status') and response.status >= 400:
                raise urllib.error.HTTPError(self.base_url, response.status, response.reason, response.headers, response)
            
            html_content = response.read().decode('utf-8')
            
            # 使用自定义解析器解析ROM列表
            parser = RomListParser()
            parser.feed(html_content)
            rom_entries = parser.get_rom_entries()
            
            print(f"🎮 找到 {len(rom_entries)} 个ROM")
            print("⚡ 支持断点续传，失败自动重试3次")
            
            downloaded_count = 0
            error_count = 0
            
            for i, rom_entry in enumerate(rom_entries):
                if max_roms and downloaded_count >= max_roms:
                    print(f"⏹️ 达到数量限制: {max_roms}")
                    break
                
                try:
                    game_title = rom_entry['title']
                    rom_page_path = rom_entry['href']
                    
                    # 构建完整URL
                    rom_page_url = urllib.parse.urljoin(self.base_url, rom_page_path)
                    
                    # 构建下载页面URL
                    if rom_page_path.endswith('.htm'):
                        download_page_path = rom_page_path[:-4] + '-download.htm'
                    else:
                        download_page_path = rom_page_path + '-download.htm'
                    
                    download_page_url = urllib.parse.urljoin(self.base_url, download_page_path)
                    
                    # 获取系统名称
                    system_name = self.get_system_from_url(rom_page_url)
                    system_dir = os.path.join(self.download_dir, system_name)
                    
                    print(f"\n🎯 [{i+1}/{len(rom_entries)}] {game_title}")
                    print(f"📂 系统: {system_name}")
                    
                    # 获取下载链接
                    download_links = self.get_download_links(download_page_url)
                    
                    if not download_links:
                        print("⚠️ 无下载链接")
                        error_count += 1
                        continue
                    
                    print(f"📎 找到 {len(download_links)} 个文件")
                    
                    # 下载每个文件
                    for file_url, filename in download_links:
                        if self.download_file_with_retry(file_url, filename, system_dir):
                            downloaded_count += 1
                        else:
                            error_count += 1
                        
                        time.sleep(1)  # 请求间隔
                
                except Exception as e:
                    print(f"❌ 处理失败: {e}")
                    error_count += 1
                    continue
            
            print(f"\n🎉 任务完成! 成功: {downloaded_count}, 失败: {error_count}")
            
        except Exception as e:
            print(f"💥 程序执行失败: {e}")

class LinkParser(html.parser.HTMLParser):
    """自定义HTML解析器，用于提取下载链接"""
    def __init__(self):
        super().__init__()
        self.download_links = []
        self.current_tag = None
        self.current_attrs = {}
    
    def handle_starttag(self, tag, attrs):
        self.current_tag = tag
        self.current_attrs = dict(attrs)
        
        if tag == 'a' and self.current_attrs.get('target') == '_blank':
            href = self.current_attrs.get('href')
            if href:
                self.download_links.append({
                    'href': href,
                    'text': ''
                })
    
    def handle_data(self, data):
        if (self.current_tag == 'a' and 
            self.current_attrs.get('target') == '_blank' and
            self.download_links):
            # 为最后一个链接设置文本
            self.download_links[-1]['text'] = data.strip()
    
    def get_download_links(self):
        """获取解析到的下载链接"""
        return self.download_links

class RomListParser(html.parser.HTMLParser):
    """解析ROM列表页面"""
    def __init__(self):
        super().__init__()
        self.rom_entries = []
        self.current_div_class = None
        self.current_div_attrs = {}
        self.current_a_href = None
        self.current_a_text = None
        self.in_target_div = False
        self.in_target_a = False
    
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        
        if tag == 'div':
            class_name = attrs_dict.get('class', '')
            if class_name and 'rom-system-index-entry-full' in class_name:
                self.in_target_div = True
                self.current_div_attrs = attrs_dict
                self.current_div_class = class_name
        
        elif tag == 'a' and self.in_target_div:
            self.in_target_a = True
            self.current_a_href = attrs_dict.get('href')
            self.current_a_text = ''
    
    def handle_data(self, data):
        if self.in_target_a:
            self.current_a_text += data
    
    def handle_endtag(self, tag):
        if tag == 'div' and self.in_target_div:
            if self.current_a_href:
                self.rom_entries.append({
                    'title': self.current_div_attrs.get('title', '未知游戏'),
                    'href': self.current_a_href,
                    'text': self.current_a_text.strip()
                })
            self.in_target_div = False
            self.current_div_attrs = {}
            self.current_a_href = None
            self.current_a_text = None
        
        elif tag == 'a' and self.in_target_a:
            self.in_target_a = False
    
    def get_rom_entries(self):
        """获取解析到的ROM条目"""
        return self.rom_entries

def main():
    # 配置参数
    BASE_URL = 'https://www.winkawaks.org/roms/full-rom-list.htm'
    DOWNLOAD_DIR = "rom_downloads"
    MAX_ROMS = None  # 测试用，设为None下载全部
    
    downloader = RomDownloader(BASE_URL, DOWNLOAD_DIR)
    downloader.download_all_roms(max_roms=MAX_ROMS)

if __name__ == "__main__":
    main()
