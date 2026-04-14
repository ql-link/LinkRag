"""
CircuitBreaker 熔断器实现
防止连续失败导致的服务雪崩
"""
import asyncio
import time
from enum import Enum
from typing import Callable, Any, Optional

from src.core.llm.exceptions import CircuitBreakerOpenError


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"      # 正常关闭，允许请求通过
    OPEN = "open"          # 打开，拒绝所有请求
    HALF_OPEN = "half_open"  # 半开，允许部分请求通过测试


class CircuitBreaker:
    """熔断器实现

    状态转换：
    - CLOSED → OPEN：连续失败达到阈值
    - OPEN → HALF_OPEN：超过恢复超时时间
    - HALF_OPEN → CLOSED：测试请求成功
    - HALF_OPEN → OPEN：测试请求失败
    """

    def __init__(
        self,
        provider_type: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        recovery_timeout: int = 30,
        half_open_max_calls: int = 3,
    ):
        """
        Args:
            provider_type: Provider 类型标识
            failure_threshold: 打开熔断的连续失败次数
            success_threshold: 关闭熔断的连续成功次数（HALF_OPEN 时）
            recovery_timeout: 尝试恢复的超时时间（秒）
            half_open_max_calls: HALF_OPEN 状态允许的最大并发测试调用
        """
        self.provider_type = provider_type
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """通过熔断器执行调用

        Args:
            func: 异步调用函数
            *args, **kwargs: 函数参数

        Returns:
            函数执行结果

        Raises:
            CircuitBreakerOpenError: 熔断器打开时
        """
        async with self._lock:
            if self.state == CircuitState.OPEN:
                # 检查是否应该转换到 HALF_OPEN
                if self._should_attempt_reset():
                    self._transition_to_half_open()
                else:
                    raise CircuitBreakerOpenError(
                        message=f"Circuit breaker is OPEN for {self.provider_type}",
                        provider_type=self.provider_type,
                    )

            if self.state == CircuitState.HALF_OPEN:
                # HALF_OPEN 状态限制并发测试调用
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerOpenError(
                        message=f"Circuit breaker is HALF_OPEN, max calls reached",
                        provider_type=self.provider_type,
                    )
                self._half_open_calls += 1

        # 执行调用
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            await self.record_success()
            return result

        except Exception as e:
            await self.record_failure()
            raise

    async def record_success(self) -> None:
        """记录一次成功调用"""
        async with self._lock:
            self._failure_count = 0

            if self.state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._transition_to_closed()

    async def record_failure(self) -> None:
        """记录一次失败调用"""
        async with self._lock:
            self._failure_count += 1
            self._success_count = 0
            self._last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                # HALF_OPEN 时失败，直接 OPEN
                self._transition_to_open()

            elif self._failure_count >= self.failure_threshold:
                self._transition_to_open()

    def _should_attempt_reset(self) -> bool:
        """检查是否应该尝试重置熔断器"""
        if self._last_failure_time is None:
            return True
        elapsed = time.time() - self._last_failure_time
        return elapsed >= self.recovery_timeout

    def _transition_to_open(self) -> None:
        """转换到 OPEN 状态"""
        self.state = CircuitState.OPEN
        self._half_open_calls = 0

    def _transition_to_half_open(self) -> None:
        """转换到 HALF_OPEN 状态"""
        self.state = CircuitState.HALF_OPEN
        self._half_open_calls = 0
        self._success_count = 0

    def _transition_to_closed(self) -> None:
        """转换到 CLOSED 状态"""
        self.state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0

    def get_state(self) -> CircuitState:
        """获取当前状态"""
        return self.state

    def reset(self) -> None:
        """手动重置熔断器"""
        self._transition_to_closed()
