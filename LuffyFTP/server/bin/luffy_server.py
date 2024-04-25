import os, sys  # 添加环境变量

# 使该文件引用server整个模块
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 获得server相对路径
sys.path.append(BASE_DIR)  # 引用server

if __name__ == '__main__':
    from core import management

    argv_parser = management.ManagementTool(sys.argv)
    argv_parser.excute()  #
