"""进程启动期引导（bootstrap）。

存放必须在业务模块 import 之前执行的环境引导逻辑。

顺序硬约束：``nltk_data.configure_nltk_data_path()`` 必须在任何会触发 NLTK 的依赖
（deepdoc / infinity-sdk / langchain / transformers）被 import 之前调用——因此
``from src.bootstrap import configure_nltk_data_path`` 必须保持为 ``src/main.py``
的第一个项目内 import，且紧随其后立即调用。
"""

from src.bootstrap.nltk_data import configure_nltk_data_path

__all__ = ["configure_nltk_data_path"]
