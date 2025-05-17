# -*- coding: utf-8 -*-
import time
import datetime
import socket
import threading
import json

#将中文信息转换编码，显示文字、TTS语音都需要转换--------------------------------------------------
def GetChineseCode(inputstr):
    strlen=len(inputstr)
    hexcode = ""
    for num in range(0, strlen):
        str=inputstr[num:num+1]
        sdata = bytes(str, encoding='gbk')  # 将信息转为bytes
        if len(sdata)==1:
            hexcode=hexcode+str
        else:
            hexcode=hexcode+"\\x"+ '%02X' % (sdata[0])+ '%02X' % (sdata[1])
    return hexcode

#获取电脑系统日期时间---------------------------------------------------------------------------
def get_time():
    st = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    st=st[2:19]
    return st

# 接收读卡器发过来的http请求、解析提交上来的信息、回应并驱动读卡器显示文字播报语音--------------------------
def service_client(new_socket):
    request = new_socket.recv(1024).decode('utf-8')
    request_header_lines = request.splitlines()
    requestlines=len(request_header_lines)

    current_time = datetime.datetime.now()
    current_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(current_time_str)

    i = 0
    while i < requestlines:     #打印出提交信息
        print(request_header_lines[i])
        i += 1
    print("\n")

    if request[0:3]=="GET":
        CommitParameter=request_header_lines[0][request_header_lines[0].find("?")+1:request_header_lines[0].find("HTTP/1.1")-1]
    elif request[0:4]=="POST":
        CommitParameter = request_header_lines[requestlines-1]
        if request_header_lines[5]=="Content-Type: application/json":
            CommitParameter = CommitParameter.replace("{", "")        #JSON信息可以引用JSON类来解析，此处统一转化成字符串处理
            CommitParameter = CommitParameter.replace("\"", "")
            CommitParameter = CommitParameter.replace(":", "=")
            CommitParameter = CommitParameter.replace(",", "&")
            CommitParameter = CommitParameter.replace("}", "")

    FieldsList = CommitParameter.split('&')
    heartbeattype=""
    dn=""
    card=""
    scantype=""
    for num in range(0, len(FieldsList)):
        ParaList=FieldsList[num].split('=')
        if ParaList[0]=="info":
            info=ParaList[1].strip()        #接收到的数据包号，需回应该包号
        elif ParaList[0]=="jihao":
            jihao = ParaList[1]             #设备机号(可自编)
        elif ParaList[0]=="cardtype":
            cardtype = ParaList[1]
            typenum=int(cardtype,16) % 16               #typenum=1 ID卡，2 HID卡，3 T5557卡，4 EM4305卡，5 IC卡，6 二代身份证，7 是15693卡，IClass"
            pushortake=int(int(cardtype,16) / 128)      #pushortake=0 表示读卡，>0表示卡离开感应区
        elif ParaList[0]=="card":
            card = ParaList[1].strip()       #接收到的原始16进制卡号，可根据需要自行转换成其他卡号
        elif ParaList[0]=="data":
            data = ParaList[1]              #读取的卡扇区内容
        elif ParaList[0]=="dn":
            dn = ParaList[1].strip()        #设备硬件序列号，出厂时已固化，全球唯一
        elif ParaList[0]=="status":
            status = ParaList[1]    #读卡状态，如密码认证失败为12
        elif ParaList[0]=="heartbeattype":
            heartbeattype = ParaList[1].strip()      #心跳包标识
        elif ParaList[0]=="scantype":
            scantype = ParaList[1].strip()      #扫码标识
        elif ParaList[0]=="input":
            input = ParaList[1]         #输入接口状态
        elif ParaList[0]=="output":
            output = ParaList[1]        #输出接口状态
        elif ParaList[0]=="time":
            time = ParaList[1]          #设备时钟
        elif ParaList[0]=="rand":
            rand = ParaList[1]          #随机数

    if (heartbeattype=="1" and len(dn)==16 and len(info)>0):     # 接收到设备上传的心跳数据包
        ResponseStr = "Response=1"  # Response=1,是固定的回应头信息，设备根据此回应头响应
        ResponseStr = ResponseStr + "," + info  # 接收到的包序号
        ResponseStr = ResponseStr + "," +dn+ GetChineseCode("接收到心跳信息！ ")  # 显示文字 中文要转换编码 {}中的文字可以高亮显示
        ResponseStr = ResponseStr + ",20"  # 显示延时秒
        ResponseStr = ResponseStr + ",1"   # 蜂鸣器响声代码，取什0到12
        ResponseStr = ResponseStr + ","    # TTS中文语音编码

        #ResponseStr="Response=1" + "," + info+",,0,0,"  #正式项目可以用这条不显示文字、不响声、不播报语音的指令来回应心跳，此处加入显示、响声只是用来检测读卡器功能

        new_socket.send(ResponseStr.encode("gbk"))  #心跳也可以不回应，但是Sock连接一定要记得关闭
        new_socket.close()
        print(ResponseStr + "\r\n")

    elif(len(dn)==16 and len(card)>4 and len(info)>0):         #接收到有效的刷卡数据
        if pushortake == 0:
            ChineseVoice = GetChineseCode("[v8]读取卡号[n1]") + card        #[v8]表示本次语音大小 取值 v0 到 v16， [n1]表示数字播报文式
        else:
            ChineseVoice = GetChineseCode("[v8]卡号[n1]") + card + GetChineseCode("离开感应区")

        ResponseStr = "Response=1"                      # Response=1,是固定的回应头信息，设备根据此回应头响应
        ResponseStr = ResponseStr + "," + info          #接收到的包序号
        ResponseStr = ResponseStr + "," + GetChineseCode("{卡号:}")+(card+"        ")[0:12]+get_time()    #显示文字 中文要转换编码 {}中的文字可以高亮显示
        ResponseStr = ResponseStr + ",20"               #显示延时秒
        ResponseStr = ResponseStr + ",1"                #蜂鸣器响声代码，取什0到12
        ResponseStr = ResponseStr + "," + ChineseVoice  #TTS中文语音编码
        ResponseStr = ResponseStr + ",20"               #第1继电器开启延时单位，每单位代表25mm，20*25=500mm,取值0表示关闭继电器
        ResponseStr = ResponseStr + ",30"               #第2继电器开启延时单位，以逗号分隔，总计可控制8个继电器

        new_socket.send(ResponseStr.encode("gbk"))
        new_socket.close()
        print(ResponseStr+"\r\n")

    elif (len(dn) == 16 and len(data) > 0 and len(info) > 0 and scantype=="1"):  # 接收到有效的扫码数据
        ChineseVoice = GetChineseCode("[v8]"+data)
        ResponseStr = "Response=1"  # Response=1,是固定的回应头信息，设备根据此回应头响应
        ResponseStr = ResponseStr + "," + info  # 接收到的包序号
        ResponseStr = ResponseStr + "," + GetChineseCode("{扫码:}") + data + "\\n\\n"  # 显示文字 中文要转换编码 {}中的文字可以高亮显示
        ResponseStr = ResponseStr + ",20"  # 显示延时秒
        ResponseStr = ResponseStr + ",1"  # 蜂鸣器响声代码，取什0到12
        ResponseStr = ResponseStr + "," + ChineseVoice  # TTS中文语音编码
        ResponseStr = ResponseStr + ",20"  # 第1继电器开启延时单位，每单位代表25mm，20*25=500mm,取值0表示关闭继电器
        ResponseStr = ResponseStr + ",30"  # 第2继电器开启延时单位，以逗号分隔，总计可控制8个继电器

        new_socket.send(ResponseStr.encode("gbk"))
        new_socket.close()
        print(ResponseStr + "\r\n")

    else:    #接收到其他未知的信息，直接关闭连接
        new_socket.close()

def main():
    # 用来完成整体的控制
    tcp_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)       # 1.创建套接字
    tcp_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)     # 设置当服务器先close 即服务器端4次挥手之后资源能够立即释放，这样就保证了，下次运行程序时 可以立即绑定设定的端口
    tcp_server_socket.bind(("", 88))                                            # 2.绑定监听端口
    tcp_server_socket.listen(128)                                               # 3.变为监听套接字

    while True:
        new_socket, client_addr = tcp_server_socket.accept()                    # 4.等待新客户端的链接
        t = threading.Thread(target=service_client, args=(new_socket,))         # 5.为这个客户端服务
        t.start()

    tcp_server_socket.close()       # 关闭监听套接字

if __name__ == '__main__':
    main()

