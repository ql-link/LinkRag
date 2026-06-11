class ParseBaseException(Exception):
    """解析基础异常"""
    pass

class UnsupportedFormatError(ParseBaseException):
    """不支持的文件格式"""
    pass

class ParseTimeoutError(ParseBaseException):
    """解析超时异常"""
    pass