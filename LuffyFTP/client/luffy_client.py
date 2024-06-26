import optparse
import socket
import json, os


class FtpClient(object):
    """FTP客户端"""

    MSG_SIZE = 1024  # 消息最长1024

    def __init__(self):
        self.username = None

        self.terminal_display = None
        parser = optparse.OptionParser()
        # 对参数输入进行规范并作出提醒
        parser.add_option("-s", "--server", dest="server", help="ftp server ip_addr")
        parser.add_option("-p", "--port", type="int", dest="port", help="ftp server port")
        parser.add_option("-u", "--username", dest="username", help="username info")
        parser.add_option("-P", "--password", dest="password", help="password info")
        self.options, self.args = parser.parse_args()
        # print(self.options, self.args, type(self.options), self.options.server)
        self.argv_verification()
        self.make_connection()

    def argv_verification(self):
        """检查参数合法性"""
        if not self.options.server or not self.options.port:
            exit("Error: must supply server and port parameters")

    def make_connection(self):
        """建立socket链接"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.options.server, self.options.port))

    def get_response(self):
        """获取服务端返回"""
        data = self.sock.recv(self.MSG_SIZE)
        return json.loads(data.decode())

    @property
    def auth(self):
        """用户认证"""
        count = 0
        while count < 3:
            username = input("username:").strip()
            if not username: continue
            password = input("password:").strip()

            cmd = {
                'action_type': 'auth',
                'username': username,
                'password': password,
            }

            self.sock.send(json.dumps(cmd).encode("utf-8"))  # 发送该服务端
            response = self.get_response()
            print("response", response)
            if response.get('status_code') == 200:
                self.username = username
                self.terminal_display = "[%s]>>:" % self.username
                return True
            else:
                print(response.get("status_msg"))
                count += 1

    def interactive(self):
        """处理与FtpServer的所有交互"""
        if self.auth:
            while True:
                user_input = input(self.terminal_display).strip()
                if not user_input: continue

                cmd_list = user_input.split()
                if hasattr(self, "_%s" % cmd_list[0]):
                    func = getattr(self, "_%s" % cmd_list[0])
                    func(cmd_list[1:])

    def parameter_check(self, args, min_args=None, max_args=None, exact_args=None):
        """参数个数合法性检查"""
        if min_args:
            if len(args) < min_args:
                print("must provide at least %s parameters but %s received." % (min_args, len(args)))
                return False
        if max_args:
            if len(args) > max_args:
                print("need  at most %s parameters but %s received." % (max_args, len(args)))
                return False
        if exact_args:
            if len(args) != exact_args:
                print("need exactly %s parameters but %s received." % (exact_args, len(args)))
                return False
        return True

    def send_msg(self, action_type, **kwargs):
        """打包消息并发送到远程"""
        msg_data = {
            'action_type': action_type,
            'fill': ''
        }
        msg_data.update(kwargs)

        bytes_msg = json.dumps(msg_data).encode()
        if self.MSG_SIZE > len(bytes_msg):
            msg_data['fill'] = msg_data['fill'].zfill(self.MSG_SIZE - len(bytes_msg))
            bytes_msg = json.dumps(msg_data).encode()

        self.sock.send(bytes_msg)

    def _ls(self, cmd_args):
        """
        display current dir's file list
        """
        self.send_msg(action_type='ls')
        response = self.get_response()  # 1024
        print(response)
        # ready to send long msg
        if response.get('status_code') == 302:
            cmd_result_size = response.get('cmd_result_size')
            received_size = 0
            cmd_result = 'b'
            while received_size < cmd_result_size:
                if cmd_result_size - received_size < 8192:
                    data = self.sock.recv(cmd_result_size - received_size)
                else:
                    data = self.sock.recv(8192)
                cmd_result += data
                received_size += len(data)
            else:
                print(cmd_result.decode("gbk"))

    def _cd(self, cmd_args):
        """
        change to target dir
        """
        if self.parameter_check(cmd_args, exact_args=1):
            target_dir = cmd_args[0]
            self.send_msg('cd', target_dir=target_dir)
            response = self.get_response()
            print(response)

            if response.get("status_code") == 350:  # dir changed
                # 调试时看一下是该 [/%s] 还是 [\%s]
                self.terminal_display = "[/%s]" % response.get('current_dir')

    def progress_bar(self, total_size):
        """
        显示上传/下载进度条
        """
        current_percent = 0
        last_percent = 0
        while True:
            received_size = yield current_percent
            current_percent = int(received_size / total_size * 100)
            if current_percent > last_percent:
                print("#" * int(current_percent / 2) + "{percent}%".format(percent=current_percent), end='\r',
                      flush=True)
                last_percent = current_percent  # 更新百分比

    def _get(self, cmd_args):
        """download file from ftp server
            1. 拿到文件名
            2.发送到远程
            3.等待服务器返回消息
                3.1.如果文件存在，拿到文件大小
                    3.1.1.循环接收
                3.2.文件如果不存在
                    3.2.1.print status msg
        """
        if self.parameter_check(cmd_args, min_args=1):
            filename = cmd_args[0]
            self.send_msg(action_type='get', filename=filename)
            response = self.get_response()
            if response.get('status_code') == 301:  # file exist, ready to receive
                file_size = response.get('file_size')

                received_size = 0
                progress_generator = self.progress_bar(file_size)
                progress_generator.__next__()

                f = open(filename, "wb")
                while received_size < file_size:
                    if file_size - received_size < 8192:  # last recv
                        data = self.sock.recv(file_size - received_size)
                    else:
                        data = self.sock.recv(8192)

                    received_size += len(data)
                    f.write(data)
                    progress_generator.send(received_size)
                    # print(received_size, file_size)
                else:
                    print("\n")
                    print("---file [%s] recv done, received size [%s]----" % (filename, file_size))
                    f.close()
            else:
                print(response.get('status_msg'))

    def _put(self, cmd_args):
        """
        上传本地文件到服务器
        1. 确保本地文件存在
        2. 拿到文件名和大小放到消息头，发到远程
        3. 打开文件，发送内容
        """
        if self.parameter_check(cmd_args, exact_args=1):
            local_file = cmd_args[0]
            if os.path.isfile(local_file):
                total_size = os.path.getsize(local_file)
                self.send_msg('put', file_size=total_size, filename=local_file)
                f = open(local_file, 'rb')
                uploaded_size = 0
                progress_generator = self.progress_bar(total_size)
                progress_generator.__next__()
                for line in f:
                    self.sock.send(line)
                    uploaded_size += len(line)
                    progress_generator.send(uploaded_size)
                else:
                    print("\n")
                    print('file upload done'.center(50, '-'))
                    f.close()


if __name__ == '__main__':
    client = FtpClient()
    client.interactive()  # 交互
