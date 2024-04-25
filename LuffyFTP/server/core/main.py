import os.path
import socket
from conf import settings
import json, hashlib, os
import configparser
import subprocess
import time

"""处理与客户端所有的交互的socket server"""


class FTPServer(object):
    # 定义状态码
    STATUS_CODE = {
        200: "Passed authentication!",
        201: "Wrong username or password!",
        300: "File does not exist!",
        301: "File exist, and this msg include the file size- !",
        302: "This msg include the msg size!",
        350: "Dir changed!",
        351: "Dir doesn't exit!",
    }

    MSG_SIZE = 1024  # 消息最长1024

    def __init__(self, management_instance):
        self.management_instance = management_instance
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((settings.HOST, settings.PORT))  # 绑定用于通信的地址和端口
        self.sock.listen(settings.MAX_SOCKET_LISTEN)  # 确定可以链接的最大个数
        self.accounts = self.load_accounts()
        self.user_obj = None

    def run_forever(self):
        """启动socket server"""
        print('starting LuffyFtp server on %s:%s'.center(50, '-') % (settings.HOST, settings.PORT))

        while True:
            self.request, self.addr = self.sock.accept()
            print("got a new connection from %s....." % (self.addr,))
            try:
                self.handle()
            except Exception as e:
                print("Error happend with client,close connection.",e)
                self.request.close()


    def handle(self):
        """处理与用户的所有指令交互"""
        while True:
            # 接收客户端发来的信息
            raw_data = self.request.recv(self.MSG_SIZE)
            print('------->', raw_data)
            if not raw_data:
                print("connection %s is lost ..." % (self.addr,))
                del self.request, self.addr
                break

            data = json.loads(raw_data.decode("utf-8"))
            action_type = data.get('action_type')

            if action_type:
                if hasattr(self, "_%s" % action_type):
                    func = getattr(self, "_%s" % action_type)
                    func(data)
            else:  # 检测客户端信息是否合法
                print("invalid command,")

    def load_accounts(self):
        """加载所有账号信息"""
        config_obj = configparser.ConfigParser()
        config_obj.read(settings.ACCOUNT_FILE)

        print(config_obj.sections())
        return config_obj

    def authenticate(self, username, password):
        """用户认证方法"""
        if username in self.accounts:
            _password = self.accounts[username]['password']
            md5_obj = hashlib.md5()
            md5_obj.update(password.encode())
            md5_password = md5_obj.hexdigest()  # 进行加密
            print("passwd:", _password, md5_password)
            if md5_password == _password:
                print("passed authentication...")

                # set user obj
                self.user_obj = self.accounts[username]
                self.user_obj['home'] = os.path.join(settings.USER_HOME_DIR, username)
                # set user home directory

                return True
            else:
                print("wrong username or password")
                return False
        else:
            print("wrong username or password")
            return False

    def send_response(self, status_code, *args, **kwargs):
        """
        打包发送消息给客户端
        :param status_code:
        :param args:
        :param kwargs: {filename:ddd, filesize:666}
        :return:
        """

        data = kwargs
        data['status_code'] = status_code
        data['status_msg'] = self.STATUS_CODE[status_code]
        data['fill'] = ''

        bytes_data = json.dumps(data).encode()

        if len(bytes_data) < self.MSG_SIZE:
            data['fill'] = data['fill'].zfill(self.MSG_SIZE - len(bytes_data))
            bytes_data = json.dumps(data).encode()

        self.request.send(bytes_data)

    def _auth(self, data):
        """处理用户认证请求"""
        print("auth", data)
        if self.authenticate(data.get('username'), data.get('password')):
            print("pass auth...")

            # 1.消息内容，状态码
            # 2.json.dumps
            # 3.encode
            self.send_response(status_code=200)

        else:
            self.send_response(status_code=201)

    def _get(self, data):
        """client downloads file through this method
            1.拿到文件名
            2.判断文件是否存在
                2.1如果存在，返回状态码和文件大小
                    2.1.1打开文件，发送文件内容
                2.2如果不存在，返回状态码
            """
        filename = data.get('filename')
        full_path = os.path.join(self.user_obj['home'], filename)
        if os.path.isfile(full_path):
            filesize = os.stat(full_path).st_size
            self.send_response(301, file_size=filesize)
            print("ready to send file")
            f = open(full_path, 'rb')
            for line in f:
                self.request.send(line)
            else:
                print('file send done...', full_path)
            f.close()
        else:
            self.send_response(300)

    def _put(self, data):
        """
        1. 拿到 local 文件名及大小
        2. 检查本地是否已有相应的文件
            2.1 若有，创建一个新的文件（带时间戳后缀）
            2.2 若没有，创建一个新的文件
        3. 开始接受数据
        """
        local_file = data.get("filename")
        full_path = os.path.join(self.user_current_dir, local_file)  # 相应的文件
        if os.path.isfile(full_path):  # 文件已存在，不能覆盖
            filename = "%s.%s" % (full_path, time.time())
        else:
            filename = full_path

        f = open(filename, "wb")
        total_size = data.get('file_size')
        received_size = 0
        while received_size < total_size:
            if total_size - received_size < 8192:  # last recv
                data = self.request.recv(total_size - received_size)
            else:
                data = self.request.recv(8192)

            received_size += len(data)
            f.write(data)
            print(received_size, total_size)
        else:
            print('file %s received done' % local_file)
            f.close()

    def _ls(self, data):
        """
        run dir command and send result to client
        """
        cmd_obj = subprocess.Popen('dir %s' % self.user_current_dir, shell=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.Popen)  # 没写完，后面的看不清
        stdout = cmd_obj.stdout.read()
        stderr = cmd_obj.stderr.read()

        cmd_result = stdout + stderr

        if not cmd_result:
            cmd_result = b'current dir has no file at all.'

        self.send_response(302, cmd_result_size=len(cmd_result))
        self.request.sendall(cmd_result)

    def _cd(self, data):
        """
        根据用户的 target_dir 改变self.user_current_dir的值
        1.把 target_dir 跟 user_current_dir 拼接
        2.检测要切换的目录是否存在
            2.1 若存在，改变 self.user_current_dir 的值到新路径
            2.2 若不存在，返回错误消息
        """
        target_dir = data.get('target_dir')
        full_path = os.path.abspath(os.path.join(self.user_current_dir, target_dir))
        print("full_path:", full_path)
        if os.path.isdir(full_path):
            if full_path.startwith(self.user_obj['home']):
                self.user_current_dir = full_path
                relative_current_dir = self.user_current_dir.replace(self.user_obj['home'], '')
                self.send_response(350, current_dir=self.user_current_dir)
            else:
                self.send_response(351)

        else:
            self.send_response(351)
