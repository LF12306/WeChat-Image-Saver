import wxauto
import time
import os
import threading
import json
import queue
import re
import uuid
import hashlib
import sys  # 新增这行导入
import shutil
from wxauto import WeChat
from tkinter import *
from tkinter import ttk, filedialog
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class WxFileHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback

    def on_created(self, event):
        if not event.is_directory:
            self.callback(event.src_path)

class WeChatImageSaver:
    def __init__(self):
        # 先初始化所有属性
        self.auto_start = False  # 必须放在最前面
        self.config_path = "wx_config.json"
        self.wx = wxauto.WeChat()
        self.stop_event = threading.Event()
        self.listen_list = []
        self.save_path = os.getcwd()
        self.wxauto_default_path = os.path.expanduser("wxauto文件")
        self.sender_mapping = {}
        self.file_queue = queue.Queue()
        self.observer = Observer()
        self.lock = threading.Lock()
        
        # 再初始化UI
        self.root = Tk()
        self.root.title("微信图片自动保存工具 v1.2")
        # 设置窗口图标（关键修改点）
        try:
            self.root.iconbitmap(self._get_icon_path('app.ico'))
        except Exception as e:
            print(f"图标加载失败: {str(e)}")
        self._create_ui()  # 此时self.auto_start已存在

        
        # 后续初始化
        self.load_config()
        # 创建监控目录（此时可以安全使用log方法）
        if not os.path.exists(self.wxauto_default_path):
            try:
                os.makedirs(self.wxauto_default_path, exist_ok=True)
                self.log(f"已创建监控目录：{self.wxauto_default_path}")
            except Exception as e:
                self.log(f"无法创建监控目录：{str(e)}", error=True)
                self.root.destroy()  # 关闭程序
                raise
        

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # 延迟的自动启动检查
        if self.auto_start and self.listen_list:
            self.root.after(1000, self._safe_auto_start)
        
        # 启动其他组件
        threading.Thread(target=self._process_queue, daemon=True).start()
        self._start_file_watcher()
        self.log("初始化完成")

    def _get_icon_path(self, icon_name):
        """获取图标绝对路径（兼容开发环境和打包环境）"""
        base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
        return os.path.join(base_path, icon_name)

    def _create_ui(self):
        # 先创建所有UI元素
        self.auto_start_var = BooleanVar(value=self.auto_start)  # 现在可以安全使用
        # 监听列表
        self.list_frame = ttk.LabelFrame(self.root, text="监听列表")
        self.listbox = Listbox(self.list_frame, width=30)
        self.entry = ttk.Entry(self.list_frame)
        self.add_btn = ttk.Button(self.list_frame, text="添加", command=self.add_listener)
        self.del_btn = ttk.Button(self.list_frame, text="删除", command=self.del_listener)
        
        # 保存路径
        self.path_frame = ttk.LabelFrame(self.root, text="保存路径")
        self.path_label = ttk.Label(self.path_frame, text=f"当前路径：{self.save_path}")
        self.path_btn = ttk.Button(self.path_frame, text="修改路径", command=self.choose_path)
        
        # 控制按钮
        self.control_frame = ttk.Frame(self.root)
        self.start_btn = ttk.Button(self.control_frame, text="启动", command=self.start_listen)
        self.stop_btn = ttk.Button(self.control_frame, text="停止", command=self.stop_listen, state=DISABLED)

        self.auto_check = ttk.Checkbutton(
            self.control_frame, 
            text="工具启动后立即自动监听",
            variable=self.auto_start_var,
            command=self._toggle_auto_start
        )        
        self.auto_check.pack(side=LEFT, padx=5)




        # 日志区域
        self.log_frame = ttk.LabelFrame(self.root, text="运行日志")
        self.log_text = Text(self.log_frame, height=10)
        self.scroll = ttk.Scrollbar(self.log_frame, command=self.log_text.yview)
        
        # 布局
        # 监听列表布局
        self.list_frame.pack(padx=10, pady=5, fill=BOTH)
        self.listbox.pack(side=LEFT, padx=5)
        self.entry.pack(pady=5)
        self.add_btn.pack(pady=2)
        self.del_btn.pack(pady=2)
        
        # 路径选择布局
        self.path_frame.pack(padx=10, pady=5, fill=BOTH)
        self.path_label.pack(side=LEFT)
        self.path_btn.pack(side=RIGHT)
        
        # 控制按钮布局
        self.control_frame.pack(pady=10)
        self.start_btn.pack(side=LEFT, padx=5)
        self.stop_btn.pack(side=LEFT)
        
        # 日志布局
        self.log_frame.pack(padx=10, pady=5, fill=BOTH)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        self.scroll.pack(side=RIGHT, fill=Y)
        self.log_text.config(yscrollcommand=self.scroll.set)

    
    def log(self, message, error=False):
        def update_log():
            tag = 'error' if error else 'info'
            self.log_text.tag_config(tag, foreground='red' if error else '#333')
            self.log_text.insert(END, f"[{datetime.now():%H:%M:%S}] {message}\n", tag)
            self.log_text.see(END)
        self.root.after(0, update_log)

    def add_listener(self):
        name = self.entry.get().strip()
        if name and name not in self.listen_list:
            self.listen_list.append(name)
            self.listbox.insert(END, name)
            self.entry.delete(0, END)
            self.save_config()

    def del_listener(self):
        selection = self.listbox.curselection()
        if selection:
            index = selection[0]
            del self.listen_list[index]
            self.listbox.delete(index)
            self.save_config()

    def choose_path(self):
        path = filedialog.askdirectory()
        if path:
            try:
                test_file = os.path.join(path, "wx_test.tmp")
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
                self.save_path = path
                self.path_label.config(text=f"当前路径：{path}")
                self.save_config()
                self.log(f"保存路径已更新至：{path}")
            except Exception as e:
                self.log(f"路径不可用：{str(e)}", error=True)

    def start_listen(self):
        if not self.listen_list:
            self.log("监听列表为空，请先添加监听对象", error=True)
            return  # 提前返回防止空监听
        try:
            self.wx.GetListenMessage()  # 清空历史消息
            for name in self.listen_list:
                self.wx.AddListenChat(who=name, savepic=True)
            
            self.stop_event.clear()
            threading.Thread(target=self._message_loop, daemon=True).start()
            self.start_btn.config(state=DISABLED)
            self.stop_btn.config(state=NORMAL)
            self.log(f"开始监听：{', '.join(self.listen_list)}")
        except Exception as e:
            self.log(f"启动失败：{str(e)}", error=True)

    def _start_file_watcher(self):
        """安全启动文件监控"""
        try:
            if not os.path.exists(self.wxauto_default_path):
                self.log(f"监控目录不存在，尝试创建：{self.wxauto_default_path}")
                os.makedirs(self.wxauto_default_path, exist_ok=True)

            event_handler = WxFileHandler(self._on_file_created)
            self.observer.schedule(
                event_handler,
                self.wxauto_default_path,
                recursive=False
            )
            self.observer.start()
            self.log(f"文件监控已启动，监控路径：{self.wxauto_default_path}")
        except Exception as e:
            self.log(f"启动文件监控失败：{str(e)}", error=True)
    
    def _on_file_created(self, src_path):
        """文件创建事件处理（严格模式）"""
        if self.stop_event.is_set():
            return
        try:
            max_wait = 4  # 最大等待时间延长到4秒
            start_time = time.time()
            sender = None
            
            # 持续检查映射表（频率提升到每秒10次）
            while time.time() - start_time < max_wait:
                with self.lock:
                    if src_path in self.sender_mapping:
                        sender = self.sender_mapping.pop(src_path)
                        break
                time.sleep(1)  # 检查间隔缩短到1秒
                
                # 实时检测停止事件
                if self.stop_event.is_set():
                    return

            if sender:
                self.file_queue.put((src_path, sender))
                self.log(f"✅ 文件匹配成功：{os.path.basename(src_path)} -> {sender}")
            else:
                # self.log(f"❌ 未找到发送者映射：{os.path.basename(src_path)}", error=True)
                # 自动重新加入监控（防止漏文件）
                if os.path.exists(src_path):
                    self.log(f"🔄 重新尝试匹配：{os.path.basename(src_path)}")
                    self.file_queue.put((src_path, None))  # 特殊标记
        except Exception as e:
            self.log(f"文件监控异常：{str(e)}", error=True)





    def stop_listen(self):
        self.stop_event.set()
        self.start_btn.config(state=NORMAL)
        self.stop_btn.config(state=DISABLED)
        self.log("监听已停止")



    def _message_loop(self):
        """消息监听主循环（优化版）"""
        while not self.stop_event.is_set():
            try:
                # 使用remove=True清理已处理消息
                msgs = self.wx.GetListenMessage()
                
                for chat, messages in msgs.items():
                    try:
                        chat_name = self._get_chat_name(chat)
                        for msg in messages:
                            try:
                                if msg.type != 'friend':
                                    pass
                                    
                                # 提前建立文件映射（优化点）
                                if 'wxauto文件' in msg.content:
                                    actual_file = os.path.basename(msg.content)
                                    expected_path = os.path.join(
                                        self.wxauto_default_path,
                                        actual_file
                                    )
                                    sender = msg.sender_remark if hasattr(msg, 'sender_remark') else msg.sender
                                    with self.lock:
                                        self.sender_mapping[expected_path] = chat_name
                                        self.log(f"预映射：{actual_file} -> {chat_name}")
                                    
                            except Exception as e:
                                self.log(f"处理消息异常：{str(e)}", error=True)
                                
                    except Exception as e:
                        self.log(f"处理聊天异常：{str(e)}", error=True)
                
                # 优化为动态休眠（有消息时立即处理）
                time.sleep(0.5 if msgs else 0.1)
            except Exception as e:
                self.log(f"消息循环异常：{str(e)}", error=True)

    def _get_chat_name(self, chat_obj):
        """安全获取聊天名称"""
        try:
            # 官方推荐方式获取聊天窗口信息
            return chat_obj.who
        except AttributeError:
            try:
                # 兼容旧版本获取方式
                return str(chat_obj).split(' for ')[1].split('>')[0].strip()
            except:
                return "未知聊天"

    def _process_queue(self):
        """队列处理（增强校验）"""
        while True:
            try:
                src_path, chat_name = self.file_queue.get(timeout=1)
                
                # 严格模式校验
                if chat_name is None:
                    if os.path.exists(src_path):
                        self.log(f"🔄 触发二次匹配：{os.path.basename(src_path)}")
                        self._on_file_created(src_path)  # 重新处理
                    continue
                    
                if chat_name == "未知":
                    self.log(f"🚫 拒绝未知发送者：{os.path.basename(src_path)}", error=True)
                    return
                    
                self._safe_transfer(src_path, chat_name)
            except queue.Empty:
                continue
            except Exception as e:
                self.log(f"处理失败：{str(e)}", error=True)

    def _safe_transfer(self, src_path, sender):
        """安全转移文件到发送者目录（防冲突版本+日期分类）"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if not os.path.exists(src_path):
                    raise FileNotFoundError("源文件不存在")
                
                # 创建安全目录名
                safe_name = re.sub(r'[\\/*?:"<>|]', '_', sender)
                # 添加日期分类目录
                date_dir = datetime.now().strftime("%Y年%m月%d日")  # 改动点：新增日期目录
                target_dir = os.path.join(self.save_path, safe_name, date_dir)  # 改动点：路径添加日期
                os.makedirs(target_dir, exist_ok=True)
                
                # 生成唯一文件名（四重保障）
                timestamp = datetime.now().strftime("%Y年%m月%d日_%H时%M分%S秒%f")[:-3]  
                file_basename = os.path.basename(src_path)  

                # 保障1：文件内容哈希
                with open(src_path, 'rb') as f:
                    content_hash = hashlib.md5(f.read()).hexdigest()[:8]
                
                # 保障2：随机UUID
                random_uuid = uuid.uuid4().hex[:6]
                
                # 组合文件名
                ext = os.path.splitext(file_basename)[1]
                filename = f"{timestamp}_{safe_name}{ext}"
                dest_path = os.path.join(target_dir, filename)
                
                # 保障3：冲突检测
                if os.path.exists(dest_path):
                    raise FileExistsError("文件名冲突检测")
                
                # 转移文件
                shutil.move(src_path, dest_path)
                self.log(f"[{safe_name}] 已保存：{filename}")
                return True
                
            except FileExistsError:
                # 保障4：冲突时自动追加序号
                base_name = f"{timestamp}_{content_hash}_{random_uuid}_{safe_name}"
                counter = 1
                while True:
                    new_filename = f"{base_name}_({counter}){ext}"
                    new_dest = os.path.join(target_dir, new_filename)
                    if not os.path.exists(new_dest):
                        shutil.move(src_path, new_dest)
                        self.log(f"[{safe_name}] 已保存（冲突解决）：{new_filename}")
                        return True
                    counter += 1
                    
            except Exception as e:
                if attempt == max_retries - 1:
                    self.log(f"最终转移失败：{src_path}", error=True)
                time.sleep(0.5 * (attempt + 1))
        return False



    


    def load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                    
                    self.auto_start = config.get("auto_start", False)# 新增自动启动配置读取
                    if self.auto_start_var:  # 防止初始化时还未创建变量
                        self.auto_start_var.set(self.auto_start)
                    self.listen_list = config.get("listen_list", [])
                    self.save_path = config.get("save_path", os.getcwd())
                    for name in self.listen_list:
                        self.listbox.insert(END, name)
                    self.path_label.config(text=f"当前路径：{self.save_path}")
        except Exception as e:
            self.log(f"配置加载失败：{str(e)}", error=True)



    def save_config(self):
        config = {
            "listen_list": self.listen_list,
            "save_path": self.save_path,
            "auto_start": self.auto_start  # 新增自动启动配置保存
        }
        try:
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            self.log(f"配置保存失败：{str(e)}", error=True)

    def on_close(self):
        self.save_config()
        self.stop_listen()
        self.root.destroy()


    def _toggle_auto_start(self):
        """切换自动启动状态"""
        self.auto_start = self.auto_start_var.get()
        self.save_config()

    def _safe_auto_start(self):
        """安全自动启动"""
        if self.listen_list:  # 再次检查监听列表
            self.start_listen()
        else:
            self.log("自动启动失败：监听列表为空", error=True)


if __name__ == "__main__":
    app = WeChatImageSaver()
    app.root.mainloop()